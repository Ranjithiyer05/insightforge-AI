"""Controlled execution of generated analysis code.

Layers, from outermost:
1. Static validation (AST): imports restricted to an allowlist, no exec/eval/
   open/__import__, no dunder attribute access.
2. Separate process with a scrubbed environment (no API keys or other secrets),
   `python -I`, CPU/memory/file-size/process rlimits and a wall-clock timeout.
3. A fresh network namespace via `unshare -rn` when the kernel allows it, so
   the process has no network interfaces at all.
4. An in-process audit hook (see bootstrap.py) that denies sockets,
   subprocesses and file access outside the run directory.

This is process-level isolation. For multi-tenant production use, run the same
runner inside a container or microVM (gVisor, Firecracker); see README.
"""
from __future__ import annotations

import ast
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import settings

HERE = Path(__file__).resolve().parent

ALLOWED_IMPORTS = {
    "ifrt", "pandas", "numpy", "scipy", "statsmodels", "sklearn", "math", "statistics", "json", "warnings",
    "itertools", "collections", "datetime", "sqlite3", "re", "functools", "typing",
}
FORBIDDEN_NAMES = {"exec", "eval", "compile", "open", "__import__", "globals", "locals", "vars", "getattr", "setattr",
                   "delattr", "input", "breakpoint", "memoryview"}


class CodeValidationError(ValueError):
    pass


def validate_code(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CodeValidationError(f"syntax error: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    raise CodeValidationError(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                raise CodeValidationError(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise CodeValidationError(f"use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith("__"):
            raise CodeValidationError(f"access to dunder attribute '{node.attr}' is not allowed")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"system", "popen", "remove", "unlink", "rmtree"}:
            raise CodeValidationError(f"call to '{node.func.attr}' is not allowed")


@lru_cache(maxsize=1)
def netns_available() -> bool:
    if not shutil.which("unshare"):
        return False
    try:
        r = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


@dataclass
class ExecResult:
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    duration_ms: int = 0
    cpu_s: float = 0.0
    isolation: dict[str, Any] = field(default_factory=dict)
    timed_out: bool = False


def _limits(mem_mb: int, cpu_s: int):
    def apply():
        # RLIMIT_DATA caps heap and anonymous mappings (real allocations) rather than reserved
        # address space, which OpenBLAS and thread stacks inflate far beyond actual use.
        resource.setrlimit(resource.RLIMIT_DATA, (mem_mb * 1024 * 1024, mem_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024, 200 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))
        except (ValueError, OSError):
            pass
        os.setsid()
    return apply


def run_code(source: str, data_csv: Path, run_dir: Path, timeout_s: int | None = None) -> ExecResult:
    validate_code(source)
    timeout_s = timeout_s or settings.sandbox_timeout_s
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data_csv, run_dir / "data.csv")
    shutil.copyfile(HERE / "runtime_lib.py", run_dir / "ifrt.py")
    (run_dir / "analysis.py").write_text(source)
    result_path = run_dir / "result.json"
    if result_path.exists():
        result_path.unlink()

    use_netns = netns_available()
    if settings.sandbox_require_netns and not use_netns:
        return ExecResult(ok=False, error="Network isolation is required (SANDBOX_REQUIRE_NETNS=1) but unavailable on this host.")
    cmd = [sys.executable, "-I", str(HERE / "bootstrap.py"), str(run_dir), "analysis.py"]
    if use_netns:
        cmd = ["unshare", "-rn"] + cmd
    env = {
        "PATH": "/usr/bin:/bin", "HOME": str(run_dir), "TMPDIR": str(run_dir), "LANG": "C.UTF-8",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0",
    }
    t0 = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    try:
        proc = subprocess.run(cmd, cwd=run_dir, env=env, capture_output=True, text=True, timeout=timeout_s,
                              preexec_fn=_limits(settings.sandbox_memory_mb, timeout_s))
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        rc, out, err = -9, (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""), \
            (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    duration_ms = int((time.perf_counter() - t0) * 1000)
    cpu = round((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime), 3)
    isolation = {"network_namespace": use_netns, "memory_mb": settings.sandbox_memory_mb, "timeout_s": timeout_s,
                 "audit_hook": True, "static_validation": True}
    out, err = out[-20000:], _scrub(err[-20000:], run_dir)
    if timed_out:
        return ExecResult(False, stdout=out, stderr=err, error=f"Execution exceeded the {timeout_s}s time limit.",
                          duration_ms=duration_ms, cpu_s=cpu, isolation=isolation, timed_out=True)
    if rc != 0:
        last = [ln for ln in err.strip().splitlines() if ln.strip()]
        msg = last[-1] if last else f"process exited with code {rc}"
        if rc in (-9, 137) or "MemoryError" in err:
            msg = f"Execution was stopped by a resource limit ({msg})."
        return ExecResult(False, stdout=out, stderr=err, error=msg, duration_ms=duration_ms, cpu_s=cpu, isolation=isolation)
    if not result_path.exists():
        return ExecResult(False, stdout=out, stderr=err, error="Script finished without writing results.", duration_ms=duration_ms, cpu_s=cpu, isolation=isolation)
    try:
        result = json.loads(result_path.read_text())
    except json.JSONDecodeError as exc:
        return ExecResult(False, stdout=out, stderr=err, error=f"Result file was not valid JSON: {exc}", duration_ms=duration_ms, cpu_s=cpu, isolation=isolation)
    return ExecResult(True, result=result, stdout=out, stderr=err, duration_ms=duration_ms, cpu_s=cpu, isolation=isolation)


def _scrub(text: str, run_dir: Path) -> str:
    """Remove absolute host paths from tracebacks before they are stored or shown."""
    return text.replace(str(run_dir), "<run>").replace(str(HERE), "<sandbox>")
