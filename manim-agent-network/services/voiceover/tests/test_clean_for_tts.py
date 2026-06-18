"""TDD for _clean_for_tts — the eSpeak phonemizer crashes ("number of lines in
input and output must be equal") on certain characters. These tests use the
REAL narration that crashed job b44dc4a4 (coin-change DP)."""
import sys
from pathlib import Path

# import the function under test without pulling FastAPI app deps
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root for shared.*

from app.main import _clean_for_tts  # noqa: E402


def _is_espeak_safe(s: str) -> bool:
    """No replacement chars, no control chars, no smart quotes/dashes left."""
    if "�" in s:           # U+FFFD replacement char (mojibake) — the crasher
        return False
    if any(ord(c) < 32 for c in s):   # control chars / newlines
        return False
    for bad in "“”‘’–—…":              # smart quotes, dashes, ellipsis
        if bad in s:
            return False
    return True


def test_strips_replacement_char():
    # The exact pattern from the crashing job: "Let<U+FFFD>s define"
    out = _clean_for_tts("Let�s define the exact problem, because coin change.")
    assert "�" not in out, repr(out)
    assert _is_espeak_safe(out)
    assert "Let" in out and "s define" in out


def test_smart_quotes_and_apostrophes():
    out = _clean_for_tts("Let’s create the “DP” recurrence…")
    assert _is_espeak_safe(out), repr(out)


def test_all_real_failing_narration_is_clean():
    import json
    p = Path(__file__).resolve().parents[3] / "_failing_narration.json"
    if not p.exists():
        return  # dump file optional; the inline cases above cover the bug
    texts = json.loads(p.read_text(encoding="utf-8"))
    assert texts, "expected real narration samples"
    for i, t in enumerate(texts):
        cleaned = _clean_for_tts(t)
        assert _is_espeak_safe(cleaned), f"scene {i+1} not espeak-safe: {cleaned!r}"
        assert cleaned, f"scene {i+1} cleaned to empty"


def test_keeps_normal_text_intact():
    out = _clean_for_tts("The answer is two coins.")
    assert out == "The answer is two coins."


def test_empty_after_clean_is_empty_string():
    assert _clean_for_tts("� �").strip() == ""


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
        except Exception:
            failed += 1
            print(f"ERROR {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
