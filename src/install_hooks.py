#!/usr/bin/env python3
"""Add or remove the Keychron hooks in ~/.claude/settings.json.

    install_hooks.py install
    install_hooks.py uninstall

Safe to re-run: an install always strips any previous install first.
A timestamped backup is written before every change.
"""
import collections, datetime, json, os, shutil, sys

SETTINGS = os.path.expanduser("~/.claude/settings.json")
PY = "~/.claude/keychron/venv/bin/python ~/.claude/keychron/hook.py"
MARKER = "keychron/hook.py"


def load():
    if not os.path.exists(SETTINGS):
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        return collections.OrderedDict()
    try:
        with open(SETTINGS) as fh:
            return json.load(fh, object_pairs_hook=collections.OrderedDict)
    except json.JSONDecodeError as e:
        sys.exit(f"{SETTINGS} is not valid JSON ({e}); fix it and re-run "
                 f"'kbd install'")


def strip(hooks):
    """Remove every hook entry this tool previously added."""
    removed = 0
    for event, entries in list(hooks.items()):
        kept = []
        for e in entries:
            before = len(e.get("hooks", []))
            e["hooks"] = [h for h in e.get("hooks", [])
                          if MARKER not in h.get("command", "")]
            removed += before - len(e["hooks"])
            if e["hooks"]:
                kept.append(e)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    return removed


def entry(state, matcher=None, background=True):
    cmd = f"{PY} {state}" + (" >/dev/null 2>&1 &" if background else "")
    e = collections.OrderedDict()
    if matcher is not None:
        e["matcher"] = matcher
    e["hooks"] = [collections.OrderedDict(
        [("type", "command"), ("command", cmd)])]
    return e


# start/end run in the foreground: they need the session id on stdin
ADDITIONS = [
    ("SessionStart",     entry("start",     background=False)),
    ("UserPromptSubmit", entry("working")),
    ("Notification",     entry("attention", matcher="permission_prompt")),
    ("Notification",     entry("attention", matcher="idle_prompt")),
    ("Stop",             entry("idle",      matcher="")),
    ("SessionEnd",       entry("end",       background=False)),
]


def save(cfg):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(SETTINGS, f"{SETTINGS}.bak-keychron-{stamp}")
    with open(SETTINGS, "w") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    json.load(open(SETTINGS))          # fail loudly if we wrote bad JSON
    print(f"backup: {SETTINGS}.bak-keychron-{stamp}")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action not in ("install", "uninstall"):
        sys.exit(__doc__)
    cfg = load()
    hooks = cfg.setdefault("hooks", collections.OrderedDict())
    removed = strip(hooks)
    if action == "uninstall":
        if not removed:
            print("nothing to uninstall; hooks were not present")
            return
        save(cfg)
        print(f"removed {removed} keychron hook(s)")
        return
    for event, e in ADDITIONS:
        hooks.setdefault(event, []).append(e)
    save(cfg)
    print(f"installed {len(ADDITIONS)} keychron hook(s):")
    for event, e in ADDITIONS:
        print(f"  {event:17s} {e['hooks'][0]['command']}")


if __name__ == "__main__":
    main()
