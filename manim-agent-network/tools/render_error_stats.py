#!/usr/bin/env python3
"""Aggregate render failures into a fine-tuning report.

Reads workspace/logs/render_errors.jsonl (written by shared/render_errors.py) and
prints a frequency table by content_type + error_class + source, plus a few sample
error tails per class. Point your prompt/structure tuning at the top rows.

Usage:
  python tools/render_error_stats.py [path/to/render_errors.jsonl] [--samples N]
Default path: ./workspace/logs/render_errors.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    args = [a for a in sys.argv[1:]]
    n_samples = 2
    if "--samples" in args:
        i = args.index("--samples")
        n_samples = int(args[i + 1])
        del args[i:i + 2]
    path = Path(args[0]) if args else Path("workspace/logs/render_errors.jsonl")
    if not path.is_file():
        print(f"no failure log at {path} (nothing has failed, or wrong path)")
        return 0

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not rows:
        print("log is empty")
        return 0

    by_class = Counter((r.get("content_type"), r.get("error_class"), r.get("source")) for r in rows)
    by_ct = Counter(r.get("content_type") for r in rows)
    samples: dict = defaultdict(list)
    for r in rows:
        key = (r.get("content_type"), r.get("error_class"))
        if len(samples[key]) < n_samples:
            err = r.get("error") or {}
            tail = err.get("tail") or err.get("full") or ""
            samples[key].append((r.get("scene_id"), r.get("source"), tail[-280:].replace("\n", " ⏎ ")))

    print(f"=== {len(rows)} render failures across {len(set(r.get('job_id') for r in rows))} jobs ===")
    print(f"by content_type: {dict(by_ct)}\n")
    print(f"{'count':>6}  {'type':<11} {'error_class':<20} {'source'}")
    for (ct, cls, src), c in by_class.most_common():
        print(f"{c:>6}  {str(ct):<11} {str(cls):<20} {src}")

    print("\n--- sample tails (top classes) ---")
    top = [k for k, _ in Counter((r.get('content_type'), r.get('error_class')) for r in rows).most_common(6)]
    for key in top:
        print(f"\n[{key[0]} / {key[1]}]")
        for sid, src, tail in samples.get(key, []):
            print(f"  scene {sid} ({src}): {tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
