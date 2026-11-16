import os

from hwassist import collectors as co
from hwassist import executor as ex
from tests import fixtures as fx
from tests.conftest import fail, ok


def test_cpu_from_lscpu(laptop):
    r = co.collect_cpu()
    assert r.available and r.data["physical_cores"] == 4 and r.sources == ["lscpu --json"]
    assert r.errors == []


def test_cpu_falls_back_to_proc_cpuinfo_when_lscpu_missing(system):
    system.files["/proc/cpuinfo"] = fx.PROC_CPUINFO
    r = co.collect_cpu()
    assert r.available and r.data["model_name"].startswith("AMD Ryzen") and "physical_cores" not in r.data
    assert any(e["kind"] == "not_installed" for e in r.errors) and any("limited data" in n for n in r.notes)


def test_cpu_unparseable_lscpu_reported_and_fallback_used(system):
    system.commands["lscpu"] = ok("lscpu --json", "{{{{")
    system.files["/proc/cpuinfo"] = fx.PROC_CPUINFO
    r = co.collect_cpu()
    assert r.available and any(e["kind"] == "parse_error" for e in r.errors)


def test_cpu_nothing_available(system):
    r = co.collect_cpu()
    assert not r.available and r.data is None and r.errors


def test_memory_full_with_modules(laptop):
    r = co.collect_memory()
    d = r.data
    assert d["total_human"] == "15.5 GiB" and len(d["modules"]) == 2 and d["slots_total"] == 4
    assert d["modules"][0]["type"] == "DDR4" and d["max_capacity_bytes"] == 64 * 1024**3


def test_memory_without_root_keeps_totals_and_explains_missing_modules(system):
    system.commands["free"] = ok("free", fx.FREE_B)
    system.commands["dmidecode_memory"] = fail("dmidecode -t memory", ex.ErrorKind.PERMISSION_DENIED, "denied")
    r = co.collect_memory()
    assert r.available and r.data["modules"] == [] and "slots_total" not in r.data
    assert any(e["kind"] == "permission_denied" for e in r.errors)
    assert any("require dmidecode with root" in n for n in r.notes)


def test_memory_fallback_to_meminfo(system):
    system.files["/proc/meminfo"] = fx.MEMINFO
    assert co.collect_memory(include_modules=False).data["total_bytes"] == 16222272 * 1024


def test_memory_modules_skipped_on_request(laptop):
    co.collect_memory(include_modules=False)
    assert "dmidecode_memory" not in laptop.calls


def test_storage_partitions_toggle_and_total(laptop):
    without = co.collect_storage().data
    assert all(d["partitions"] == [] for d in without["devices"])
    with_parts = co.collect_storage(include_partitions=True).data
    assert len(with_parts["devices"][0]["partitions"]) == 2
    assert with_parts["total_bytes"] == 512110190592 + 1000204886016


def test_storage_falls_back_to_sys_block(system):
    system.dirs["/sys/block"] = ["loop0", "nvme0n1", "zram0"]
    system.files.update({"/sys/block/nvme0n1/size": "1000215216", "/sys/block/nvme0n1/queue/rotational": "0",
                         "/sys/block/nvme0n1/device/model": "KINGSTON SNVS1000G"})
    r = co.collect_storage()
    d = r.data["devices"][0]
    assert d["name"] == "nvme0n1" and d["size_bytes"] == 1000215216 * 512 and d["media_type"] == "nvme"
    assert d["model"] == "KINGSTON SNVS1000G" and any("lsblk unavailable" in n for n in r.notes)


def test_storage_nothing_available(system):
    assert not co.collect_storage().available


def test_gpu_merges_lspci_and_nvidia_smi(laptop):
    gpus = co.collect_gpu().data["devices"]
    assert len(gpus) == 2
    nv = next(g for g in gpus if "NVIDIA" in g["vendor"])
    assert nv["vram_mib"] == 4096 and nv["driver_version"] == "535.154.05" and nv["name"] == "NVIDIA GeForce RTX 3050 Laptop GPU"
    assert "vram_mib" not in next(g for g in gpus if "Intel" in g["vendor"])


