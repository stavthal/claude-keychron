#!/usr/bin/env python3
"""Drive the Keychron V1 Max backlight per-key from Claude session state.

F1..F9 each carry one Claude session. F12 is a usage gauge. Everything else
sits at the background hue.

Hooks only record state; this process is the sole renderer. That is deliberate:
the hooks used to paint directly, which knocked the board out of per-key mode
every time one fired.

FIRMWARE CONSTRAINT: per-key brightness does not exist. per_key_rgb_solid()
overwrites each key's V with one global scalar, so a single key cannot be dimmed
or switched off and S=0 is white, not black. "Off" is therefore the background
hue, and blinking alternates a key between its state hue and the background.

SAFETY: RAM-only writes. Never sends 0xA8 0x02 or VIA 0x09 0x03 (the EEPROM
writers), and perkey.py refuses them at the send layer regardless.
"""
import json
import os
import signal
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import kbd       # noqa: E402
import perkey    # noqa: E402
import slots as slotmap  # noqa: E402

SESSIONS = os.path.join(BASE, "state.json")
USAGE = "/tmp/.claude_usage_cache"
PIDFILE = os.path.join(BASE, "daemon.pid")
DISABLED = os.path.join(BASE, "disabled")
STORE = os.path.expanduser("~/Library/Application Support/Claude")

F1_LED = 1                 # verified against hardware: LED 1..12 == F1..F12
SLOTS = 9                  # F1..F9
USAGE_LED = 12             # F12

BACKGROUND = (213, 255)    # magenta. Also means "no session in this slot"
STATE_COLOUR = {
    "working":   (170, 255),   # blue, session is busy
    "attention": (21, 255),    # orange, wants you
    "error":     (0, 255),     # red
    "done":      BACKGROUND,   # finishing is not itself interesting
    "idle":      BACKGROUND,
}
PR_OPEN = (85, 255)            # green: this session has an open PR to check
BLINKING = {"attention", "error"}

TICK = 0.10
BLINK_PERIOD = 0.70        # seconds per on/off half-cycle
EFFECT_CHECK = 5.0         # re-assert per-key mode this often
META_REFRESH = 4.0         # session titles and PR state change slowly
BRIGHTNESS = 220

_running = True


def stop(*_):
    global _running
    _running = False


def read_states():
    try:
        with open(SESSIONS) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def slot_order():
    """slot number -> cli session id, claimed at session start and held."""
    return slotmap.current()


def usage_colour():
    try:
        with open(USAGE) as fh:
            lines = fh.read().splitlines()
        pct = max(0, min(100, max(int(lines[0]), int(lines[1]))))
    except Exception:
        pct = 0
    return (int(85 * (1 - pct / 100.0)), 255)


def build_frame(states, order, meta, blink_on):
    """(hue, sat) for LED indices F1..F9.

    Live state wins over PR status: a session that is working or wants you is
    more urgent than one that merely has a PR sitting open.
    """
    out = []
    for n in range(1, SLOTS + 1):
        cli = order.get(n)
        if not cli:
            out.append(BACKGROUND)
            continue
        state = states.get(cli, {}).get("state", "idle")
        colour = STATE_COLOUR.get(state, BACKGROUND)
        if colour == BACKGROUND and meta.get(cli, {}).get("pr_open"):
            colour = PR_OPEN
        if state in BLINKING and not blink_on:
            colour = BACKGROUND          # no per-key brightness, so blink by hue
        out.append(colour)
    return out


class Board:
    def __init__(self):
        self.ready = False
        self.frame = None
        self.checked = 0.0

    def ensure(self, path, now):
        """Put the board in per-key mode and paint the background once."""
        if self.ready and now - self.checked < EFFECT_CHECK:
            return True
        r = kbd.send(path, [kbd.CMD_CUSTOM_GET, kbd.CHANNEL_RGB_MATRIX,
                            kbd.VAL_EFFECT])
        self.checked = now
        if r and r[3] == perkey.EFFECT_PER_KEY_RGB and self.ready:
            return True
        ok, _ = perkey.enable(path)
        if not ok:
            self.ready = False
            return False
        perkey.set_background(path, *BACKGROUND)
        perkey.set_brightness(path, BRIGHTNESS)
        self.ready = True
        self.frame = None                 # force a repaint
        return True

    def draw(self, path, frame, usage):
        if (frame, usage) == self.frame:
            return
        perkey.paint(path, F1_LED, frame)
        perkey.paint(path, USAGE_LED, [usage])
        self.frame = (frame, usage)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with open(PIDFILE, "w") as fh:
        fh.write(str(os.getpid()))

    board = Board()
    t = 0.0
    meta, order, meta_at = {}, {}, -1e9
    try:
        while _running:
            if os.path.exists(DISABLED):
                board.ready = False
                time.sleep(1.0)
                continue

            path = kbd.find_raw_interface()
            if path is None:                   # unplugged or wireless
                board.ready = False
                time.sleep(1.0)
                continue

            try:
                if not board.ensure(path, t):
                    time.sleep(1.0)
                    t += 1.0
                    continue
                # slot_order() also walks the session store, so refresh both
                # on the same timer rather than on every frame.
                if t - meta_at >= META_REFRESH:
                    meta, order, meta_at = slotmap.session_meta(), slot_order(), t
                blink_on = int(t / BLINK_PERIOD) % 2 == 0
                frame = build_frame(read_states(), order, meta, blink_on)
                board.draw(path, tuple(frame), usage_colour())
            except Exception:
                board.ready = False            # re-init on the next pass

            t += TICK
            time.sleep(TICK)
    finally:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
