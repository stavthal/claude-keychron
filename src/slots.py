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


_META_CACHE = {}                       # path -> (mtime, parsed fields or None)


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
    """Give a slot to any live session that predates sticky assignment."""
    meta = session_meta()
    slots = _load()
    missing = [c for c in meta if c not in slots]
    missing.sort(key=lambda c: -meta[c]["last"])
    for cli in missing:
        if len(_load()) >= MAX_SLOTS:
            break
        assign(cli)
