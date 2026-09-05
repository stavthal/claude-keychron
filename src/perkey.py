#!/usr/bin/env python3
"""Per-key RGB for the Keychron V1 Max on stock firmware 1.1.0+.

Uses Keychron's proprietary raw-HID command 0xA8, which sits outside VIA's
custom-channel space (which is why probing VIA channels never found it).

SAFETY, all verified against Keychron's GPL source:
  * Colours are written to the RAM array HSV per_key_led[81]. No EEPROM writes
    on this path, so streaming is free and nothing survives a power cycle.
  * This module will NEVER emit 0xA8 0x02 (RGB save) or VIA 0x09 0x03
    (custom save). Those are the only EEPROM writers, and the flash is
    wear-levelled with roughly 10k erase cycles.
  * It will NEVER emit 0xAA (wireless DFU), 0xA7/0x11 (factory reset),
    0xAB (factory test), or VIA 0x06/0x0A/0x0B.
  * per_key_rgb_set_led_color() in firmware validates count but NOT start,
    so an out-of-range start writes past the array into adjacent config.
    Every write here is clamped host-side.

KNOWN FIRMWARE LIMITATION: per-key V is discarded. per_key_rgb_solid() does
  hsv = per_key_led[i]; hsv.v = rgb_matrix_config.hsv.v
so hue and saturation are per-key but brightness is one global scalar.
A single key cannot be dimmed or switched off, and S=0 is white, not black.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import kbd  # noqa: E402

LED_COUNT = 81
MAX_PER_PACKET = 9                 # firmware rejects count > 9
KEY_1_LED = 15                     # keys 1..9 are LED indices 15..23
NUM_KEYS = 9

KC_RGB = 0xA8
SUB_GET_VERSION = 0x01
SUB_GET_LED_COUNT = 0x05
SUB_SET_EFFECT = 0x08
SUB_GET_COLOR = 0x09
SUB_SET_COLOR = 0x0A

EFFECT_PER_KEY_RGB = 23            # VIA effect id, per the V1 Max shipped JSON
SUBEFFECT_SOLID = 0x00

# Commands that write flash or are otherwise destructive. Belt and braces:
# nothing in this file constructs them, and send() refuses them anyway.
FORBIDDEN = {
    (0xA8, 0x02): "Keychron RGB save (EEPROM write)",
    (0x09, 0x03): "VIA custom save on channel 3 (EEPROM write)",
    (0xA7, 0x11): "factory reset",
}
FORBIDDEN_CMDS = {
    0xAA: "wireless module DFU",
    0xAB: "factory test",
    0x06: "VIA dynamic keymap reset",
    0x0A: "VIA eeprom reset",
    0x0B: "VIA bootloader jump",
}


def _guard(payload):
    cmd = payload[0]
    if cmd in FORBIDDEN_CMDS:
        raise RuntimeError(f"refusing to send 0x{cmd:02X}: {FORBIDDEN_CMDS[cmd]}")
    if len(payload) > 1 and (cmd, payload[1]) in FORBIDDEN:
        raise RuntimeError(
            f"refusing to send 0x{cmd:02X} 0x{payload[1]:02X}: "
            f"{FORBIDDEN[(cmd, payload[1])]}")


def send(path, payload, read_back=False):
    _guard(payload)
    return kbd.send(path, payload, read_back=read_back)


def enable(path):
    """Switch the board into Per Key RGB mode. RAM only.

    Returns True if the firmware confirms effect 23 took. A lower value means
    this build clamped it, i.e. the effect does not exist here.
    """
    C, CH = kbd.CMD_CUSTOM_SET, kbd.CHANNEL_RGB_MATRIX
    send(path, [C, CH, kbd.VAL_EFFECT, EFFECT_PER_KEY_RGB])
    r = kbd.send(path, [kbd.CMD_CUSTOM_GET, CH, kbd.VAL_EFFECT])
    got = r[3] if r else None
    if got != EFFECT_PER_KEY_RGB:
        return False, got
    send(path, [KC_RGB, SUB_SET_EFFECT, SUBEFFECT_SOLID])
    return True, got


def paint(path, start, colours, batch=True):
    """Write (hue, sat) pairs from LED index `start`. V is ignored by firmware.

    Clamped host-side because the firmware does not bounds-check `start`.
    """
    if start < 0 or start + len(colours) > LED_COUNT:
        raise ValueError(
            f"refusing out-of-range write: start={start} count={len(colours)} "
            f"exceeds {LED_COUNT} LEDs (firmware does not bounds-check this)")
    i = 0
    while i < len(colours):
        chunk = colours[i:i + (MAX_PER_PACKET if batch else 1)]
        payload = [KC_RGB, SUB_SET_COLOR, start + i, len(chunk)]
        for h, s in chunk:
            payload += [h & 0xFF, s & 0xFF, 0]      # V slot present but ignored
        send(path, payload)
        i += len(chunk)


def set_background(path, hue, sat, batch=True):
    """Paint all 81 LEDs. Required: per_key_led[] is loaded from EEPROM at boot,
    so unpainted keys would show whatever was last saved."""
    paint(path, 0, [(hue, sat)] * LED_COUNT, batch=batch)


def set_keys(path, colours, batch=True):
    """colours: list of up to 9 (hue, sat) for keys 1..9."""
    if len(colours) > NUM_KEYS:
        raise ValueError(f"only {NUM_KEYS} key slots")
    paint(path, KEY_1_LED, colours, batch=batch)


def set_brightness(path, val):
    send(path, [kbd.CMD_CUSTOM_SET, kbd.CHANNEL_RGB_MATRIX,
                kbd.VAL_BRIGHTNESS, max(0, min(255, val))])


def read_back(path, start, count):
    r = kbd.send(path, [KC_RGB, SUB_GET_COLOR, start, count])
    # NOTE the offset asymmetry: SET reads HSV from byte 4, the GET reply
    # writes HSV from byte 3 and overwrites its own count field with hue 1.
    return list(r[3:3 + count * 3]) if r else None
