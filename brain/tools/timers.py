"""Timer and alarm functionality."""

import threading
import time
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import paho.mqtt.publish as mqtt_publish_msg
from config import MQTT_BROKER, MQTT_PORT

# Store active timers: {timer_id: {"name": str, "end_time": datetime, "thread": Thread}}
ACTIVE_TIMERS = {}
# Store recently expired timers for 30 minutes: {timer_id: {"name": str, "expired_at": datetime}}
EXPIRED_TIMERS = {}
_timer_counter = 0
_lock = threading.Lock()

# MQTT topic for timer announcements
TIMER_TOPIC = "voice-assistant/timer"

# Persistence file path - use data directory for Docker volume mount
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
TIMERS_FILE = DATA_DIR / "timers.json"

# How long to keep expired timers (seconds)
EXPIRED_RETENTION = 1800  # 30 minutes


def _save_timers():
    """Save active timers to disk."""
    with _lock:
        data = {
            "counter": _timer_counter,
            "active": {
                tid: {
                    "name": t["name"],
                    "end_time": t["end_time"].isoformat()
                }
                for tid, t in ACTIVE_TIMERS.items()
            },
            "expired": {
                tid: {
                    "name": t["name"],
                    "expired_at": t["expired_at"].isoformat()
                }
                for tid, t in EXPIRED_TIMERS.items()
            }
        }

    try:
        with open(TIMERS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Timer] Failed to save timers: {e}")


def _load_timers():
    """Load timers from disk and restart active ones."""
    global _timer_counter, ACTIVE_TIMERS, EXPIRED_TIMERS

    if not TIMERS_FILE.exists():
        return

    try:
        with open(TIMERS_FILE) as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Timer] Failed to load timers: {e}")
        return

    _timer_counter = data.get("counter", 0)
    now = datetime.now(ZoneInfo("America/Toronto"))

    # Restore active timers
    for tid, t in data.get("active", {}).items():
        end_time = datetime.fromisoformat(t["end_time"])
        remaining = (end_time - now).total_seconds()

        if remaining > 0:
            # Timer still has time left - restart it
            timer_thread = threading.Timer(remaining, _timer_callback, args=[tid, t["name"]])
            timer_thread.daemon = True
            timer_thread.start()

            ACTIVE_TIMERS[tid] = {
                "name": t["name"],
                "end_time": end_time,
                "thread": timer_thread
            }
            print(f"[Timer] Restored timer '{t['name']}' with {int(remaining)}s remaining")
        else:
            # Timer expired while we were down - move to expired
            EXPIRED_TIMERS[tid] = {
                "name": t["name"],
                "expired_at": end_time
            }
            print(f"[Timer] Timer '{t['name']}' expired while service was down")

    # Restore expired timers (clean up old ones)
    for tid, t in data.get("expired", {}).items():
        expired_at = datetime.fromisoformat(t["expired_at"])
        age = (now - expired_at).total_seconds()

        if age < EXPIRED_RETENTION:
            EXPIRED_TIMERS[tid] = {
                "name": t["name"],
                "expired_at": expired_at
            }

    _save_timers()  # Clean up any expired ones we didn't restore


def _cleanup_expired():
    """Remove expired timers older than retention period."""
    now = datetime.now(ZoneInfo("America/Toronto"))
    to_remove = []

    with _lock:
        for tid, t in EXPIRED_TIMERS.items():
            age = (now - t["expired_at"]).total_seconds()
            if age >= EXPIRED_RETENTION:
                to_remove.append(tid)

        for tid in to_remove:
            del EXPIRED_TIMERS[tid]

    if to_remove:
        _save_timers()


def _parse_duration(duration_str: str) -> int:
    """Parse duration string like '5 minutes', '30 seconds', '1 hour' to seconds."""
    duration_str = duration_str.lower().strip()

    # Handle common patterns
    parts = duration_str.split()
    if len(parts) >= 2:
        try:
            value = int(parts[0])
            unit = parts[1]

            if unit.startswith("second"):
                return value
            elif unit.startswith("minute"):
                return value * 60
            elif unit.startswith("hour"):
                return value * 3600
        except ValueError:
            pass

    # Try to parse just a number (assume minutes)
    try:
        return int(duration_str) * 60
    except ValueError:
        pass

    return 0


def _timer_callback(timer_id: str, name: str):
    """Called when timer expires."""
    print(f"[Timer] Timer '{name}' expired!")
    now = datetime.now(ZoneInfo("America/Toronto"))

    # Move from active to expired
    with _lock:
        if timer_id in ACTIVE_TIMERS:
            del ACTIVE_TIMERS[timer_id]

        EXPIRED_TIMERS[timer_id] = {
            "name": name,
            "expired_at": now
        }

    _save_timers()
    _cleanup_expired()

    # Announce via MQTT
    announcement = f"Timer complete: {name}" if name else "Your timer is done"

    try:
        mqtt_publish_msg.single(
            TIMER_TOPIC,
            payload=json.dumps({"message": announcement, "name": name}),
            hostname=MQTT_BROKER,
            port=MQTT_PORT
        )
        print(f"[Timer] Published to MQTT: {announcement}")
    except Exception as e:
        print(f"[Timer] Failed to publish to MQTT: {e}")


