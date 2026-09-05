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


def _load():
    try:
        with open(SLOTS_FILE) as fh:
            d = json.load(fh)
        return {k: int(v) for k, v in d.items()} if isinstance(d, dict) else {}
    except Exception:
        return {}


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


def session_meta():
    """cli_session_id -> {title, last, pr_open, local_id} for every live session."""
    out = {}
    for path in glob.glob(os.path.join(STORE, "*", "*", "local_*.json")):
        try:
            with open(path) as fh:
                d = json.load(fh)
        except Exception:
            continue
        cli = d.get("cliSessionId")
        if not cli or d.get("isArchived"):
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
    return out


def assign(cli_id):
    """Claim the lowest free slot for this session. Idempotent."""
    if not cli_id:
        return None
    slots = _load()
    if cli_id in slots:
        return slots[cli_id]

    meta = session_meta()
    # drop holders whose session file is gone entirely
    slots = {k: v for k, v in slots.items() if k in meta or k == cli_id}

    taken = set(slots.values())
    free = next((n for n in range(1, MAX_SLOTS + 1) if n not in taken), None)
    if free is None:
        # evict the least recently active holder
        oldest = min(slots, key=lambda k: meta.get(k, {}).get("last", 0))
        free = slots.pop(oldest)
    slots[cli_id] = free
    _save(slots)
    return free


def release(cli_id):
    slots = _load()
    if slots.pop(cli_id, None) is not None:
        _save(slots)


def current():
    """slot -> cli_session_id, pruned of sessions whose files no longer exist."""
    slots, meta = _load(), session_meta()
    pruned = {k: v for k, v in slots.items() if k in meta}
    if pruned != slots:
        _save(pruned)
    return {v: k for k, v in pruned.items()}


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
