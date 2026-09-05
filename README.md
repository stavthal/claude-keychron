# claude-keychron

Your Keychron's F-keys become a live dashboard of your Claude Code sessions,
and `Option+1..9` jumps straight to the one that needs you.

```
 ESC  F1   F2   F3   F4   F5   F6   F7   F8   F9   F10  F11  F12
      ██   ██   ██   ██   ██   ██   ░░   ░░   ░░             ▓▓
      blue blue orng grn  blue grn  --   --   --            usage
       |         |    |
       |         |    +- session 4 has an open PR to review
       |         +------ session 3 wants your input (blinking)
       +---------------- sessions 1, 2, 5 are working
```

Each running session claims an F-key when it starts and holds it until it ends.
Glance at the board, see which session needs you, press `Option+<n>`, and you
are there.

## What the colours mean

| F-key | Meaning |
|---|---|
| Blue | That session is working |
| Orange, blinking | That session is waiting for your input |
| Red, blinking | That session hit an error |
| Green | That session has an open pull request to check |
| Background | Idle, or no session in that slot |
| **F12** | Usage gauge: green at 0%, red at 100% of your 5-hour limit |

Live state beats PR status, so a session that is working shows blue even with a
PR open, and turns green once it goes quiet.

## Requirements

- **A Keychron keyboard with per-key RGB firmware.** Developed and tested on a
  **V1 Max running firmware v1.1.2**. Keychron added per-key RGB to the Max
  line in the 1.1.0-era updates, so older firmware will not work. Update
  through [Keychron Launcher](https://launcher.keychron.com) if needed.
  Other Keychron QMK boards very likely work, see *Compatibility* below.
- **macOS.** Uses `launchd` and, for the hotkeys, `CGEventTap`.
- **The Claude Code desktop app.** The CLI alone is not enough: slots, titles,
  PR state and jumping all come from the desktop app's session store, and
  jumping needs the app to own the `claude://` scheme.
- **A USB-C cable.** This is not optional, see below.

### The cable is not optional

Control runs over a raw HID interface that only exists on the USB connection.
On Bluetooth or 2.4GHz that interface is absent, every hook silently does
nothing, and the lights stop. Nothing breaks and nothing errors, it just goes
quiet. Set the side switch to `Cable`.

## Install

```bash
git clone https://github.com/stavthal/claude-keychron.git
cd claude-keychron
./install.sh
```

The installer creates a Python venv, installs the `kbd` command to
`~/.local/bin`, sets up two launch agents, saves your existing keyboard
lighting so it can be restored, and adds hooks to `~/.claude/settings.json`
(backing it up first). It is safe to re-run.

Then, for `Option+1..9`:

```bash
kbd hotkeys start
```

It will print the exact binary to grant **Input Monitoring** to. See *Hotkeys*.

## Usage

```bash
kbd status          # everything at a glance
kbd sessions        # your sessions and their F-key slots
kbd go 3            # jump to the session on F3
kbd off             # disable, restore your own lighting
```

<details>
<summary>Full command list</summary>

| Command | Does |
|---|---|
| `kbd on` / `off` / `toggle` | Enable or disable. `off` restores your lighting and persists across reboots |
| `kbd status` | Integration, autostart, hotkeys, keyboard, usage, live sessions |
| `kbd daemon start\|stop\|status` | The lighting renderer, this boot |
| `kbd autostart on\|off\|status\|remove` | Whether it starts at login |
| `kbd hotkeys start\|stop\|restart\|pause\|resume\|status\|log` | `Option+1..9` |
| `kbd sessions` (`ls`) | Numbered session list with slots and PR numbers |
| `kbd go [n]` | Jump to session n (~0.03s). No n = whichever has waited longest |
| `kbd restore` / `kbd save` | Restore your lighting / re-capture it as the baseline |
| `kbd test` | Cycle through every state |
| `kbd install` / `uninstall` | Add or remove the Claude Code hooks |
| `kbd preset <name>` / `color <h> <s>` / `bright <v>` / `effect <id>` | Manual control |
| `kbd probe` / `version` | Diagnostics |

</details>

## Hotkeys

`Fn+F1` through `Fn+F9` jump to the session on that F-key. `Option+1..9` and
`Option+F1..F9` do the same thing, whichever you find easier. This uses a
`CGEventTap`, which needs **Input Monitoring** permission.

> **macOS attributes this permission to the *responsible* process.** Running
> the tap from a terminal can appear to work because the terminal holds the
> grant. Under `launchd` there is no parent to inherit from, so the binary
> itself must be listed. If `kbd hotkeys watch` works but `kbd hotkeys start`
> says refused, that is exactly what has happened.

The installer creates a dedicated copy of the Python interpreter at
`~/.claude/keychron/venv/bin/kbd-hotkeys-python`, and that is the binary you
grant. This is deliberate: granting Input Monitoring to your shared system
Python would cover every Python script you ever run.

**Be clear about what an event tap is.** It sees every keystroke, the same
capability a keylogger has. This one swallows eighteen keycodes: `Fn+F1..F9`,
`Option+1..9`, and `Option+F1..F9`, so the same slot is reachable from either
row. Anything carrying another modifier, and every other key, passes through
untouched. Nothing is logged, stored, or transmitted. It is about 130 lines in
[`src/hotkeys.py`](src/hotkeys.py). Read it before granting anything.

The dedicated interpreter scopes the grant to one binary, but it is still a
general Python interpreter: anything already running as you could use it to
read keystrokes.

`kbd hotkeys stop` revokes it, and you can remove the permission in System
Settings independently of this tool.

## How it works

Three parts.

**Session state** comes from Claude Code hooks (`SessionStart`,
`UserPromptSubmit`, `Notification`, `Stop`, `SessionEnd`) writing to a small
JSON file. Hooks only record state. A separate daemon is the sole renderer,
because painting from a hook knocks the board out of per-key mode.

**Per-key colour** uses Keychron's proprietary raw HID command `0xA8`, which
sits *outside* VIA's custom-channel space. This is why probing VIA channels
finds nothing: an overridden `via_command_kb()` intercepts `0xA8` before VIA's
own dispatch runs.

```
07 03 02 17        VIA: set effect 23 (Per Key RGB). RAM only
08 03 02           VIA: read it back, expect 23
A8 08 00           Keychron: sub-effect SOLID
A8 0A <start> <n>  Keychron: set colours for n LEDs from index start
                   followed by n HSV triples, max 9 LEDs per packet
07 03 01 <val>     VIA: global brightness
```

Colours land in the RAM array `HSV per_key_led[81]`. Nothing is written to
flash, so this is safe to drive continuously.

**Session jumping** uses `claude://resume?session=<uuid>`, a deep link the
Claude desktop app already handles. Note that `claude://code/needs-input` only
moves you when a session is genuinely blocked on a permission prompt, which
makes it useless for jumping on demand.

### Why the code avoids the session store on hot paths

Claude's session records are large and numerous. On the development machine:
**574 files, 310 MB of JSON**. Anything that walks them must not sit on a path
that runs often, and two things did.

**Jumping** resolved a slot by scanning the whole store in a fresh Python
process. Measured at **13.8s per keypress**. `slots.json` already holds the
`slot -> session` mapping, so `slots.lookup()` reads that one file and nothing
else: **0.03s**, a 460x difference.

`slots.current()` still exists and still prunes entries whose session has
disappeared, but pruning costs a full store walk, and a jump does not need it.
A stale entry simply opens a session that has since ended, which is a much
better outcome than a keypress that feels broken. Correctness on a rare edge
case is not worth fourteen seconds on the common one.

**The daemon** called `session_meta()` and `slot_order()` on every 0.10s frame,
each walking the same store, and sat at **8.1% CPU** permanently. Records are
now cached per file on mtime, and both refresh on a 4s timer, since titles and
PR state change slowly. Sustained CPU is now **0.6%**.

If you fork this, the rule is: `slots.json` is the hot path, the session store
is the cold one. Keep it that way.

## Safety

This tool cannot brick your keyboard.

- Every colour write goes to **RAM**. The save commands are never sent
- `src/perkey.py` refuses 8 destructive commands at the send layer, including
  both EEPROM writers (`0xA8 0x02` and VIA `0x09 0x03`), the wireless module
  DFU command (`0xAA`), factory reset and bootloader jump
- The firmware does **not** bounds-check the per-key `start` index, so an
  out-of-range write would corrupt adjacent config. Every write here is clamped
  host-side to the LED count
- **A power cycle always restores your keyboard's stored profile**, whatever
  this code does

Your original lighting is captured at install time and restored by
`kbd restore`, `kbd off`, or `./uninstall.sh`.

## Limitations

- **A single key cannot be dimmed or turned off.** The firmware's
  `per_key_rgb_solid()` overwrites every key's V with one global scalar, so
  brightness is board-wide. `S=0` gives white, not black. "Off" is therefore a
  background hue, and blinking alternates a key's hue rather than its
  brightness.
- **Cable only.** No Bluetooth, no 2.4GHz.
- **Nine sessions.** If all slots are taken, the least recently active is
  evicted.
- **The red error state never fires on its own.** Claude Code has no error
  hook. It is reachable via `kbd preset error`.
- **F12's usage gauge needs `/tmp/.claude_usage_cache`**, a two-line file
  holding your 5-hour and 7-day utilisation percentages. This repo does not
  ship a fetcher for it. Without one, F12 simply sits green.

## Compatibility

Developed against a **Keychron V1 Max, firmware v1.1.2**. The `0xA8` protocol
is Keychron-wide rather than model-specific, so other Keychron QMK boards with
per-key RGB firmware should work, though LED indices differ per layout.

Check yours:

```bash
kbd probe      # needs a 0xFF60 interface
kbd version    # VIA protocol version
```

Then confirm the feature bit, which is a pure read:

```bash
~/.claude/keychron/venv/bin/python - <<'PY'
import os, sys
sys.path.insert(0, os.path.expanduser("~/.claude/keychron"))
import kbd
reply = kbd.send(kbd.require_device(), [0xA2])   # read-only feature query
print("per-key RGB supported:", bool(reply[2] & 0x80))
PY
```

If your layout differs, adjust `F1_LED` and `SLOTS` in `src/daemon.py`. Light a
single LED and look at the board to find the right index.

## Uninstall

```bash
./uninstall.sh
```

Restores your lighting, removes the launch agents, strips the hooks from
`settings.json`, and deletes the install directory. Revoke Input Monitoring
separately if you granted it.

## Licence

MIT. See [LICENSE](LICENSE).

Not affiliated with Keychron or Anthropic.
