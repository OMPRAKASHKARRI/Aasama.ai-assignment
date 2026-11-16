"""Collectors: run allow-listed sources, parse them, fall back when one is unavailable, and report
honestly (sources used, every error, and notes about what could not be determined)."""
from __future__ import annotations

from collections.abc import Callable

from hwassist import executor as ex
from hwassist import parsers as p
from hwassist.models import (
    ComponentReport, CpuInfo, GpuDevice, GpuInfo, MemoryInfo, MotherboardInfo, StorageDevice, StorageInfo,
)

_PCI_VENDORS = {"0x10de": "NVIDIA Corporation", "0x1002": "Advanced Micro Devices, Inc. [AMD/ATI]",
                "0x8086": "Intel Corporation"}   # PCI-SIG vendor ids, used only by the /sys fallback


class _Trace:
    def __init__(self) -> None:
        self.sources: list[str] = []
        self.errors: list[dict] = []
        self.notes: list[str] = []

    def cmd(self, key: str) -> ex.CommandResult:
        r = ex.run_allowed(key)
        (self.sources if r.ok else self.errors).append(r.source if r.ok else r.error)  # type: ignore[arg-type]
        return r

    def file(self, path: str) -> ex.FileResult:
        r = ex.read_allowed_file(path)
        (self.sources if r.ok else self.errors).append(r.source if r.ok else r.error)  # type: ignore[arg-type]
        return r

    def _collapsed_errors(self) -> list[dict]:
        """Merge errors of the same kind so the LLM sees 'why' once instead of a dozen near-duplicates."""
        groups: dict[str, list[dict]] = {}
        for e in self.errors:
            groups.setdefault(e["kind"], []).append(e)
        out = []
        for kind, items in groups.items():
            if len(items) == 1:
                out.append(items[0])
            else:
                out.append({"kind": kind, "count": len(items), "message": items[0]["message"],
                            "sources": [i["source"] for i in items][:4]})
        return out

    def report(self, component: str, data: object | None, available: bool | None = None) -> ComponentReport:
        return ComponentReport(
            component=component, available=data is not None if available is None else available,
            data=data.model_dump(exclude_none=True) if data is not None else None,  # type: ignore[attr-defined]
            sources=self.sources, errors=self._collapsed_errors(), notes=self.notes,
        )


def _try(t: _Trace, parse: Callable[[str], object], text: str, source: str):
    try:
        return parse(text)
    except (ValueError, KeyError, TypeError) as exc:
        t.errors.append({"source": source, "kind": "parse_error", "message": str(exc)[:200]})
        return None


# ------------------------------------------------------------------ CPU

