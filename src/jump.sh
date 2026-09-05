#!/bin/sh
# Jump to a Claude session by position. Used by the Option+N keybind.
#   jump.sh        -> the session that has waited longest for you
#   jump.sh 3      -> session 3 in `kbd sessions`
# stdin is closed so this can never block when Shortcuts pipes input to it.
exec "$HOME/.claude/keychron/venv/bin/python" \
     "$HOME/.claude/keychron/sessions.py" go "$@" < /dev/null
