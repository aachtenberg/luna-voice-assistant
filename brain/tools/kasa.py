"""Smart light control - Kasa switches and WiZ bulbs."""

import asyncio
from kasa import Discover
from pywizlight import wizlight, PilotBuilder

# Kasa switches
KASA_DEVICES = {
    "kitchen": "192.168.0.133",
    "kitchen light": "192.168.0.133",
    "patio": "192.168.0.179",
    "patio light": "192.168.0.179",
}

# WiZ bulbs - living room is a group of 2 bulbs
WIZ_DEVICES = {
    "living room": ["192.168.0.132", "192.168.0.129"],
    "living room lights": ["192.168.0.132", "192.168.0.129"],
}


def _run_async(coro):
    """Run async code in sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=10)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _control_device(ip: str, action: str) -> str:
    """Control a Kasa device."""
    try:
        dev = await Discover.discover_single(ip, timeout=5)
        await dev.update()

        if action == "on":
            await dev.turn_on()
            return f"Turned on {dev.alias}"
        elif action == "off":
            await dev.turn_off()
            return f"Turned off {dev.alias}"
        elif action == "toggle":
            if dev.is_on:
                await dev.turn_off()
                return f"Turned off {dev.alias}"
            else:
                await dev.turn_on()
                return f"Turned on {dev.alias}"
        elif action == "status":
            status = "on" if dev.is_on else "off"
            return f"{dev.alias} is {status}"
        else:
            return f"Unknown action: {action}"
    except Exception as e:
        return f"Error controlling device: {e}"


async def _control_wiz_bulbs(ips: list, action: str, brightness: int = None) -> str:
    """Control WiZ bulbs."""
    results = []
    for ip in ips:
        try:
            bulb = wizlight(ip)
            if action == "on":
                if brightness is not None:
                    await bulb.turn_on(PilotBuilder(brightness=brightness))
                else:
                    await bulb.turn_on()
                results.append("on")
            elif action == "off":
                await bulb.turn_off()
                results.append("off")
            elif action == "status":
                state = await bulb.updateState()
                if state and state.get_state():
                    bri = int((state.get_brightness() or 0) / 255 * 100)
                    results.append(f"on ({bri}%)")
                else:
                    results.append("off")
            elif action == "bright":
                await bulb.turn_on(PilotBuilder(brightness=255, colortemp=6500))
                results.append("bright white")
            elif action in ("warm", "soft"):
                await bulb.turn_on(PilotBuilder(brightness=200, colortemp=2700))
                results.append("soft white")
            elif action == "dim":
                await bulb.turn_on(PilotBuilder(brightness=50))
                results.append("dim")
        except Exception as e:
            results.append(f"error: {e}")
    return ", ".join(results)


def control_light(name: str, action: str, brightness: int = None) -> str:
    """
    Control a smart light.

    Args:
        name: Name of the light (e.g., "kitchen", "patio", "living room")
        action: Action to perform ("on", "off", "toggle", "status", "bright", "warm", "dim")
        brightness: Optional brightness percentage (1-100) for WiZ bulbs

    Returns:
        Result message
    """
    name_lower = name.lower().strip()
    action_lower = action.lower().strip()

    # Check if it's a WiZ device (living room)
    wiz_ips = None
    for device_name, device_ips in WIZ_DEVICES.items():
        if name_lower in device_name or device_name in name_lower:
            wiz_ips = device_ips
            break

    if wiz_ips:
        # Handle WiZ bulbs
        if action_lower not in ("on", "off", "status", "bright", "warm", "soft", "dim"):
            return f"Unknown action '{action}'. Use: on, off, status, bright, warm/soft, dim"

        # Convert brightness percentage to 0-255
        bri_value = None
        if brightness is not None:
            bri_value = int(int(brightness) * 255 / 100)
            bri_value = max(1, min(255, bri_value))

        result = _run_async(_control_wiz_bulbs(wiz_ips, action_lower, bri_value))

        if action_lower == "on":
            if brightness is not None:
                return f"Living room lights set to {brightness}%"
            return "Living room lights turned on"
        elif action_lower == "off":
            return "Living room lights turned off"
        elif action_lower == "bright":
            return "Living room lights set to bright white"
        elif action_lower in ("warm", "soft"):
            return "Living room lights set to soft white"
        elif action_lower == "dim":
            return "Living room lights dimmed"
        else:
            return f"Living room lights: {result}"

    # Check if it's a Kasa device
    ip = KASA_DEVICES.get(name_lower)
    if not ip:
        for device_name, device_ip in KASA_DEVICES.items():
            if name_lower in device_name or device_name in name_lower:
                ip = device_ip
                break

    if not ip:
        return f"Unknown light '{name}'. Available: kitchen, patio, living room"

    if action_lower not in ("on", "off", "toggle", "status"):
        return f"Unknown action '{action}'. Use: on, off, toggle, or status"

    return _run_async(_control_device(ip, action_lower))


def list_lights() -> str:
    """
    List all available smart lights and their current status.

    Returns:
        List of lights with status
    """
    async def get_all_status():
        results = []

        # Kasa switches
        seen_ips = set()
        for name, ip in KASA_DEVICES.items():
            if ip in seen_ips:
                continue
            seen_ips.add(ip)
            try:
                dev = await Discover.discover_single(ip, timeout=5)
                await dev.update()
                status = "on" if dev.is_on else "off"
                results.append(f"{dev.alias}: {status}")
            except Exception as e:
                results.append(f"{name}: error")

        # WiZ bulbs (living room)
        wiz_status = []
        for ip in WIZ_DEVICES.get("living room", []):
            try:
                bulb = wizlight(ip)
                state = await bulb.updateState()
                if state and state.get_state():
                    bri = int((state.get_brightness() or 0) / 255 * 100)
                    wiz_status.append(f"on ({bri}%)")
                else:
                    wiz_status.append("off")
            except:
                wiz_status.append("error")

        if wiz_status:
            results.append(f"Living room: {', '.join(wiz_status)}")

        return ". ".join(results)

    return _run_async(get_all_status())
