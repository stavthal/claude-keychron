#!/usr/bin/env python3
"""Keychron V1 Max backlight control over VIA raw HID.

Usage:
    kbd.py probe                 list HID interfaces on the keyboard
    kbd.py version               read the VIA protocol version
    kbd.py color <hue> <sat>     set solid colour (0-255 each)
    kbd.py bright <val>          set brightness (0-255)
    kbd.py effect <id>           set RGB matrix effect (1 = solid colour)
    kbd.py preset <name>         apply a named preset
    kbd.py restore               put back your original lighting
"""
import sys
import hid

VENDOR_ID = 0x3434          # Keychron
RAW_USAGE_PAGE = 0xFF60     # VIA raw HID
RAW_USAGE = 0x61
REPORT_LEN = 32

# VIA protocol
CMD_GET_PROTOCOL = 0x01
CMD_CUSTOM_SET = 0x07
CMD_CUSTOM_GET = 0x08
CMD_CUSTOM_SAVE = 0x09

CHANNEL_RGB_MATRIX = 3
VAL_BRIGHTNESS = 1
VAL_EFFECT = 2
VAL_SPEED = 3
VAL_COLOR = 4

EFFECT_SOLID = 1

# hue, sat, brightness
PRESETS = {
    "idle":     (170, 255, 60),    # dim blue
    "working":  (190, 255, 180),   # purple
    "thinking": (128, 255, 150),   # cyan
    "attention":(21,  255, 255),   # amber, full brightness
    "error":    (0,   255, 255),   # red
    "done":     (85,  255, 120),   # green
}


def find_raw_interface():
    """Return the path of the keyboard's VIA raw HID interface."""
    candidates = [
        d for d in hid.enumerate(VENDOR_ID, 0)
        if d.get("usage_page") == RAW_USAGE_PAGE and d.get("usage") == RAW_USAGE
    ]
    if not candidates:
        return None
    return candidates[0]["path"]


def send(path, payload, read_back=True):
    """Send one VIA command. Returns the response bytes, or None."""
    data = list(payload) + [0x00] * (REPORT_LEN - len(payload))
    dev = hid.device()
    dev.open_path(path)
    try:
        dev.write([0x00] + data)           # leading 0x00 = report ID
        if read_back:
            return dev.read(REPORT_LEN, timeout_ms=500)
    finally:
        dev.close()
    return None


def require_device():
    path = find_raw_interface()
    if path is None:
        sys.exit(
            "No VIA raw HID interface found.\n"
            "  - Is the keyboard connected by USB-C cable? (Bluetooth will not work.)\n"
            "  - Is the side switch set to 'Cable'?\n"
            "  Run 'kbd.py probe' to see what is visible."
        )
    return path


def cmd_probe():
    devices = hid.enumerate(VENDOR_ID, 0)
    if not devices:
        print("No Keychron device (vendor 0x3434) found on USB.")
        print("Connect the USB-C cable and set the side switch to 'Cable'.")
        return
    print(f"Found {len(devices)} interface(s) for vendor 0x3434:\n")
    for d in devices:
        marker = ""
        if d.get("usage_page") == RAW_USAGE_PAGE and d.get("usage") == RAW_USAGE:
            marker = "   <-- VIA raw HID (this is the one)"
        print(f"  product      : {d.get('product_string')}")
        print(f"  product_id   : 0x{d.get('product_id', 0):04X}")
        print(f"  usage_page   : 0x{d.get('usage_page', 0):04X}")
        print(f"  usage        : 0x{d.get('usage', 0):04X}")
        print(f"  interface    : {d.get('interface_number')}{marker}")
        print()


def cmd_version():
    resp = send(require_device(), [CMD_GET_PROTOCOL])
    if not resp:
        sys.exit("No response from keyboard.")
    version = (resp[1] << 8) | resp[2]
    print(f"VIA protocol version: {version}")
    print(f"raw response: {list(resp[:8])}")


def set_value(value_id, *args):
    send(require_device(),
         [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, value_id, *args],
         read_back=False)


def cmd_color(hue, sat):
    set_value(VAL_COLOR, hue, sat)
    print(f"colour set: hue={hue} sat={sat}")


def cmd_bright(val):
    set_value(VAL_BRIGHTNESS, val)
    print(f"brightness set: {val}")


def cmd_effect(eid):
    set_value(VAL_EFFECT, eid)
    print(f"effect set: {eid}")


def cmd_preset(name):
    if name not in PRESETS:
        sys.exit(f"Unknown preset '{name}'. Options: {', '.join(PRESETS)}")
    hue, sat, val = PRESETS[name]
    path = require_device()
    send(path, [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, VAL_EFFECT, EFFECT_SOLID], read_back=False)
    send(path, [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, VAL_COLOR, hue, sat], read_back=False)
    send(path, [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, VAL_BRIGHTNESS, val], read_back=False)
    print(f"preset '{name}': hue={hue} sat={sat} brightness={val}")


def cmd_restore():
    """Reapply the lighting that was saved before any Claude changes."""
    import json, os
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saved_state.json")
    if not os.path.exists(f):
        sys.exit("No saved_state.json found; nothing to restore.")
    s = json.load(open(f))
    path = require_device()
    send(path, [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, VAL_EFFECT, s["effect"]], read_back=False)
    send(path, [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, VAL_COLOR, s["hue"], s["sat"]], read_back=False)
    send(path, [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, VAL_SPEED, s["speed"]], read_back=False)
    send(path, [CMD_CUSTOM_SET, CHANNEL_RGB_MATRIX, VAL_BRIGHTNESS, s["brightness"]], read_back=False)
    print(f"restored original lighting: {s}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "probe":
        cmd_probe()
    elif cmd == "version":
        cmd_version()
    elif cmd == "color":
        cmd_color(int(args[0]), int(args[1]))
    elif cmd == "bright":
        cmd_bright(int(args[0]))
    elif cmd == "effect":
        cmd_effect(int(args[0]))
    elif cmd == "preset":
        cmd_preset(args[0])
    elif cmd == "restore":
        cmd_restore()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
