"""Real-world council mode-switch test against a live script-writer + NVIDIA NIM.

Switch logic (services/script-writer/app/council.py:generate_script):
    full = bool(brief) and (is_study_material or target_duration_seconds > 600)
    mode = "council" if full else "single"

Hits POST /generate per scenario, asserts meta.mode, and prints scene plan so
the switch can be eyeballed against real LLM output.
"""
import sys
import time

import httpx

BASE = "http://127.0.0.1:8001"

# (name, request body, expected mode, why)
CASES = [
    ("short_explainer", {"topic": "How DNS resolution works",
                         "brief": {"target_duration_seconds": 300}},
     "single", "300s < 600 threshold, not study"),

    ("bare_topic_legacy", {"topic": "What is a hash map"},
     "single", "no brief -> full=False"),

    ("boundary_600", {"topic": "The TCP three-way handshake",
                     "brief": {"target_duration_seconds": 600}},
     "single", "600 is NOT > 600 (strict gt) -> single"),

    ("study_override_short", {"topic": "Introduction to derivatives in calculus",
                            "brief": {"target_duration_seconds": 240,
                                       "is_study_material": True,
                                       "audience_level": "beginner"}},
     "council", "is_study_material forces council even at 240s"),

    ("long_form_course", {"topic": "A complete guide to graph algorithms",
                        "brief": {"target_duration_seconds": 1500,
                                   "audience_level": "intermediate",
                                   "focus_areas": ["BFS", "DFS", "Dijkstra", "topological sort"]}},
     "council", "1500s > 600 threshold -> council"),
]


def run():
    results = []
    with httpx.Client(timeout=400.0) as client:
        for name, body, expected, why in CASES:
            print(f"\n=== {name} === (expect: {expected} — {why})")
            t0 = time.time()
            try:
                r = client.post(f"{BASE}/generate", json=body)
                dt = time.time() - t0
                r.raise_for_status()
                data = r.json()
                meta = data.get("meta", {})
                script = data.get("script", {})
                scenes = script.get("scenes", [])
                mode = meta.get("mode")
                audit = meta.get("duration_audit")
                types = [s.get("content_type") for s in scenes]
                ok = mode == expected
                results.append((name, expected, mode, ok))
                print(f"  HTTP {r.status_code}  {dt:.1f}s")
                print(f"  mode        = {mode}   {'PASS' if ok else 'FAIL <<<'}")
                print(f"  title       = {script.get('title')!r}")
                print(f"  scenes      = {len(scenes)}  types={types}")
                est = sum(s.get("estimated_duration_seconds", 0) for s in scenes)
                print(f"  est_total_s = {est}")
                if audit:
                    print(f"  audit       = within={audit.get('within_tolerance')} "
                          f"dev={audit.get('deviation_pct')}% est={audit.get('estimated_seconds')}s")
                if meta.get("warnings"):
                    print(f"  warnings    = {meta['warnings']}")
            except Exception as e:
                dt = time.time() - t0
                results.append((name, expected, f"ERROR: {e}", False))
                print(f"  FAIL <<<  {type(e).__name__}: {e}  ({dt:.1f}s)")

    print("\n" + "=" * 60)
    print(f"{'scenario':<22}{'expect':<10}{'got':<12}{'result'}")
    print("-" * 60)
    passed = 0
    for name, expected, got, ok in results:
        got_s = got if isinstance(got, str) else str(got)
        print(f"{name:<22}{expected:<10}{got_s[:11]:<12}{'PASS' if ok else 'FAIL'}")
        passed += ok
    print("-" * 60)
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(run())
