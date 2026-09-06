#!/usr/bin/env python3
"""Sticky F-key slot assignment for Claude sessions.

A session claims a slot when it starts and holds it until it ends, so F3 means
the same session for that session's whole life. Ordering slots by recency (the
previous behaviour) reshuffled keys underneath you while you were looking.

Slots are claimed by the SessionStart hook and released by SessionEnd. If all
nine are taken, the least recently active holder is evicted.
"""
import glob
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
SLOTS_FILE = os.path.join(BASE, "slots.json")
STORE = os.path.expanduser(
    "~/Library/Application Support/Claude/claude-code-sessions")
MAX_SLOTS = 9


def _raw():
    """slots.json exactly as stored, for detecting an un-migrated file."""
    try:
        with open(SLOTS_FILE) as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _load():
    """cli id -> {"slot": int, "local": str}.

    Accepts the older cli -> int shape and upgrades it in memory, so an
    existing slots.json keeps working after an update.
    """
    try:
        with open(SLOTS_FILE) as fh:
            d = json.load(fh)
        if not isinstance(d, dict):
            return {}
    except Exception:
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, dict) and "slot" in v:
            out[k] = {"slot": int(v["slot"]), "local": v.get("local", "")}
        else:
            try:
                out[k] = {"slot": int(v), "local": ""}
            except (TypeError, ValueError):
                continue
    return out


def _save(d):
    try:
        with open(SLOTS_FILE, "w") as fh:
            json.dump(d, fh, indent=2)
    except Exception:
        pass


def pr_status(d):
    """(pr_number, is_open) for a session record.

    Live sessions carry a `prs` array. The flat prNumber/prState pair is the
    older shape and only survives on archived sessions, so both are handled.
    """
    prs = d.get("prs")
    if isinstance(prs, list) and prs:
        open_ones = [p for p in prs if p.get("state") == "OPEN"]
        chosen = open_ones[0] if open_ones else prs[0]
        return chosen.get("prNumber"), bool(open_ones)
    return d.get("prNumber"), d.get("prState") == "OPEN"


CLI_STORE = os.path.expanduser("~/.claude/projects")
CLI_SCAN = 14                          # only the most recent are worth parsing

_META_CACHE = {}                       # path -> (mtime, parsed fields or None)
_CLI_CACHE = {}                        # path -> (mtime, parsed fields or None)


# Transcripts open with injected scaffolding rather than anything the user
# typed, so a naive "first user message" title reads as gibberish.
_SYNTHETIC = ("caveat:", "<local-command", "<command-name", "<command-message",
              "<command-args", "<system-reminder", "<user-prompt-submit-hook",
              "this session is being continued", "<bash-input", "<bash-stdout")


def _first_real_line(text):
    """The first line the user actually typed, or None."""
    if not isinstance(text, str):
        return None
    body = re.sub(r"<[^>]{1,80}>", " ", text)          # drop tag wrappers
    for line in body.splitlines():
        line = " ".join(line.split())
        if not line or len(line) < 3:
            continue
        if any(line.lower().startswith(p) for p in _SYNTHETIC):
            continue
        return line[:60]
    return None


