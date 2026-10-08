"""Smart light control - Kasa switches and Kasa bulbs."""

import asyncio
from kasa import Discover, Module

# Kasa switches
KASA_DEVICES = {
    "kitchen": "192.168.0.133",
    "kitchen light": "192.168.0.133",
    "patio": "192.168.0.179",
    "patio light": "192.168.0.179",
}

# Kasa KL125 bulbs, grouped by room. A room's bulbs are controlled together.
# These need "Third-Party Compatibility" on in the Kasa app: with it off, the
# firmware closes the unauthenticated port 9999 protocol and wants a KLAP login
# that python-kasa cannot complete for these bulbs.
KASA_BULBS = {
    "living room": ["192.168.0.10", "192.168.0.2"],
    "ethan's room": ["192.168.0.59"],
}

# Spoken / LLM name variants -> room key in KASA_BULBS
BULB_ALIASES = {
    "living room lights": "living room",
    "ethans room": "ethan's room",
    "ethan room": "ethan's room",
    "ethan's bedroom": "ethan's room",
    "ethan": "ethan's room",
}

BULB_ACTIONS = ("on", "off", "status", "bright", "warm", "soft", "dim")


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


async def _control_bulb(ip: str, action: str, brightness: int = None) -> str:
    """Control one Kasa bulb. Setting brightness or color temp also turns it on."""
    try:
        dev = await Discover.discover_single(ip, timeout=5)
        await dev.update()
        light = dev.modules[Module.Light]

        if action == "on":
            if brightness is not None:
                await light.set_brightness(brightness)
            else:
                await dev.turn_on()
            return "on"
        elif action == "off":
            await dev.turn_off()
            return "off"
        elif action == "status":
            return f"on ({light.brightness}%)" if dev.is_on else "off"
        elif action == "bright":
            await light.set_color_temp(6500)
            await light.set_brightness(100)
            return "bright white"
        elif action in ("warm", "soft"):
            await light.set_color_temp(2700)
            await light.set_brightness(80)
            return "soft white"
        elif action == "dim":
            await light.set_brightness(20)
            return "dim"
        return f"unknown action {action}"
    except Exception as e:
        return f"error: {e}"


async def _control_bulbs(ips: list, action: str, brightness: int = None) -> list:
    return await asyncio.gather(*(_control_bulb(ip, action, brightness) for ip in ips))


def _find_room(name_lower: str):
    """Match a light name to a KASA_BULBS room, or None."""
    room = BULB_ALIASES.get(name_lower, name_lower)
    if room in KASA_BULBS:
        return room
    for alias, target in BULB_ALIASES.items():
        if alias in name_lower:
            return target
    for room in KASA_BULBS:
        if room in name_lower or name_lower in room:
            return room
    return None


def control_light(name: str, action: str, brightness: int = None) -> str:
    """
    Control a smart light.

    Args:
        name: Name of the light (e.g., "kitchen", "patio", "living room", "ethan's room")
        action: Action to perform ("on", "off", "toggle", "status", "bright", "warm", "dim")
        brightness: Optional brightness percentage (1-100) for bulbs

    Returns:
        Result message
    """
    name_lower = name.lower().strip()
    action_lower = action.lower().strip()

    room = _find_room(name_lower)
    if room:
        label = room[0].upper() + room[1:] + " lights"
        if action_lower == "toggle":
            states = _run_async(_control_bulbs(KASA_BULBS[room], "status"))
            if all(s.startswith("error") for s in states):
                return f"Couldn't reach the {room} lights: {states[0]}"
            action_lower = "off" if any(s.startswith("on") for s in states) else "on"
        if action_lower not in BULB_ACTIONS:
            return f"Unknown action '{action}'. Use: on, off, toggle, status, bright, warm/soft, dim"

        bri = None
        if brightness is not None:
            try:
                bri = max(1, min(100, int(str(brightness).strip().rstrip("%"))))
            except (TypeError, ValueError):
                return f"Invalid brightness '{brightness}'. Use a number from 1 to 100"

        results = _run_async(_control_bulbs(KASA_BULBS[room], action_lower, bri))
        errors = [r for r in results if r.startswith("error")]
        if errors and len(errors) == len(results):
            return f"Couldn't reach the {room} lights: {errors[0]}"

        if action_lower == "on":
            msg = f"{label} set to {bri}%" if bri is not None else f"{label} turned on"
        elif action_lower == "off":
            msg = f"{label} turned off"
        elif action_lower == "bright":
            msg = f"{label} set to bright white"
        elif action_lower in ("warm", "soft"):
            msg = f"{label} set to soft white"
        elif action_lower == "dim":
            msg = f"{label} dimmed"
        else:
            msg = f"{label}: {', '.join(results)}"
        if errors:
            msg += f" ({len(errors)} of {len(results)} bulbs didn't respond)"
        return msg

    # Check if it's a Kasa switch
    ip = KASA_DEVICES.get(name_lower)
    if not ip:
        for device_name, device_ip in KASA_DEVICES.items():
            if name_lower in device_name or device_name in name_lower:
                ip = device_ip
                break

    if not ip:
        return f"Unknown light '{name}'. Available: kitchen, patio, living room, Ethan's room"

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

        # Kasa bulbs, by room
        for room, ips in KASA_BULBS.items():
            states = await _control_bulbs(ips, "status")
            states = ["error" if s.startswith("error") else s for s in states]
            results.append(f"{room[0].upper() + room[1:]}: {', '.join(states)}")

        return ". ".join(results)

    return _run_async(get_all_status())