def collect_cpu() -> ComponentReport:
    t = _Trace()
    info: CpuInfo | None = None
    r = t.cmd("lscpu")
    if r.ok:
        info = _try(t, p.parse_lscpu_json, r.stdout, r.source)  # type: ignore[assignment]
    if info is None:
        f = t.file("/proc/cpuinfo")
        if f.ok:
            info = p.parse_proc_cpuinfo(f.text)
            t.notes.append("lscpu unavailable; limited data derived from /proc/cpuinfo (no cache/topology details).")
    if info is not None:
        if info.max_mhz is None:
            f = t.file("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
            if f.ok and f.text.isdigit():
                info.max_mhz = int(f.text) / 1000
        if info.max_mhz is None:
            t.notes.append("Maximum clock speed is not reported by this system (common inside virtual machines).")
        if info.hypervisor:
            t.notes.append(f"Running under a hypervisor ({info.hypervisor}); values describe the virtual CPU.")
    return t.report("cpu", info)


# ------------------------------------------------------------------ memory

def collect_memory(include_modules: bool = True) -> ComponentReport:
    t = _Trace()
    info: MemoryInfo | None = None
    r = t.cmd("free")
    if r.ok:
        info = _try(t, p.parse_free_bytes, r.stdout, r.source)  # type: ignore[assignment]
    if info is None:
        f = t.file("/proc/meminfo")
        if f.ok:
            info = _try(t, p.parse_meminfo, f.text, f.source)  # type: ignore[assignment]
    if info is not None and include_modules:
        d = t.cmd("dmidecode_memory")
        if d.ok:
            modules, extra = p.parse_dmi_memory(d.stdout)
            info.modules = modules
            info.slots_total, info.slots_populated = extra["slots_total"], extra["slots_populated"]
            info.max_capacity_bytes = extra["max_capacity_bytes"]
            if not modules:
                t.notes.append("dmidecode reported no populated memory modules.")
        else:
            t.notes.append("Physical module details (DDR generation, speed, slot count) are unavailable: "
                           "they require dmidecode with root privileges and SMBIOS data (absent in most VMs).")
    return t.report("memory", info)


# ------------------------------------------------------------------ storage

def _storage_from_sys(t: _Trace) -> list[StorageDevice]:
    devices = []
    for name in ex.list_allowed_dir("/sys/block"):
        if name.startswith(("loop", "ram", "zram", "dm-", "md")):
            continue
        size = t.file(f"/sys/block/{name}/size")
        if not size.ok or not size.text.isdigit() or int(size.text) == 0:
            continue
        rota = t.file(f"/sys/block/{name}/queue/rotational")
        model = t.file(f"/sys/block/{name}/device/model")
        rota_val = {"1": True, "0": False}.get(rota.text) if rota.ok else None
        devices.append(StorageDevice(name=name, size_bytes=int(size.text) * 512, model=p.clean(model.text) if model.ok else None,
                                     media_type=p._media_type(name, None, rota_val)))  # type: ignore[arg-type]
    return devices


def collect_storage(include_partitions: bool = False) -> ComponentReport:
    t = _Trace()
    devices: list[StorageDevice] | None = None
    r = t.cmd("lsblk")
    if r.ok:
        devices = _try(t, p.parse_lsblk_json, r.stdout, r.source)  # type: ignore[assignment]
    if devices is None:
        devices = _storage_from_sys(t) or None
        if devices:
            t.notes.append("lsblk unavailable; basic data derived from /sys/block (no partitions/filesystems).")
    if devices is None:
        return t.report("storage", None)
    if not include_partitions:
        for d in devices:
            d.partitions = []
    if any(d.media_type == "virtual" for d in devices):
        t.notes.append("Some disks are virtual (VM/virtio); their SSD/HDD type cannot be determined from the guest.")
    if any(d.model is None for d in devices):
        t.notes.append("Disk model is not reported for some devices.")
    total = sum(d.size_bytes or 0 for d in devices)
    return t.report("storage", StorageInfo(devices=devices, total_bytes=total))


# ------------------------------------------------------------------ GPU

def _gpus_from_drm(t: _Trace) -> list[GpuDevice]:
    gpus = []
    for entry in ex.list_allowed_dir("/sys/class/drm"):
        if not entry.startswith("card") or not entry[4:].isdigit():
            continue
        v = t.file(f"/sys/class/drm/{entry}/device/vendor")
        if v.ok:
            gpus.append(GpuDevice(slot=entry, vendor=_PCI_VENDORS.get(v.text.lower(), f"PCI vendor {v.text}")))
    return gpus


def collect_gpu() -> ComponentReport:
    t = _Trace()
    gpus: list[GpuDevice] | None = None
    r = t.cmd("lspci")
    if r.ok:
        gpus = _try(t, p.parse_lspci_gpus, r.stdout, r.source)  # type: ignore[assignment]
    if gpus is None:
        gpus = _gpus_from_drm(t) or None
        if gpus:
            t.notes.append("lspci unavailable; only the vendor could be read from /sys/class/drm (model unknown).")
    n = t.cmd("nvidia_smi")
    if n.ok:
        rows = p.parse_nvidia_smi_csv(n.stdout)
        gpus = gpus or []
        for name, vram, drv in rows:
            match = next((g for g in gpus if g.vendor and "NVIDIA" in g.vendor.upper() and g.vram_mib is None), None)
            if match is None:
                match = GpuDevice(vendor="NVIDIA Corporation")
                gpus.append(match)
            match.name, match.vram_mib, match.driver_version = name, vram, drv
    if gpus is None:
        return t.report("gpu", None)
    if not gpus:
        t.notes.append("No display/3D controller is reported by this system (normal in headless VMs and containers).")
    elif all(g.vram_mib is None for g in gpus):
        t.notes.append("Video memory (VRAM) size could not be determined for any GPU (nvidia-smi is NVIDIA-only).")
    return t.report("gpu", GpuInfo(devices=gpus))


# ------------------------------------------------------------------ motherboard

_SYSFS_DMI = {
    "board_vendor": "board_vendor", "board_name": "board_name", "board_version": "board_version",
    "bios_vendor": "bios_vendor", "bios_version": "bios_version", "bios_date": "bios_date",
    "system_vendor": "sys_vendor", "product_name": "product_name", "product_version": "product_version",
}


def collect_motherboard() -> ComponentReport:
    t = _Trace()
    values: dict[str, str | None] = {}
    for key, parser in (("dmidecode_baseboard", p.parse_dmi_baseboard), ("dmidecode_bios", p.parse_dmi_bios),
                        ("dmidecode_system", p.parse_dmi_system)):
        r = t.cmd(key)
        if r.ok:
            values.update(parser(r.stdout))
    # /sys/class/dmi/id is world-readable and fills gaps when dmidecode needs root
    for field, fname in _SYSFS_DMI.items():
        if values.get(field) is None:
            f = t.file(f"/sys/class/dmi/id/{fname}")
            if f.ok:
                values[field] = p.clean(f.text)
    info = MotherboardInfo(**values)
    if not info.model_dump(exclude_none=True):
        t.notes.append("No DMI/SMBIOS data is exposed (typical for VMs, containers and some ARM boards): "
                       "the motherboard model cannot be determined here.")
        return t.report("motherboard", None, available=False)
    if info.board_name is None:
        t.notes.append("Motherboard model is not reported; the fields above come from other DMI tables.")
    return t.report("motherboard", info)


COLLECTORS: dict[str, Callable[..., ComponentReport]] = {
    "cpu": collect_cpu, "memory": collect_memory, "storage": collect_storage,
    "gpu": collect_gpu, "motherboard": collect_motherboard,
}


def collect_all() -> dict[str, ComponentReport]:
    return {name: fn() for name, fn in COLLECTORS.items()}
