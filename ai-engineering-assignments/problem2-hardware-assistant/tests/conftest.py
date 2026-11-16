"""Helpers to simulate a machine by replacing the executor's three primitives (never to fake parsing)."""
import pytest

from hwassist import executor as ex
from tests import fixtures as fx


def ok(source, stdout):
    return ex.CommandResult(source, True, stdout=stdout)


def fail(source, kind, message="x"):
    return ex.CommandResult(source, False, error_kind=kind, message=message)


class FakeSystem:
    """Programmable stand-in for executor.run_allowed/read_allowed_file/list_allowed_dir."""

    def __init__(self):
        self.commands: dict[str, ex.CommandResult] = {}
        self.files: dict[str, str] = {}
        self.dirs: dict[str, list[str]] = {}
        self.calls: list[str] = []

    def run_allowed(self, key, timeout=None):
        self.calls.append(key)
        return self.commands.get(key) or fail(key, ex.ErrorKind.NOT_INSTALLED, f"{key} is not installed on this system")

    def read_allowed_file(self, path):
        self.calls.append(path)
        if path in self.files:
            return ex.FileResult(path, True, text=self.files[path])
        return ex.FileResult(path, False, error_kind=ex.ErrorKind.NOT_FOUND, message="file does not exist on this system")

    def list_allowed_dir(self, path):
        return self.dirs.get(path, [])


@pytest.fixture()
def system(monkeypatch):
    fs = FakeSystem()
    monkeypatch.setattr(ex, "run_allowed", fs.run_allowed)
    monkeypatch.setattr(ex, "read_allowed_file", fs.read_allowed_file)
    monkeypatch.setattr(ex, "list_allowed_dir", fs.list_allowed_dir)
    return fs


@pytest.fixture()
def laptop(system):
    """A fully-populated laptop (root available)."""
    c = system.commands
    c["lscpu"] = ok("lscpu --json", fx.LSCPU_JSON)
    c["free"] = ok("free --bytes", fx.FREE_B)
    c["lsblk"] = ok("lsblk", fx.LSBLK_JSON)
    c["lspci"] = ok("lspci", fx.LSPCI)
    c["nvidia_smi"] = ok("nvidia-smi", fx.NVIDIA_SMI)
    c["dmidecode_baseboard"] = ok("dmidecode -t baseboard", fx.DMI_BASEBOARD)
    c["dmidecode_bios"] = ok("dmidecode -t bios", fx.DMI_BIOS)
    c["dmidecode_system"] = ok("dmidecode -t system", fx.DMI_SYSTEM)
    c["dmidecode_memory"] = ok("dmidecode -t memory", fx.DMI_MEMORY)
    return system
