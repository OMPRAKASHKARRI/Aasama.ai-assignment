import subprocess

import pytest

from hwassist import executor as ex
from hwassist.executor import ErrorKind, read_allowed_file, run_allowed


def test_runs_allowed_command_for_real():
    r = run_allowed("lscpu")
    assert r.ok and "Architecture" in r.stdout


@pytest.mark.parametrize("key", ["lscpu; rm -rf /", "rm", "bash -c id", "../../bin/sh", "", "LSCPU", "lscpu --version"])
def test_rejects_anything_not_in_allow_list(key, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("subprocess must not be invoked for non-allow-listed keys")
    monkeypatch.setattr(subprocess, "run", boom)
    r = run_allowed(key)
    assert not r.ok and r.error_kind == ErrorKind.NOT_ALLOWED


def test_always_uses_shell_false_list_argv_timeout_and_clean_env(monkeypatch):
    seen = {}
    def fake(argv, **kw):
        seen.update(argv=argv, **kw)
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    assert run_allowed("free").ok
    assert seen["shell"] is False and isinstance(seen["argv"], list) and seen["timeout"] > 0
    assert seen["argv"][0].endswith("/free") and seen["argv"][1:] == ["--bytes"]
    assert set(seen["env"]) == {"PATH", "LC_ALL", "LANG"} and seen["env"]["LC_ALL"] == "C"
    assert seen["stdin"] == subprocess.DEVNULL


def test_all_allowlisted_commands_are_fixed_argv_without_shell_metacharacters():
    for spec in ex.ALLOWED_COMMANDS.values():
        assert isinstance(spec.argv, tuple) and spec.timeout <= 10
        assert not any(ch in part for part in spec.argv for ch in ";|&$`><\n")


def test_timeout(monkeypatch):
    monkeypatch.setitem(ex.ALLOWED_COMMANDS, "slow", ex.AllowedCommand("slow", ("sleep", "5"), "t", timeout=0.3))
    r = run_allowed("slow")
    assert not r.ok and r.error_kind == ErrorKind.TIMEOUT and "timed out" in r.message


def test_missing_command(monkeypatch):
    monkeypatch.setitem(ex.ALLOWED_COMMANDS, "ghost", ex.AllowedCommand("ghost", ("definitely-not-installed-xyz",), "t"))
    r = run_allowed("ghost")
    assert r.error_kind == ErrorKind.NOT_INSTALLED and "not installed" in r.message


def test_permission_error_on_exec(monkeypatch):
    def deny(*a, **k):
        raise PermissionError("denied")
    monkeypatch.setattr(subprocess, "run", deny)
    assert run_allowed("free").error_kind == ErrorKind.PERMISSION_DENIED


def test_nonzero_exit_with_permission_text_is_classified(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "dmidecode: /dev/mem: Permission denied"))
    r = run_allowed("dmidecode_memory")
    assert r.error_kind == ErrorKind.PERMISSION_DENIED and r.error["kind"] == "permission_denied"


def test_dmidecode_exit0_with_permission_error_is_not_treated_as_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "# dmidecode 3.5\n", "/dev/mem: Permission denied"))
    assert not run_allowed("dmidecode_baseboard").ok


def test_output_cap(monkeypatch):
    monkeypatch.setattr(ex, "MAX_OUTPUT_BYTES", 10)
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "x" * 100, ""))
    assert run_allowed("free").error_kind == ErrorKind.OUTPUT_TOO_LARGE


class TestFileAllowList:
    def test_reads_real_proc_file(self):
        r = read_allowed_file("/proc/meminfo")
        assert r.ok and "MemTotal" in r.text

    @pytest.mark.parametrize("path", [
        "/etc/passwd", "/etc/shadow", "/proc/self/environ", "/proc/1/cmdline", "/sys/class/dmi/id/product_serial",
        "/sys/class/dmi/id/product_uuid", "/proc/../etc/passwd", "/sys/block/../../etc/passwd",
        "/sys/block/sda/../../../etc/shadow", "/home/user/.ssh/id_rsa", "", "/proc/cpuinfo\x00.txt",
    ])
    def test_rejects_non_allowlisted_paths(self, path):
        r = read_allowed_file(path)
        assert not r.ok and r.error_kind == ErrorKind.NOT_ALLOWED

    def test_missing_allowed_file_is_not_found(self):
        r = read_allowed_file("/sys/block/zzzdoesnotexist/size")
        assert r.error_kind == ErrorKind.NOT_FOUND

    def test_symlink_escape_blocked(self, monkeypatch):
        monkeypatch.setattr(ex.os.path, "realpath", lambda p: "/etc/passwd")
        assert read_allowed_file("/proc/cpuinfo").error_kind == ErrorKind.NOT_ALLOWED

    def test_permission_error(self, monkeypatch):
        def deny(*a, **k):
            raise PermissionError
        monkeypatch.setattr("builtins.open", deny)
        assert read_allowed_file("/proc/cpuinfo").error_kind == ErrorKind.PERMISSION_DENIED

    def test_dir_listing_is_restricted(self):
        assert ex.list_allowed_dir("/etc") == [] and ex.list_allowed_dir("/sys/block/../..") == []
