"""Cross-platform subprocess execution with MANDATORY timeout and tree-kill.

Every pipeline subprocess (ffprobe/ffmpeg/manim/piper/...) should go through
run_proc():

* `timeout` is a required positional — a forgotten timeout has wedged
  thread-pool workers for good (a hung ffprobe on a corrupt file blocks a
  worker forever; under fan-out the whole service seizes).
* On timeout the WHOLE process tree is killed, not just the direct child —
  manim/piper spawn grandchildren (dvisvgm, ffmpeg) that a bare .kill() leaks.
* Works on POSIX (process group via start_new_session + killpg) and Windows
  (new process group + `taskkill /T`), so host-side dev on win32 behaves like
  the Linux containers.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

_IS_WIN = sys.platform == "win32"


class ProcTimeout(subprocess.TimeoutExpired):
    """Raised when run_proc kills a timed-out process tree.

    Subclasses subprocess.TimeoutExpired so existing `except TimeoutExpired`
    call sites keep working.
    """


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child and every descendant."""
    if _IS_WIN:
        # taskkill /T walks the tree; CTRL_BREAK is unreliable for non-console
        # children. Best-effort — the process may already be gone.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()


def run_proc(
    cmd: list[str],
    timeout: float,
    *,
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict | None = None,
    text: bool = True,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """subprocess.run drop-in with required timeout + process-tree kill.

    Returns CompletedProcess(cmd, returncode, stdout, stderr) with output
    always captured. Raises ProcTimeout (a TimeoutExpired subclass) when the
    deadline passes; the whole tree is killed first so nothing leaks.
    """
    kwargs: dict = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        cwd=cwd, text=text)
    if env is not None:
        kwargs["env"] = env
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE
    if _IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)  # reap
        except Exception:
            stdout, stderr = "", ""
        raise ProcTimeout(cmd, timeout, output=stdout, stderr=stderr)

    completed = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd,
                                            output=stdout, stderr=stderr)
    return completed
