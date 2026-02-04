"""Timer and alarm functionality."""

import threading
import time
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import paho.mqtt.publish as mqtt_publish_msg
from config import MQTT_BROKER, MQTT_PORT

# Store active timers: {timer_id: {"name": str, "end_time": datetime, "thread": Thread}}
ACTIVE_TIMERS = {}
_timer_counter = 0
_lock = threading.Lock()

# MQTT topic for timer announcements
TIMER_TOPIC = "voice-assistant/timer"


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

    # Remove from active timers
    with _lock:
        if timer_id in ACTIVE_TIMERS:
            del ACTIVE_TIMERS[timer_id]

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
            return f"Cancelled timer: {timer_name}"

        return f"Couldn't find a timer matching '{name}'."


def list_timers() -> str:
    """
    List all active timers.

    Returns:
        List of active timers with remaining time
    """
    with _lock:
        if not ACTIVE_TIMERS:
            return "No active timers."

        now = datetime.now(ZoneInfo("America/Toronto"))
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

        return "Active timers: " + ". ".join(timer_list) + ". Read this exactly to the user."
