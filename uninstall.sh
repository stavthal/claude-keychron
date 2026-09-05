#!/usr/bin/env bash
# Remove claude-keychron. Restores your keyboard lighting and your settings.json.
set -uo pipefail

DEST="$HOME/.claude/keychron"
BIN="$HOME/.local/bin"
AGENTS="$HOME/Library/LaunchAgents"
GUI="gui/$(id -u)"

say() { printf '  %s\n' "$*"; }

printf '\n== Restoring your keyboard lighting\n'
[ -x "$DEST/venv/bin/python" ] && "$DEST/venv/bin/python" "$DEST/kbd.py" restore 2>/dev/null | sed 's/^/  /'

printf '\n== Stopping and removing the launch agents\n'
for l in lighting hotkeys; do
  launchctl bootout  "$GUI/com.claude-keychron.$l" 2>/dev/null
  launchctl disable  "$GUI/com.claude-keychron.$l" 2>/dev/null
  rm -f "$AGENTS/com.claude-keychron.$l.plist"
  say "com.claude-keychron.$l"
done
pkill -f "keychron/daemon.py"  2>/dev/null
pkill -f "keychron/hotkeys.py" 2>/dev/null

printf '\n== Removing the Claude Code hooks\n'
[ -x "$DEST/venv/bin/python" ] && "$DEST/venv/bin/python" "$DEST/install_hooks.py" uninstall 2>/dev/null | sed 's/^/  /'

printf '\n== Removing files\n'
rm -f "$BIN/kbd"; say "$BIN/kbd"
rm -rf "$DEST";   say "$DEST"

cat <<TXT

Removed.

Revoke Input Monitoring separately if you granted it:
  System Settings > Privacy & Security > Input Monitoring

Your keyboard keeps nothing. Nothing was ever written to its memory, so a
power cycle restores its stored profile regardless.
TXT
