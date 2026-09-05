#!/usr/bin/env bash
# Install claude-keychron. Safe to re-run; it upgrades in place.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.claude/keychron"
BIN="$HOME/.local/bin"
AGENTS="$HOME/Library/LaunchAgents"
GUI="gui/$(id -u)"

say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }

[ "$(uname)" = "Darwin" ] || die "macOS only (launchd and CGEventTap)"
command -v python3 >/dev/null || die "python3 not found"

step "Stopping anything already running"
# Prefer the CLI's own stop, which restores your lighting before returning.
if [ -x "$BIN/kbd" ]; then "$BIN/kbd" daemon stop >/dev/null 2>&1 || true; fi
launchctl bootout "$GUI/com.claude-keychron.lighting" 2>/dev/null || true
launchctl bootout "$GUI/com.claude-keychron.hotkeys"  2>/dev/null || true
pkill -f "keychron/daemon.py"  2>/dev/null || true
pkill -f "keychron/hotkeys.py" 2>/dev/null || true
say "done"

step "Installing to $DEST"
mkdir -p "$DEST"
cp "$SRC"/src/*.py "$SRC"/src/jump.sh "$DEST/"
chmod +x "$DEST"/*.py "$DEST/jump.sh"
say "copied $(ls -1 "$SRC"/src | wc -l | tr -d ' ') files"

step "Python environment"
if [ ! -x "$DEST/venv/bin/python" ]; then
  python3 -m venv "$DEST/venv"
  say "created venv"
fi
"$DEST/venv/bin/pip" install --quiet --upgrade pip
"$DEST/venv/bin/pip" install --quiet hidapi pyobjc-framework-Quartz
say "installed hidapi + pyobjc-framework-Quartz"

# A dedicated interpreter so the Input Monitoring grant is scoped to this tool
# rather than to every Python script on the machine.
REAL="$("$DEST/venv/bin/python" -c 'import sys,os; print(os.path.realpath(sys.executable))')"
cp "$REAL" "$DEST/venv/bin/kbd-hotkeys-python"
chmod +x "$DEST/venv/bin/kbd-hotkeys-python"
say "created kbd-hotkeys-python for the Input Monitoring grant"

step "Installing the kbd command"
mkdir -p "$BIN"
cp "$SRC/bin/kbd" "$BIN/kbd"
chmod +x "$BIN/kbd"
say "$BIN/kbd"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) say "WARNING: $BIN is not on your PATH. Add it to your shell profile:"
     say "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

step "Installing launch agents"
mkdir -p "$AGENTS"
for t in "$SRC"/launchagents/*.plist.template; do
  out="$AGENTS/$(basename "${t%.template}")"
  sed "s|__HOME__|$HOME|g" "$t" > "$out"
  plutil -lint "$out" >/dev/null || die "generated a malformed plist: $out"
  say "$(basename "$out")"
done

step "Saving your current keyboard lighting"
BASELINE=no
if [ -f "$DEST/saved_state.json" ]; then
  # Never overwrite it: on a re-run the board may still be showing OUR colours.
  say "keeping the existing baseline at $DEST/saved_state.json"
  BASELINE=yes
elif "$DEST/venv/bin/python" "$DEST/kbd.py" probe 2>/dev/null | grep -q 0xFF60; then
  "$BIN/kbd" save >/dev/null 2>&1 && { say "saved to $DEST/saved_state.json"; BASELINE=yes; }
else
  say "keyboard not on USB, so there is nothing to save yet."
fi

step "Installing Claude Code hooks"
if [ -f "$HOME/.claude/settings.json" ]; then
  "$DEST/venv/bin/python" "$DEST/install_hooks.py" install | sed 's/^/  /' \
    || say "hook install failed; fix settings.json then run 'kbd install'"
else
  say "no ~/.claude/settings.json found, skipping. Run 'kbd install' later."
fi

step "Starting the lighting daemon"
if [ "$BASELINE" = yes ]; then
  "$BIN/kbd" daemon start | sed 's/^/  /'
else
  say "NOT starting it yet: without a saved baseline, 'kbd restore' and"
  say "'kbd off' would have nothing to put back. Plug the cable in, then:"
  say "  kbd save && kbd daemon start"
fi

cat <<TXT

Installed.

  kbd status          see everything at a glance
  kbd sessions        your sessions and their F-key slots
  kbd go 3            jump to the session on F3

Two things left, both optional:

1. Plug the keyboard in by USB-C and set the side switch to Cable.
   Control is impossible over Bluetooth or 2.4GHz.

2. For Option+1..9 session jumping:
     kbd hotkeys start
   It will tell you to grant Input Monitoring to:
     $DEST/venv/bin/kbd-hotkeys-python
   Add it in System Settings > Privacy & Security > Input Monitoring,
   then: kbd hotkeys restart

To remove everything: ./uninstall.sh
TXT
