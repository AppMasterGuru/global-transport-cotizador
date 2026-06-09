#!/usr/bin/env python3
"""
sync_checklist.py — End-of-session MEMORY.md → gt-checklist sync.

Parses MEMORY.md using the same logic as the dashboard's parseMemory.js,
then POSTs all task states to /api/agent-push on the deployed Vercel app.
Run once at the end of every work session.

Usage:
    cd cotizador
    python3 scripts/sync_checklist.py

Config (all optional — falls back to sensible defaults):
    CHECKLIST_URL  — Vercel app URL  (default: https://gt-checklist.vercel.app)
    AGENT_SECRET   — Bearer token    (default: read from .env)
    MEMORY_PATH    — Path to MEMORY.md (default: ../MEMORY.md relative to cotizador/)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent   # scripts/
_ROOT = _HERE.parent                      # cotizador/

def _load_env_file(path: Path) -> None:
    """Minimal .env loader — no dependencies required."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:  # don't override shell env
            os.environ[key] = val

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    _load_env_file(_ROOT / ".env")

# ── Config ────────────────────────────────────────────────────────────────────

CHECKLIST_URL = os.getenv("CHECKLIST_URL", "https://gt-checklist.vercel.app")
AGENT_SECRET  = os.getenv("AGENT_SECRET", "")
MEMORY_PATH   = Path(os.getenv("MEMORY_PATH", str(_ROOT.parent / "MEMORY.md")))


# ── MEMORY.md parser — mirrors parseMemory.js exactly ────────────────────────

def parse_memory(raw: str) -> list[dict]:
    """
    Convert MEMORY.md markdown into a flat list of task dicts.

    ID generation matches parseMemory.js: first task is mem-task-1,
    counted sequentially across all sections. IDs must match so that
    the checklist's Redis state keys are consistent session to session
    (as long as MEMORY.md task order doesn't change).

    Returns:
        [{"id": "mem-task-N", "done": bool, "name": str, "section": str}, ...]
    """
    lines = raw.split("\n")
    sections: list[dict] = []
    current_section: dict | None = None
    task_counter = 0

    for line in lines:
        # ## or ### heading → start new section (same regex as parseMemory.js)
        heading_match = re.match(r"^#{2,3}\s+(.+)", line)
        if heading_match:
            title = re.sub(
                r"[🔧📋📊💬🏗️🚀⚙️✅🔴🟢⚠️]", "", heading_match.group(1)
            ).strip()
            current_section = {
                "id":    f"mem-{len(sections)}",
                "title": title,
                "tasks": [],
            }
            sections.append(current_section)
            continue

        # Task line: - [x] or - [ ] (same regex as parseMemory.js)
        task_match = re.match(r"^\s*[-*]\s*\[([ xX])\]\s*(.+)", line)
        if not task_match:
            continue

        if current_section is None:
            current_section = {"id": "mem-general", "title": "General", "tasks": []}
            sections.append(current_section)

        is_done  = task_match.group(1).lower() == "x"
        raw_name = task_match.group(2).strip()
        task_counter += 1

        # Strip status suffixes for display name (matches parseMemory.js)
        name = re.sub(
            r"\s*[-—–]\s*(BLOCKED|READY|DONE|IN PROGRESS|NEEDS CLIENT|COMPLETE|WIP|TODO)[^$]*",
            "", raw_name, flags=re.IGNORECASE,
        ).strip()
        name = re.sub(
            r"\s*\(BLOCKED\)|\(READY\)|\(DONE\)", "", name, flags=re.IGNORECASE
        ).strip()

        current_section["tasks"].append({
            "id":      f"mem-task-{task_counter}",
            "done":    is_done,
            "name":    name or raw_name,
            "section": current_section["title"],
        })

    # Flatten to a single list (skip empty sections)
    all_tasks: list[dict] = []
    for s in sections:
        all_tasks.extend(s["tasks"])
    return all_tasks


# ── Push to Vercel ────────────────────────────────────────────────────────────

