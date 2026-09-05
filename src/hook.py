#!/usr/bin/env python3
"""Claude Code -> Keychron V1 Max backlight bridge.

Called from Claude Code hooks:  hook.py <state>
States: start | working | attention | idle | end

Never fails loudly. Any error exits 0 so a keyboard problem can never
break a Claude Code session. Set KBD_LIGHTS=0 to disable entirely.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SESSIONS_FILE = os.path.join(BASE, "state.json")
USAGE_CACHE = "/tmp/.claude_usage_cache"
SAVED_STATE = os.path.join(BASE, "saved_state.json")
DISABLED_FLAG = os.path.join(BASE, "disabled")

EFFECT_SOLID = 1
EFFECT_BREATHING = 5

# hue, sat, brightness, effect
STATES = {
    "working":   (170, 255, 210, EFFECT_SOLID),      # blue, loading
    "attention": (21,  255, 255, EFFECT_BREATHING),  # orange, needs you
    "error":     (0,   255, 255, EFFECT_SOLID),      # red, something failed
}

# Which state wins when several sessions disagree. Highest number wins.
PRIORITY = {"attention": 4, "error": 3, "done": 2, "working": 1, "idle": 0}


def read_usage_pct():
    """Highest of the 5h / 7d utilisation percentages, or None."""
    try:
        with open(USAGE_CACHE) as fh:
            lines = fh.read().splitlines()
        return max(int(lines[0]), int(lines[1]))
    except Exception:
        return None


def usage_colour():
    """Map usage to hue: 85 (green) at 0%, 0 (red) at 100%."""
    pct = read_usage_pct()
    if pct is None:
        return (85, 255, 150, EFFECT_SOLID)      # unknown -> green
    pct = max(0, min(100, pct))
    hue = int(85 * (1 - pct / 100.0))
    brightness = 150 + int(pct * 1.05)           # 150 -> 255 as the limit nears
    return (hue, 255, brightness, EFFECT_SOLID)


def done_colour():
    """Finished: the usage gauge hue, but breathing so it reads as 'flashing'.

    At low usage that is green flashing, which is the intended signal. At high
    usage it flashes amber or red, which is also true and worth seeing.
    """
    hue, sat, val, _ = usage_colour()
    return (hue, sat, max(val, 190), EFFECT_BREATHING)


def load_states():
    try:
        with open(SESSIONS_FILE) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def track_session(state, session_id):
    """Record this session's state. Returns True if no sessions remain.

    Stores {cli_session_id: {"state": ..., "ts": ...}} so several concurrent
    sessions can be shown and ranked instead of overwriting each other.
    """
    import time
    states = load_states()

    if state == "end":
        states.pop(session_id, None)
    elif session_id:
        states[session_id] = {"state": state, "ts": int(time.time())}

    try:
        with open(SESSIONS_FILE, "w") as fh:
            json.dump(states, fh)
    except Exception:
        pass
    return len(states) == 0


def winning_state(fallback):
    """The most urgent state across every live session."""
    states = load_states()
    if not states:
        return fallback
    best = max(states.values(),
               key=lambda s: PRIORITY.get(s.get("state"), 0))
    return best.get("state", fallback)


def apply(hue, sat, val, effect):
    sys.path.insert(0, BASE)
    import kbd
    path = kbd.find_raw_interface()
    if path is None:
        return                                   # unplugged / wireless: no-op
    C, CH = kbd.CMD_CUSTOM_SET, kbd.CHANNEL_RGB_MATRIX
    kbd.send(path, [C, CH, kbd.VAL_EFFECT, effect], read_back=False)
    kbd.send(path, [C, CH, kbd.VAL_COLOR, hue, sat], read_back=False)
    kbd.send(path, [C, CH, kbd.VAL_BRIGHTNESS, val], read_back=False)


def restore():
    try:
        with open(SAVED_STATE) as fh:
            s = json.load(fh)
    except Exception:
        return
    apply(s["hue"], s["sat"], s["brightness"], s["effect"])


def main():
    if os.environ.get("KBD_LIGHTS") == "0" or os.path.exists(DISABLED_FLAG):
        return
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"

    session_id = ""
    try:
        payload = sys.stdin.read()
        if payload.strip():
            session_id = json.loads(payload).get("session_id", "")
    except Exception:
        pass

    # Claim an F-key slot on start, give it back on end.
    try:
        import slots as _slots
        if state == "start" and session_id:
            _slots.assign(session_id)
        elif state == "end" and session_id:
            _slots.release(session_id)
    except Exception:
        pass

    all_closed = track_session(
        "working" if state == "start" else state, session_id)

    if state == "end":
        if all_closed:
            restore()
        return

    # The daemon is the sole renderer. Painting from a hook would knock the
    # board out of per-key mode, so hooks only ever record state.


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass                                     # never break a session
    sys.exit(0)
