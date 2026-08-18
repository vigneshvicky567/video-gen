"""shared/proc.run_proc: mandatory-timeout subprocess wrapper with tree-kill.
The one runnable check per behavior: success passthrough, timeout kill (fast,
raises the TimeoutExpired-compatible ProcTimeout), and check=True semantics."""

import os
import subprocess
import sys
import time

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.proc import ProcTimeout, run_proc  # noqa: E402

PY = sys.executable


def test_success_passthrough():
    r = run_proc([PY, "-c", "print('hi')"], timeout=30)
    assert r.returncode == 0
    assert r.stdout.strip() == "hi"


def test_stdin_input():
    r = run_proc([PY, "-c", "import sys; print(sys.stdin.read().upper())"],
                 timeout=30, input="abc")
    assert r.stdout.strip() == "ABC"


def test_timeout_kills_and_raises_promptly():
    t0 = time.perf_counter()
    with pytest.raises(ProcTimeout):
        run_proc([PY, "-c", "import time; time.sleep(60)"], timeout=1)
    # kill + reap must not hang anywhere near the child's 60s sleep
    assert time.perf_counter() - t0 < 15


def test_proc_timeout_is_a_timeout_expired():
    # Existing call sites catch subprocess.TimeoutExpired — must keep matching.
    assert issubclass(ProcTimeout, subprocess.TimeoutExpired)


def test_check_raises_on_nonzero():
    with pytest.raises(subprocess.CalledProcessError):
        run_proc([PY, "-c", "import sys; sys.exit(3)"], timeout=30, check=True)


def test_nonzero_without_check_returns():
    r = run_proc([PY, "-c", "import sys; sys.exit(3)"], timeout=30)
    assert r.returncode == 3