def _cli_title_and_cwd(path):
    """First user message and cwd, read from the head of a transcript.

    Transcripts run to megabytes, so this stops as soon as it has both, and
    never reads past the first 40 lines.
    """
    cwd = title = None
    try:
        with open(path, errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 120:
                    break
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                cwd = cwd or d.get("cwd")
                if not title and d.get("type") == "user":
                    content = (d.get("message") or {}).get("content")
                    text = None
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text = part.get("text")
                                break
                    text = _first_real_line(text)
                    if text:
                        title = text
                if cwd and title:
                    break
    except OSError:
        return None, None
    return title, cwd


def cli_sessions():
    """cli_session_id -> meta for recent Claude Code CLI sessions.

    These live in ~/.claude/projects/<encoded-cwd>/<uuid>.jsonl and never
    appear in the desktop store, so without this a session started in the
    terminal gets a slot from the hook and is then pruned straight back out.

    Stats every transcript (~3700 files, ~0.02s) but parses only the most
    recent CLI_SCAN, because the store runs to hundreds of megabytes.
    """
    rows = []
    try:
        for d in os.scandir(CLI_STORE):
            if not d.is_dir():
                continue
            try:
                for f in os.scandir(d.path):
                    if f.name.endswith(".jsonl"):
                        try:
                            rows.append((f.stat().st_mtime, f.path, f.name[:-6]))
                        except OSError:
                            pass
            except OSError:
                continue
    except OSError:
        return {}
    rows.sort(reverse=True)

    out = {}
    for mtime, path, cli in rows[:CLI_SCAN]:
        hit = _CLI_CACHE.get(path)
        if hit and hit[0] == mtime:
            if hit[1]:
                out[cli] = dict(hit[1], last=int(mtime * 1000))
            continue
        title, cwd = _cli_title_and_cwd(path)
        if not title and not cwd:
            _CLI_CACHE[path] = (mtime, None)
            continue
        meta = {
            "title": title or "(untitled CLI session)",
            "cwd": os.path.basename(cwd or ""),
            "local_id": "",             # no desktop record, so jump via resume
            "pr_open": False,
            "pr_number": None,
            "cli_only": True,
        }
        _CLI_CACHE[path] = (mtime, meta)
        out[cli] = dict(meta, last=int(mtime * 1000))
    return out


def session_meta():
    """cli_session_id -> {title, last, pr_open, local_id} for every live session.

    Session records are large (tens of KB each, hundreds of them) and change
    rarely, so each file is parsed once and reused until its mtime moves.
    Without this a caller that runs in a loop re-parses hundreds of MB.
    """
    out = {}
    for path in glob.glob(os.path.join(STORE, "*", "*", "local_*.json")):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        hit = _META_CACHE.get(path)
        if hit and hit[0] == mtime:
            if hit[1]:
                out[hit[1]["cli"]] = hit[1]["meta"]
            continue
        try:
            with open(path) as fh:
                d = json.load(fh)
        except Exception:
            _META_CACHE[path] = (mtime, None)
            continue
        cli = d.get("cliSessionId")
        if not cli or d.get("isArchived"):
            _META_CACHE[path] = (mtime, None)
            continue
        pr_num, pr_open = pr_status(d)
        out[cli] = {
            "title": d.get("title") or "(untitled)",
            "cwd": os.path.basename(d.get("cwd", "") or ""),
            "last": d.get("lastActivityAt", 0),
            "local_id": d.get("sessionId", ""),
            "pr_open": pr_open,
            "pr_number": pr_num,
        }
        _META_CACHE[path] = (mtime, {"cli": cli, "meta": out[cli]})

    # CLI sessions fill in the gaps. A desktop record always wins, because it
    # carries a real title, PR state and the local_ id needed to navigate.
    for cli, meta in cli_sessions().items():
        out.setdefault(cli, meta)
    return out


def assign(cli_id):
    """Claim the lowest free slot for this session. Idempotent."""
    if not cli_id:
        return None
    slots = _load()
    meta = session_meta()
    local = meta.get(cli_id, {}).get("local_id", "")
    if cli_id in slots:
        if local and slots[cli_id].get("local") != local:
            slots[cli_id]["local"] = local      # a resume writes a new record
            _save(slots)
        return slots[cli_id]["slot"]
    # drop holders whose session file is gone entirely
    slots = {k: v for k, v in slots.items() if k in meta or k == cli_id}

    taken = {v["slot"] for v in slots.values()}
    free = next((n for n in range(1, MAX_SLOTS + 1) if n not in taken), None)
    if free is None:
        # evict the least recently active holder
        oldest = min(slots, key=lambda k: meta.get(k, {}).get("last", 0))
        free = slots.pop(oldest)["slot"]
    slots[cli_id] = {"slot": free, "local": local}
    _save(slots)
    return free


def release(cli_id):
    slots = _load()
    if slots.pop(cli_id, None) is not None:
        _save(slots)


def lookup(slot):
    """cli id for one slot, reading slots.json and nothing else.

    current() prunes dead entries, which costs a walk of the whole session
    store. A jump does not need pruning, and paid ~14s for it. This is ~0.15s,
    which is the difference between a keypress feeling instant and feeling
    broken. A stale entry simply opens a session that has since ended.
    """
    for cli, v in _load().items():
        if v["slot"] == slot:
            return cli, v.get("local", "")
    return None, ""


def current():
    """slot -> cli_session_id, pruned of sessions whose files no longer exist."""
    slots, meta = _load(), session_meta()
    pruned = {k: dict(v) for k, v in slots.items() if k in meta}
    changed = len(pruned) != len(slots)
    for cli, v in pruned.items():               # keep local_ ids fresh
        local = meta.get(cli, {}).get("local_id", "")
        if local and v.get("local") != local:
            v["local"] = local
            changed = True
    # _load() also upgrades the older cli -> int shape, so persist that too.
    if changed or any(not isinstance(x, dict) for x in _raw().values()):
        _save(pruned)
    return {v["slot"]: k for k, v in pruned.items()}


def backfill():
    """Give a slot to any live session that predates sticky assignment.

    Covers CLI sessions too, since session_meta() merges both stores.
    """
    meta = session_meta()
    slots = _load()
    missing = [c for c in meta if c not in slots]
    missing.sort(key=lambda c: -meta[c]["last"])
    for cli in missing:
        if len(_load()) >= MAX_SLOTS:
            break
        assign(cli)