def _post(url: str, payload: dict) -> dict:
    """POST JSON to url with AGENT_SECRET auth. Returns parsed response dict."""
    import urllib.request
    import urllib.error

    body    = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if AGENT_SECRET:
        headers["Authorization"] = f"Bearer {AGENT_SECRET}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
        ) from exc


def push(tasks: list[dict], raw_memory: str) -> None:
    done_count    = sum(1 for t in tasks if t["done"])
    pending_count = len(tasks) - done_count
    now_utc       = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    last_modified = datetime.fromtimestamp(
        MEMORY_PATH.stat().st_mtime, tz=timezone.utc
    ).isoformat()

    # Step 1 — push raw MEMORY.md content so /api/memory can serve it on Vercel
    url_mem = f"{CHECKLIST_URL}/api/memory-push"
    print(f"  → Pushing MEMORY.md content ({len(raw_memory):,} chars) to {url_mem} …")
    try:
        result = _post(url_mem, {"memory_content": raw_memory, "last_modified": last_modified})
        print(f"  ✓ MEMORY.md stored in Redis ({result.get('length', '?')} chars)")
    except RuntimeError as exc:
        print(f"  ERROR pushing MEMORY.md: {exc}")
        sys.exit(1)

    # Step 2 — push task state map so the toggle shows correct checkboxes
    url_push = f"{CHECKLIST_URL}/api/agent-push"
    print(f"  → Pushing {len(tasks)} task states to {url_push} …")
    try:
        result = _post(url_push, {
            "source":       "memory_sync",
            "from_email":   "barney@timebackai.co",
            "subject":      f"MEMORY.md sync — {now_utc}",
            "summary":      (
                f"End-of-session sync — {done_count}/{len(tasks)} tasks complete "
                f"({pending_count} pending). Synced {now_utc}."
            ),
            "task_updates": [{"id": t["id"], "done": t["done"]} for t in tasks],
            "notes": [
                f"{done_count} of {len(tasks)} complete.",
                f"Pending: {pending_count}",
            ],
        })
        applied     = result.get("applied_count", "?")
        redis_label = "Redis ok" if result.get("redis") else "no Redis"
        print(f"  ✓ {applied} states applied ({redis_label})")
    except RuntimeError as exc:
        print(f"  ERROR pushing task states: {exc}")
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("GT Checklist sync — MEMORY.md → gt-checklist.vercel.app")
    print(f"  MEMORY.md : {MEMORY_PATH}")
    print(f"  Checklist : {CHECKLIST_URL}")
    print()

    # Guard: warn if no secret (push will still work if server has no secret set)
    if not AGENT_SECRET:
        print("  WARNING: AGENT_SECRET not set — push may be rejected by the server.")
        print("  Add AGENT_SECRET to cotizador/.env and retry.")
        print()

    # 1. Read MEMORY.md
    if not MEMORY_PATH.exists():
        print(f"  ERROR: MEMORY.md not found at {MEMORY_PATH}")
        print("  Set MEMORY_PATH env var to override the default location.")
        sys.exit(1)

    raw   = MEMORY_PATH.read_text(encoding="utf-8")
    tasks = parse_memory(raw)

    if not tasks:
        print("  ERROR: No tasks found in MEMORY.md (no [x] or [ ] lines detected).")
        sys.exit(1)

    done_count    = sum(1 for t in tasks if t["done"])
    pending_count = len(tasks) - done_count
    print(f"  Parsed {len(tasks)} tasks — {done_count} done, {pending_count} pending")

    # Preview first few
    for t in tasks[:5]:
        marker = "✓" if t["done"] else "·"
        section_label = f"[{t['section'][:30]}]" if t.get("section") else ""
        print(f"    {marker} {t['id']:15s} {section_label} {t['name'][:50]}")
    if len(tasks) > 5:
        print(f"    … and {len(tasks) - 5} more")
    print()

    # 2. Push to Vercel
    push(tasks, raw)

    print()
    print(f"  View checklist : {CHECKLIST_URL}")
    print(f"  Click 'MEMORY.md' toggle in the dashboard to see live state.")


if __name__ == "__main__":
    main()
