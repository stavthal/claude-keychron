#!/usr/bin/env python3
"""Option+1..9 jumps to the Claude session on F1..F9.

Runs a CGEventTap, which needs Input Monitoring permission. It runs under the
dedicated `venv/bin/kbd-hotkeys-python` copy that install.sh creates, so the
grant is scoped to that binary rather than to every Python script you run. It
is still a general Python interpreter, so anything already running as you could
use it to read keystrokes. Kept in its own process so the lighting daemon never
needs this permission.

Swallowed: Fn+F1..F9, Option+1..9, and Option+F1..F9. Everything else, and any
combination carrying another modifier, passes through untouched.
"""
import os
import signal
import subprocess
import sys

import Quartz
from CoreFoundation import CFRunLoopAddSource, CFRunLoopGetCurrent, kCFRunLoopCommonModes

BASE = os.path.dirname(os.path.abspath(__file__))
JUMP = os.path.join(BASE, "jump.sh")
PIDFILE = os.path.join(BASE, "hotkeys.pid")
DISABLED = os.path.join(BASE, "hotkeys-disabled")

# macOS virtual keycodes. Both the number row and the function row map to the
# same slots, because F5 showing session 5 should mean F5 reaches session 5.
DIGITS = {18: 1, 19: 2, 20: 3, 21: 4, 23: 5, 22: 6, 26: 7, 28: 8, 25: 9}
FKEYS = {122: 1, 120: 2, 99: 3, 118: 4, 96: 5, 97: 6, 98: 7, 100: 8, 101: 9}
KEYCODES = {**DIGITS, **FKEYS}

_TAP = None          # the callback re-enables its own tap through this

FN = Quartz.kCGEventFlagMaskSecondaryFn
SHIFT = Quartz.kCGEventFlagMaskShift
CTRL = Quartz.kCGEventFlagMaskControl
ALT = Quartz.kCGEventFlagMaskAlternate
CMD = Quartz.kCGEventFlagMaskCommand
RELEVANT = SHIFT | CTRL | ALT | CMD


def describe(event):
    """Human-readable keycode + modifier flags, for `kbd hotkeys watch`."""
    code = Quartz.CGEventGetIntegerValueField(
        event, Quartz.kCGKeyboardEventKeycode)
    f = Quartz.CGEventGetFlags(event)
    mods = [n for n, m in (("Fn", FN), ("Shift", SHIFT), ("Ctrl", CTRL),
                           ("Option", ALT), ("Cmd", CMD)) if f & m]
    known = KEYCODES.get(code)
    return (f"keycode {code:>4}  flags 0x{f:08X}  "
            f"[{'+'.join(mods) if mods else 'no modifiers'}]"
            f"{'   -> slot ' + str(known) if known else ''}")


def watch_callback(proxy, etype, event, refcon):
    if etype in (Quartz.kCGEventTapDisabledByTimeout,
                 Quartz.kCGEventTapDisabledByUserInput):
        if _TAP is not None:
            Quartz.CGEventTapEnable(_TAP, True)
        return event
    if etype == Quartz.kCGEventKeyDown:
        sys.stderr.write("  " + describe(event) + "\n")
        sys.stderr.flush()
    return event                      # watch mode never swallows anything


def jump(slot):
    try:
        subprocess.Popen([JUMP, str(slot)],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
    except Exception:
        pass


def callback(proxy, etype, event, refcon):
    # macOS disables a tap that takes too long. Re-arm rather than dying silent.
    if etype in (Quartz.kCGEventTapDisabledByTimeout,
                 Quartz.kCGEventTapDisabledByUserInput):
        if _TAP is not None:
            Quartz.CGEventTapEnable(_TAP, True)
        return event

    if etype != Quartz.kCGEventKeyDown or os.path.exists(DISABLED):
        return event

    code = Quartz.CGEventGetIntegerValueField(
        event, Quartz.kCGKeyboardEventKeycode)
    flags = Quartz.CGEventGetFlags(event)
    mods = flags & RELEVANT          # Shift/Ctrl/Option/Cmd, ignoring Fn

    # Fn + F1..F9, with no other modifier. Verified on a Keychron V1 Max:
    # the board sends the real Apple Fn flag (0x00800000), not a firmware layer.
    if code in FKEYS and (flags & FN) and mods == 0:
        jump(FKEYS[code])
        return None

    # Option + digit, or Option + F-key. Option and nothing else, so
    # Option+Shift+3 and friends still reach the foreground app.
    if mods == ALT:
        slot = KEYCODES.get(code)
        if slot is not None:
            jump(slot)
            return None

    return event


def main():
    global _TAP
    watch = "--watch" in sys.argv
    if not watch:
        with open(PIDFILE, "w") as fh:
            fh.write(str(os.getpid()))

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap,
        Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListenOnly if watch
        else Quartz.kCGEventTapOptionDefault,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
        watch_callback if watch else callback,
        None,
    )
    if not tap:
        sys.stderr.write(
            "hotkeys: could not create the event tap.\n"
            "Grant Input Monitoring to:\n"
            f"  {sys.executable}\n"
            "System Settings > Privacy & Security > Input Monitoring, "
            "then: kbd hotkeys restart\n")
        sys.exit(1)

    _TAP = tap
    Quartz.CGEventTapEnable(tap, True)
    src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)

    def stop(*_):
        Quartz.CFRunLoopStop(CFRunLoopGetCurrent())
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    sys.stderr.write(
        "hotkeys: WATCH MODE, press keys to see what macOS reports. Ctrl-C to quit.\n"
        if watch else
        "hotkeys: listening for Fn+F1..F9 and Option+1..9\n")
    sys.stderr.flush()
    try:
        Quartz.CFRunLoopRun()
    finally:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    main()