def set_timer(duration: str, name: str = "") -> str:
    """
    Set a timer for the specified duration.

    Args:
        duration: Duration string like "5 minutes", "30 seconds", "1 hour"
        name: Optional name for the timer (e.g., "pasta", "laundry")

    Returns:
        Confirmation message
    """
    global _timer_counter

    seconds = _parse_duration(duration)
    if seconds <= 0:
        return f"I couldn't understand the duration '{duration}'. Try something like '5 minutes' or '30 seconds'."

    with _lock:
        _timer_counter += 1
        timer_id = f"timer_{_timer_counter}"

    end_time = datetime.now(ZoneInfo("America/Toronto")) + timedelta(seconds=seconds)

    # Create timer thread
    timer_thread = threading.Timer(seconds, _timer_callback, args=[timer_id, name])
    timer_thread.daemon = True
    timer_thread.start()

    with _lock:
        ACTIVE_TIMERS[timer_id] = {
            "name": name or f"Timer {_timer_counter}",
            "end_time": end_time,
            "thread": timer_thread
        }

    _save_timers()

    # Format confirmation
    if seconds < 60:
        duration_text = f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        duration_text = f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        hours = seconds // 3600
        remaining_mins = (seconds % 3600) // 60
        duration_text = f"{hours} hour{'s' if hours != 1 else ''}"
        if remaining_mins:
            duration_text += f" and {remaining_mins} minute{'s' if remaining_mins != 1 else ''}"

    timer_name = f" for {name}" if name else ""
    return f"Timer set{timer_name} for {duration_text}."


def cancel_timer(name: str = "") -> str:
    """
    Cancel a timer by name.

    Args:
        name: Name of the timer to cancel (or empty to cancel most recent)

    Returns:
        Confirmation message
    """
    with _lock:
        if not ACTIVE_TIMERS:
            return "There are no active timers to cancel."

        timer_to_cancel = None
        timer_id_to_cancel = None

        if name:
            # Find by name
            for tid, timer in ACTIVE_TIMERS.items():
                if name.lower() in timer["name"].lower():
                    timer_to_cancel = timer
                    timer_id_to_cancel = tid
                    break
        else:
            # Cancel most recent
            timer_id_to_cancel = list(ACTIVE_TIMERS.keys())[-1]
            timer_to_cancel = ACTIVE_TIMERS[timer_id_to_cancel]

        if timer_to_cancel and timer_id_to_cancel:
            timer_to_cancel["thread"].cancel()
            timer_name = timer_to_cancel["name"]
            del ACTIVE_TIMERS[timer_id_to_cancel]
            _save_timers()
            return f"Cancelled timer: {timer_name}"

        return f"Couldn't find a timer matching '{name}'."


def list_timers() -> str:
    """
    List all active timers and recently expired ones.

    Returns:
        List of active timers with remaining time, plus recently expired
    """
    _cleanup_expired()

    with _lock:
        now = datetime.now(ZoneInfo("America/Toronto"))
        results = []

        # Active timers
        if ACTIVE_TIMERS:
            timer_list = []
            for timer in ACTIVE_TIMERS.values():
                remaining = timer["end_time"] - now
                remaining_secs = int(remaining.total_seconds())

                if remaining_secs < 60:
                    time_left = f"{remaining_secs} seconds remaining"
                elif remaining_secs < 3600:
                    mins = remaining_secs // 60
                    secs = remaining_secs % 60
                    if secs > 0:
                        time_left = f"{mins} minutes and {secs} seconds remaining"
                    else:
                        time_left = f"{mins} minute{'s' if mins != 1 else ''} remaining"
                else:
                    hours = remaining_secs // 3600
                    mins = (remaining_secs % 3600) // 60
                    time_left = f"{hours} hour{'s' if hours != 1 else ''} and {mins} minute{'s' if mins != 1 else ''} remaining"

                timer_list.append(f"{timer['name']} has {time_left}")

            results.append("Active timers: " + ". ".join(timer_list))

        # Recently expired timers
        if EXPIRED_TIMERS:
            expired_list = []
            for timer in EXPIRED_TIMERS.values():
                ago = (now - timer["expired_at"]).total_seconds()
                if ago < 60:
                    time_ago = f"{int(ago)} seconds ago"
                else:
                    mins_ago = int(ago // 60)
                    time_ago = f"{mins_ago} minute{'s' if mins_ago != 1 else ''} ago"

                expired_list.append(f"{timer['name']} went off {time_ago}")

            results.append("Recently expired: " + ". ".join(expired_list))

        if not results:
            return "No active or recent timers."

        return " ".join(results)


# Load timers on module import
_load_timers()
