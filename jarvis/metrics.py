"""Measures speed and Claude usage of every turn and job, so we tune with real numbers.

    python -m jarvis stats      # summary of the last few days
"""

from __future__ import annotations

import json
import statistics
import threading
import time
from pathlib import Path

_file: Path | None = None
_lock = threading.Lock()


def init(data_dir: Path) -> None:
    global _file
    _file = data_dir / "metrics.jsonl"


def record(kind: str, seconds: float, usage: dict | None = None, **extra) -> None:
    """kind: 'fast' (fast-path command), 'turn' (a conversation reply), 'siri' (full Siri round trip), 'job', 'telegram'."""
    if _file is None:
        return
    usage = usage or {}
    row = {
        "t": round(time.time()), "kind": kind, "seconds": round(seconds, 2),
        "tokens_in": usage.get("input_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "tokens_out": usage.get("output_tokens", 0),
        **extra,
    }
    with _lock, _file.open("a") as f:
        f.write(json.dumps(row) + "\n")


def report(data_dir: Path, days: float = 3) -> str:
    path = data_dir / "metrics.jsonl"
    if not path.exists():
        return "No measurements yet. Talk to Jarvis first."
    since = time.time() - days * 86400
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    rows = [r for r in rows if r["t"] >= since]
    lines = [f"Last {days:g} days:"]
    for kind in ("siri", "fast", "turn", "telegram", "job"):
        group = [r for r in rows if r["kind"] == kind]
        if not group:
            continue
        secs = sorted(r["seconds"] for r in group)
        p90 = secs[min(len(secs) - 1, int(len(secs) * 0.9))]
        fresh = sum(r["tokens_in"] + r["cache_write"] for r in group)
        lines.append(
            f"  {kind:9} {len(group):4} runs | median {statistics.median(secs):6.1f}s  p90 {p90:6.1f}s | "
            f"new tokens {fresh:,}  cached {sum(r['cache_read'] for r in group):,}  "
            f"output {sum(r['tokens_out'] for r in group):,}"
        )
    return "\n".join(lines)
