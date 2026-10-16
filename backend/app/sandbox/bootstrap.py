"""Sandbox bootstrap. Executed as: python -I bootstrap.py <workdir> <script>

Defence in depth on top of the OS-level limits applied by the parent process
(rlimits, timeout, scrubbed environment, and a network namespace when
available): a Python audit hook denies sockets, subprocesses, and file access
outside the run directory and the Python installation.
"""
import os
import sys

WORKDIR = os.path.realpath(sys.argv[1])
SCRIPT = sys.argv[2]

_read_prefixes = [WORKDIR, "/usr", "/lib", "/lib64", "/proc/self", "/proc/cpuinfo", "/proc/meminfo", "/sys/devices/system/cpu",
                  "/sys/fs/cgroup", "/dev/null", "/dev/urandom", "/etc/localtime", "/opt/conda", sys.prefix, sys.base_prefix,
                  sys.exec_prefix]
_read_prefixes += [os.path.realpath(p) for p in sys.path if p]
_read_prefixes = tuple(sorted({os.path.realpath(p) for p in _read_prefixes if p}))

_BLOCKED_EVENTS = {
    "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto", "socket.__new__",
    "subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "os.exec", "os.fork", "os.forkpty",
    "os.kill", "os.killpg", "pty.spawn", "webbrowser.open", "urllib.Request", "http.client.connect",
    "os.chmod", "os.chown", "os.symlink", "os.link", "os.rmdir", "shutil.rmtree",
}


def _inside(path, prefixes):
    try:
        rp = os.path.realpath(path)
    except Exception:
        return False
    return any(rp == p or rp.startswith(p.rstrip("/") + "/") for p in prefixes)


def _hook(event, args):
    if event in _BLOCKED_EVENTS:
        raise PermissionError(f"sandbox: '{event}' is not permitted")
    if event == "open":
        path, mode = args[0], args[1]
        if isinstance(path, int) or path is None:
            return
        path = os.fsdecode(path)
        writing = isinstance(mode, str) and any(m in mode for m in "wax+")
        if isinstance(mode, int):
            writing = bool(mode & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
        if writing and not _inside(path, (WORKDIR,)):
            raise PermissionError(f"sandbox: writing outside the run directory is not permitted ({path})")
        if not writing and not _inside(path, _read_prefixes):
            raise PermissionError(f"sandbox: reading '{path}' is not permitted")
    elif event in ("os.remove", "os.rename", "os.replace", "os.mkdir"):
        for p in args[:2]:
            if isinstance(p, (str, bytes)) and not _inside(os.fsdecode(p), (WORKDIR,)):
                raise PermissionError(f"sandbox: '{event}' outside the run directory is not permitted")


os.chdir(WORKDIR)
sys.path.insert(0, WORKDIR)
# Import heavy libraries before the hook so their own initialisation (which may
# legitimately inspect the system) is not affected; user code runs after.
import numpy  # noqa: E402,F401
import pandas  # noqa: E402,F401

sys.addaudithook(_hook)

with open(SCRIPT, "r") as fh:
    source = fh.read()
code = compile(source, SCRIPT, "exec")
exec(code, {"__name__": "__main__", "__file__": SCRIPT})