def test_gpu_none_found_is_reported_not_an_error(system):
    system.commands["lspci"] = ok("lspci", "Slot:\t00:00.0\nClass:\tHost bridge [0600]\nVendor:\tIntel [8086]\nDevice:\tDevice [1]\n")
    r = co.collect_gpu()
    assert r.available and r.data["devices"] == [] and any("No display/3D controller" in n for n in r.notes)


def test_gpu_unknown_model_is_not_invented_and_vram_note(system):
    system.commands["lspci"] = ok("lspci", fx.LSPCI_UNKNOWN_GPU)
    r = co.collect_gpu()
    assert "name" not in r.data["devices"][0] and any("VRAM" in n for n in r.notes)


def test_gpu_sysfs_fallback_reports_vendor_only(system):
    system.dirs["/sys/class/drm"] = ["card0", "card0-HDMI-A-1", "version"]
    system.files["/sys/class/drm/card0/device/vendor"] = "0x10de"
    r = co.collect_gpu()
    assert r.data["devices"] == [{"slot": "card0", "vendor": "NVIDIA Corporation"}]
    assert any("model unknown" in n for n in r.notes)


def test_motherboard_from_dmidecode(laptop):
    d = co.collect_motherboard().data
    assert d["board_vendor"] == "LENOVO" and d["bios_version"] == "N32ET85W (1.60 )" and d["product_version"] == "ThinkPad X1 Carbon Gen 9"


def test_motherboard_non_root_uses_sysfs_dmi(system):
    for k in ("dmidecode_baseboard", "dmidecode_bios", "dmidecode_system"):
        system.commands[k] = fail(k, ex.ErrorKind.PERMISSION_DENIED, "denied")
    system.files.update({"/sys/class/dmi/id/board_vendor": "ASUSTeK COMPUTER INC.", "/sys/class/dmi/id/board_name": "ROG STRIX B550-F",
                         "/sys/class/dmi/id/bios_version": "2803"})
    r = co.collect_motherboard()
    assert r.available and r.data["board_name"] == "ROG STRIX B550-F" and r.data["bios_version"] == "2803"
    assert any(e["kind"] == "permission_denied" for e in r.errors)


def test_motherboard_unavailable_in_vm_says_so(system):
    for k in ("dmidecode_baseboard", "dmidecode_bios", "dmidecode_system"):
        system.commands[k] = fail(k, ex.ErrorKind.PERMISSION_DENIED, "denied")
    r = co.collect_motherboard()
    assert not r.available and r.data is None and any("cannot be determined" in n for n in r.notes)


def test_errors_of_same_kind_are_collapsed(system):
    r = co.collect_motherboard()
    kinds = [e["kind"] for e in r.errors]
    assert len(kinds) == len(set(kinds))


def test_placeholder_board_values_treated_as_unknown(system):
    system.commands["dmidecode_baseboard"] = ok("x", "Handle 0x2, DMI type 2, 15 bytes\nBase Board Information\n\tManufacturer: Default string\n\tProduct Name: To Be Filled By O.E.M.\n")
    assert not co.collect_motherboard().available


# ----- the real machine this test-suite runs on: values must match the kernel's own numbers -----
def test_real_memory_total_matches_proc_meminfo():
    r = co.collect_memory(include_modules=False)
    kernel = next(int(l.split()[1]) * 1024 for l in open("/proc/meminfo") if l.startswith("MemTotal"))
    assert r.available and r.data["total_bytes"] == kernel


def test_real_cpu_count_matches_proc_cpuinfo():
    r = co.collect_cpu()
    procs = sum(1 for l in open("/proc/cpuinfo") if l.startswith("processor"))
    assert r.available and r.data["logical_cpus"] == procs


def test_real_storage_sizes_match_sysfs():
    r = co.collect_storage()
    if not r.available or not r.data["devices"]:
        return
    for d in r.data["devices"]:
        path = f"/sys/block/{d['name']}/size"
        if os.path.exists(path):
            assert d["size_bytes"] == int(open(path).read()) * 512
