#!/usr/bin/env python3
"""List Claude desktop sessions and jump to them via deep link.

    sessions.py list        numbered list, most urgent first
    sessions.py go [n]      jump to session n; with no n, whichever needs you
    sessions.py id <n>      print the local_ id of session n
"""
import glob
import json
import os
import subprocess
import sys
import time

BASE_DIR = os.path.expanduser("~/Library/Application Support/Claude")
# claude-code-sessions is the live store; local-agent-mode-sessions is legacy
# but still holds older sessions, so read both and let ids de-duplicate.
STORES = [os.path.join(BASE_DIR, "claude-code-sessions"),
          os.path.join(BASE_DIR, "local-agent-mode-sessions")]
STATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
PRIORITY = {"attention": 4, "error": 3, "done": 2, "working": 1, "idle": 0}
GLYPH = {"attention": "needs you", "error": "error",
         "done": "finished", "working": "loading", "idle": "idle"}


def _pr(d):
    import slots as slotmap
    return slotmap.pr_status(d)


def states():
    try:
        with open(STATES) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def sessions():
    """Every non-archived desktop session, most urgent then most recent."""
    st = states()
    out, seen = [], set()
    paths = []
    for store in STORES:
        paths += glob.glob(os.path.join(store, "*", "*", "local_*.json"))
    # newest first, so the surviving record for a de-duplicated session is the
    # most recent one rather than whichever the glob happened to return first
    paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for path in paths:
        try:
            with open(path) as fh:
                d = json.load(fh)
        except Exception:
            continue
        cli = d.get("cliSessionId", "")
        # De-duplicate on the CLI id, not the local_ id: one CLI session can
        # appear under several local_ ids (a resume writes a new record), which
        # would otherwise show the same session twice on the same slot.
        key = cli or d.get("sessionId")
        if d.get("isArchived") or key in seen:
            continue
        seen.add(key)
        out.append({
            "local_id": d.get("sessionId", ""),
            "cli_id": cli,
            "title": d.get("title") or "(untitled)",
            "cwd": os.path.basename(d.get("cwd", "") or ""),
            "last": d.get("lastActivityAt", 0),
            "state": st.get(cli, {}).get("state", "idle"),
            "pr_open": _pr(d)[1],
            "pr_number": _pr(d)[0],
        })
    # Slots come from slots.py, claimed at session start and held until it
    # ends, so F3 keeps meaning the same session. The daemon reads the same map.
    import slots as slotmap
    owner = {cli: n for n, cli in slotmap.current().items()}
    for row in out:
        row["slot"] = owner.get(row["cli_id"])
    out.sort(key=lambda s: -s["last"])
    return out


def by_urgency(rows):
    """Display order only. The slot number travels with the row."""
    return sorted(rows, key=lambda s: (-PRIORITY.get(s["state"], 0), -s["last"]))


def cmd_list():
    ss = [s for s in sessions() if s["slot"]]
    if not ss:
        print("no sessions found")
        return
    now = time.time()
    for s in by_urgency(ss):
        i = s["slot"]
        age = now - (s["last"] / 1000.0 if s["last"] > 1e11 else s["last"])
        if age < 3600:
            ago = f"{int(age/60)}m"
        elif age < 86400:
            ago = f"{int(age/3600)}h"
        else:
            ago = f"{int(age/86400)}d"
        pr = f"PR#{s['pr_number']}" if s.get("pr_open") else ""
        print(f"  F{i}  {GLYPH.get(s['state'], s['state']):10s} "
              f"{s['title'][:34]:34s} {s['cwd'][:16]:16s} {pr:>7s} {ago:>4s} ago")


def jump(cli_id):
    """Focus a specific session.

    Uses claude://resume, which takes the CLI uuid and works for any session.
    claude://code/needs-input only moves when a session is genuinely blocked
    on a permission prompt, so it is no use for jumping on demand.
    """
    subprocess.run(["open", f"claude://resume?session={cli_id}"], check=False)


def cmd_go(arg):
    if arg is None:                       # whichever session waited longest
        subprocess.run(
            ["open", "claude://code/needs-input?source=kbd"], check=False)
        print("jumped to the session waiting longest for you")
        return

    # Fast path. slots.json already maps slot -> cli id, so a jump needs one
    # small file rather than a scan of every session record. The full scan is
    # ~14s here (574 files, 310MB of JSON); this is ~0.15s.
    try:
        import slots as slotmap
        cli = slotmap.lookup(int(arg))
        if cli:
            jump(cli)
            print(f"jumped to slot {arg}")
            return
    except Exception:
        pass                              # fall through to the full lookup
    n = int(arg)
    match = [s for s in sessions() if s["slot"] == n]
    if not match:
        sys.exit(f"no session in slot {n}")
    s = match[0]
    if not s["cli_id"]:
        sys.exit(f"session {n} has no CLI id; cannot jump to it")
    jump(s["cli_id"])
    print(f"jumped to {n}: {s['title']}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "list":
        cmd_list()
    elif cmd == "go":
        cmd_go(arg)
    elif cmd == "id":
        import slots as slotmap
        cli = slotmap.lookup(int(arg))                 # fast path
        if not cli:
            m = [s for s in sessions() if s["slot"] == int(arg)]
            cli = m[0]["cli_id"] if m else ""
        print(cli)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
