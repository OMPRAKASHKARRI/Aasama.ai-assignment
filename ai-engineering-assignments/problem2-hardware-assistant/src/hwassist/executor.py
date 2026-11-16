"""The ONLY place where this program touches the operating system.

Safety model
------------
* Commands are looked up by *key* in a fixed allow-list. Their argv is hard-coded here; neither the LLM nor
  the user can supply a command name, flag or argument.
* ``subprocess.run(..., shell=False)`` with an argv list, a per-command timeout, a sanitised environment
  (fixed PATH, ``LC_ALL=C``) and a cap on captured output.
* The binary is resolved from a fixed set of system directories, never from the caller's PATH.
* ``/proc`` and ``/sys`` files can be read only if they match an explicit allow-list of exact paths or
  strict regexes (no ``..``, no symlink escapes: the resolved path must still be under /proc or /sys).
* Serial numbers / UUIDs / MACs are never requested.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum

SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
MAX_OUTPUT_BYTES = 1_000_000
MAX_FILE_BYTES = 64 * 1024


class ErrorKind(str, Enum):
    NOT_ALLOWED = "not_allowed"
    NOT_INSTALLED = "not_installed"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    OUTPUT_TOO_LARGE = "output_too_large"


@dataclass(frozen=True)
class AllowedCommand:
    key: str
    argv: tuple[str, ...]          # argv[0] is a bare binary name resolved against SAFE_PATH
    description: str
    timeout: float = 5.0


@dataclass
class CommandResult:
    source: str                    # what was run, for provenance ("lscpu --json")
    ok: bool
    stdout: str = ""
    error_kind: ErrorKind | None = None
    message: str = ""

    @property
    def error(self) -> dict | None:
        if self.ok:
            return None
        return {"source": self.source, "kind": self.error_kind.value if self.error_kind else "failed",
                "message": self.message}


ALLOWED_COMMANDS: dict[str, AllowedCommand] = {c.key: c for c in (
    AllowedCommand("lscpu", ("lscpu", "--json"), "CPU topology and model"),
    AllowedCommand("lsblk", ("lsblk", "--json", "--bytes", "--output",
                             "NAME,TYPE,SIZE,ROTA,MODEL,TRAN,FSTYPE,MOUNTPOINTS,RM,RO,PKNAME"),
                   "Block devices"),
    AllowedCommand("free", ("free", "--bytes"), "Memory and swap usage"),
    AllowedCommand("lspci", ("lspci", "-vmm", "-nn", "-k"), "PCI devices (machine readable)"),
    AllowedCommand("dmidecode_baseboard", ("dmidecode", "-t", "baseboard"), "Motherboard (needs root)"),
    AllowedCommand("dmidecode_bios", ("dmidecode", "-t", "bios"), "BIOS/UEFI (needs root)"),
    AllowedCommand("dmidecode_system", ("dmidecode", "-t", "system"), "System vendor/product (needs root)"),
    AllowedCommand("dmidecode_memory", ("dmidecode", "-t", "memory"), "RAM modules (needs root)"),
    AllowedCommand("nvidia_smi", ("nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                                  "--format=csv,noheader,nounits"), "NVIDIA GPU memory/driver"),
)}

_PERMISSION_HINTS = ("permission denied", "must be root", "operation not permitted", "can't read memory",
                     "access denied", "not permitted")


def _classify_failure(stderr: str) -> ErrorKind:
    low = stderr.lower()
    return ErrorKind.PERMISSION_DENIED if any(h in low for h in _PERMISSION_HINTS) else ErrorKind.FAILED


def run_allowed(key: str, timeout: float | None = None) -> CommandResult:
    """Run an allow-listed command by key. Never raises; failures come back as a typed CommandResult."""
    spec = ALLOWED_COMMANDS.get(key)
    if spec is None:
        return CommandResult(key, False, error_kind=ErrorKind.NOT_ALLOWED,
                             message=f"command key {key!r} is not in the allow-list")
    source = " ".join(spec.argv)
    binary = shutil.which(spec.argv[0], path=SAFE_PATH)
    if binary is None:
        return CommandResult(source, False, error_kind=ErrorKind.NOT_INSTALLED,
                             message=f"{spec.argv[0]} is not installed on this system")
    try:
        proc = subprocess.run(
            [binary, *spec.argv[1:]], shell=False, capture_output=True, text=True, errors="replace",
            timeout=timeout or spec.timeout, env={"PATH": SAFE_PATH, "LC_ALL": "C", "LANG": "C"}, stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(source, False, error_kind=ErrorKind.TIMEOUT,
                             message=f"timed out after {timeout or spec.timeout:.0f}s")
    except PermissionError as exc:
        return CommandResult(source, False, error_kind=ErrorKind.PERMISSION_DENIED, message=str(exc))
    except FileNotFoundError:
        return CommandResult(source, False, error_kind=ErrorKind.NOT_INSTALLED, message=f"{spec.argv[0]} not found")
    except OSError as exc:
        return CommandResult(source, False, error_kind=ErrorKind.FAILED, message=f"{type(exc).__name__}: {exc}")

    if len(proc.stdout.encode()) > MAX_OUTPUT_BYTES:
        return CommandResult(source, False, error_kind=ErrorKind.OUTPUT_TOO_LARGE, message="output exceeded limit")
    # dmidecode/lspci print diagnostics on stderr and may still exit 0 with unusable output
    if proc.returncode != 0 or (key.startswith("dmidecode") and "Permission denied" in proc.stderr):
        msg = (proc.stderr.strip() or proc.stdout.strip() or f"exit status {proc.returncode}")[:300]
        return CommandResult(source, False, error_kind=_classify_failure(proc.stderr + proc.stdout), message=msg)
    return CommandResult(source, True, stdout=proc.stdout)


# ------------------------------------------------------------------ /proc and /sys

_ALLOWED_FILES = frozenset({
    "/proc/cpuinfo", "/proc/meminfo", "/proc/swaps",
    "/sys/class/dmi/id/board_vendor", "/sys/class/dmi/id/board_name", "/sys/class/dmi/id/board_version",
    "/sys/class/dmi/id/bios_vendor", "/sys/class/dmi/id/bios_version", "/sys/class/dmi/id/bios_date",
    "/sys/class/dmi/id/sys_vendor", "/sys/class/dmi/id/product_name", "/sys/class/dmi/id/product_version",
    "/sys/class/dmi/id/chassis_type",
    "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq",
})
_ALLOWED_PATTERNS = tuple(re.compile(p) for p in (
    r"^/sys/block/[a-z0-9]+/size$",
    r"^/sys/block/[a-z0-9]+/queue/rotational$",
    r"^/sys/block/[a-z0-9]+/device/model$",
    r"^/sys/class/drm/card[0-9]+/device/(vendor|device)$",
))
_ALLOWED_DIRS = frozenset({"/sys/block", "/sys/class/drm"})


def _path_allowed(path: str) -> bool:
    if ".." in path.split("/") or "\x00" in path:
        return False
    if path in _ALLOWED_FILES or any(p.match(path) for p in _ALLOWED_PATTERNS):
        resolved = os.path.realpath(path)
        return resolved.startswith(("/proc/", "/sys/"))
    return False


@dataclass
class FileResult:
    source: str
    ok: bool
    text: str = ""
    error_kind: ErrorKind | None = None
    message: str = ""

    @property
    def error(self) -> dict | None:
        if self.ok:
            return None
        return {"source": self.source, "kind": self.error_kind.value if self.error_kind else "failed",
                "message": self.message}


def read_allowed_file(path: str) -> FileResult:
    if not _path_allowed(path):
        return FileResult(path, False, error_kind=ErrorKind.NOT_ALLOWED, message="path is not in the allow-list")
    try:
        with open(path, "rb") as fh:
            return FileResult(path, True, text=fh.read(MAX_FILE_BYTES).decode(errors="replace").strip())
    except FileNotFoundError:
        return FileResult(path, False, error_kind=ErrorKind.NOT_FOUND, message="file does not exist on this system")
    except PermissionError:
        return FileResult(path, False, error_kind=ErrorKind.PERMISSION_DENIED, message="permission denied")
    except OSError as exc:
        return FileResult(path, False, error_kind=ErrorKind.FAILED, message=f"{type(exc).__name__}: {exc}")


def list_allowed_dir(path: str) -> list[str]:
    """List entry names of /sys/block or /sys/class/drm only (used to enumerate disks / GPUs)."""
    if path not in _ALLOWED_DIRS:
        return []
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


