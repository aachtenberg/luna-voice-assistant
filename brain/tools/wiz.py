"""WiZ smart bulb control."""

import asyncio
from pywizlight import wizlight, PilotBuilder

# Living room WiZ bulbs - controlled as a group
WIZ_DEVICES = {
    "living room": ["192.168.0.132", "192.168.0.129"],
    "living room 1": ["192.168.0.132"],
    "living room 2": ["192.168.0.129"],
}


def _run_async(coro):
    """Run async code in sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=15)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


async def _control_wiz_bulbs(ips: list, action: str, brightness: int = None, color_temp: str = None) -> str:
    """Control WiZ bulbs."""
    results = []

    for ip in ips:
        try:
            bulb = wizlight(ip)

            if action == "on":
                if brightness is not None:
                    # Brightness is 0-255 for WiZ
                    await bulb.turn_on(PilotBuilder(brightness=brightness))
                elif color_temp == "warm":
                    await bulb.turn_on(PilotBuilder(colortemp=2700))
                elif color_temp == "cool" or color_temp == "white" or color_temp == "bright":
                    await bulb.turn_on(PilotBuilder(colortemp=6500))
                else:
                    await bulb.turn_on()
                results.append(f"{ip}: on")
            elif action == "off":
                await bulb.turn_off()
                results.append(f"{ip}: off")
            elif action == "status":
                state = await bulb.updateState()
                if state and state.get_state():
                    brightness_pct = int((state.get_brightness() or 0) / 255 * 100)
                    results.append(f"on ({brightness_pct}%)")
                else:
                    results.append("off")
        except Exception as e:
            results.append(f"{ip}: error - {e}")

    return ", ".join(results)


def control_wiz(name: str, action: str, brightness: int = None, color_temp: str = None) -> str:
    """
    Control WiZ smart bulbs.

    Args:
        name: Light name (e.g., "living room")
        action: Action to perform ("on", "off", "status")
        brightness: Optional brightness percentage (1-100)
        color_temp: Optional color temperature ("warm", "cool", "white", "bright")

    Returns:
        Result message
    """
    name_lower = name.lower().strip()

    # Find matching device(s)
    ips = None
    for device_name, device_ips in WIZ_DEVICES.items():
        if name_lower in device_name or device_name in name_lower:
            ips = device_ips
            break

    if not ips:
        return f"Unknown WiZ light '{name}'. Available: living room"

    # Convert brightness percentage to 0-255
    brightness_value = None
    if brightness is not None:
        brightness_value = int(brightness * 255 / 100)
        brightness_value = max(1, min(255, brightness_value))

    action_lower = action.lower().strip()
    if action_lower not in ("on", "off", "status"):
        return f"Unknown action '{action}'. Use: on, off, status"

    result = _run_async(_control_wiz_bulbs(ips, action_lower, brightness_value, color_temp))

    if action_lower == "on":
        if brightness is not None:
            return f"Living room lights set to {brightness}%"
        elif color_temp:
            return f"Living room lights set to {color_temp}"
        else:
            return "Living room lights turned on"
    elif action_lower == "off":
        return "Living room lights turned off"
    else:
        return f"Living room lights: {result}"


def list_wiz_lights() -> str:
    """
    List all WiZ lights and their current status.

    Returns:
        List of lights with status
    """
    async def get_status():
        results = []
        seen = set()
        for name, ips in WIZ_DEVICES.items():
            if name == "living room":  # Only show the group
                for i, ip in enumerate(ips):
                    if ip in seen:
                        continue
                    seen.add(ip)
                    try:
                        bulb = wizlight(ip)
                        state = await bulb.updateState()
                        if state and state.get_state():
                            brightness_pct = int((state.get_brightness() or 0) / 255 * 100)
                            results.append(f"Living room bulb {i+1}: on ({brightness_pct}%)")
                        else:
                            results.append(f"Living room bulb {i+1}: off")
                    except Exception as e:
                        results.append(f"Living room bulb {i+1}: error")
        return ". ".join(results)

    return _run_async(get_status())
