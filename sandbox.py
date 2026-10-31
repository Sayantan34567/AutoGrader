"""Sandbox: compile and run untrusted C programs under hard limits (Linux only).

Every run gets: a wall-clock timeout, CPU-time / address-space / file-size
rlimits (applied with `prlimit`, so no Python code runs between fork and exec,
which keeps it safe even when Streamlit has other threads running), its own
session (the whole process group is killed on timeout), a private empty working
directory and a capped copy of stdout/stderr. Output goes to temp files, not
pipes, so a program that prints forever cannot exhaust the agent's memory.
"""
from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import tempfile
import time

try:  # `resource` only exists on Unix; used as a fallback when prlimit is absent
    import resource
except ImportError:  # pragma: no cover (Windows)
    resource = None

MAX_CAPTURE = 64 * 1024  # bytes of stdout / stderr kept
SUPPORTED = resource is not None and hasattr(os, "killpg")
UNSUPPORTED_MSG = ("The sandbox needs Linux (run inside WSL2 or on the Ubuntu lab PC); "
                   "it cannot run on native Windows.")


def tool_version(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        text = (out.stdout or out.stderr).strip().splitlines()
        return text[0] if text else "unknown"
    except Exception:
        return None


def compile_c(src, out, flags, timeout=60, extra=None):
    """Compile `src` with gcc. Returns dict(ok, stderr, cmd)."""
    cmd = ["gcc"] + flags.split() + [str(src), "-o", str(out), "-lm"] + (extra or [])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"ok": p.returncode == 0, "stderr": p.stderr, "cmd": " ".join(cmd)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stderr": "compiler timed out", "cmd": " ".join(cmd)}
    except FileNotFoundError:
        return {"ok": False, "stderr": "gcc not found (sudo apt install build-essential)",
                "cmd": " ".join(cmd)}


def _limit_args(mem_mb, cpu_s, use_as):
    args = [f"--cpu={cpu_s}", f"--fsize={1 << 20}", "--core=0"]
    if use_as and mem_mb:
        args.append(f"--as={mem_mb << 20}")
    return args


def _preexec(mem_mb, cpu_s, use_as):  # fallback when `prlimit` is not installed
    def apply():
        if use_as and mem_mb:
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1 << 20, 1 << 20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def run_cmd(cmd, stdin_text="", timeout_s=1.0, mem_mb=64, use_as=True, env=None):
    """Run an arbitrary command under limits. Never raises.

    status: ok | nonzero_exit | crash | timeout | error
    """
    if not SUPPORTED:
        return {"status": "error", "rc": None, "signal": None, "stdout": "",
                "stderr": UNSUPPORTED_MSG, "wall_s": 0.0}
    work = tempfile.mkdtemp(prefix="ag_run_")
    try:
        with open(os.path.join(work, "stdin"), "w", newline="") as f:
            f.write(stdin_text)
        fin = open(os.path.join(work, "stdin"), "rb")
        fout = open(os.path.join(work, "stdout"), "wb")
        ferr = open(os.path.join(work, "stderr"), "wb")
        full_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
        if env:
            full_env.update(env)
        cpu_s = max(1, math.ceil(timeout_s) + 1)
        popen_kw = {}
        if shutil.which("prlimit"):
            full_cmd = ["prlimit"] + _limit_args(mem_mb, cpu_s, use_as) + ["--"] + list(cmd)
        else:
            full_cmd = list(cmd)
            popen_kw["preexec_fn"] = _preexec(mem_mb, cpu_s, use_as)
        t0 = time.monotonic()
        status, rc, sig = "ok", 0, None
        try:
            proc = subprocess.Popen(full_cmd, stdin=fin, stdout=fout, stderr=ferr, cwd=work,
                                    env=full_env, start_new_session=True, **popen_kw)
        except Exception as e:  # e.g. exec format error
            return {"status": "error", "rc": None, "signal": None,
                    "stdout": "", "stderr": str(e), "wall_s": 0.0}
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            status, rc = "timeout", None
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        wall = time.monotonic() - t0
        try:  # make sure no straggler survives in the group
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        for h in (fin, fout, ferr):
            h.close()
        if status == "ok":
            if rc is not None and rc < 0:
                status, sig = "crash", signal.Signals(-rc).name
            elif rc == 127 and not os.path.exists(str(cmd[0])) and shutil.which(str(cmd[0])) is None:
                status = "error"
            elif rc != 0:
                status = "nonzero_exit"

        def rd(name):
            with open(os.path.join(work, name), "rb") as h:
                return h.read(MAX_CAPTURE).decode("utf-8", "replace")
        return {"status": status, "rc": rc, "signal": sig,
                "stdout": rd("stdout"), "stderr": rd("stderr"), "wall_s": wall}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def run_binary(binary, stdin_text="", timeout_s=1.0, mem_mb=64, **kw):
    return run_cmd([str(binary)], stdin_text, timeout_s, mem_mb, **kw)
