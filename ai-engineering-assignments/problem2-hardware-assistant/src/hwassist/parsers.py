"""Pure parsers: text/JSON in, typed models out. No I/O here, so they are trivially testable.

Privacy: serial numbers, UUIDs, asset tags and MAC addresses are never extracted, and any that appear
inside free-text fields are masked by :func:`clean`.
"""
from __future__ import annotations

import json
import re

from hwassist.models import (
    CpuInfo, GpuDevice, MemoryInfo, MemoryModule, Partition, StorageDevice,
)

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_MAC = re.compile(r"\b[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}\b")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_JUNK = {"", "unknown", "not specified", "to be filled by o.e.m.", "default string", "none", "n/a",
         "system manufacturer", "system product name", "not available", "o.e.m."}


def clean(value: object, max_len: int = 200) -> str | None:
    """Sanitise a hardware string: strip control chars (prompt-injection hygiene), mask MAC/UUID, cap length.
    Returns None for empty/placeholder values so they are reported as unknown rather than as data."""
    if value is None:
        return None
    s = _CTRL.sub("", str(value)).strip()
    if s.lower() in _JUNK:
        return None
    s = _UUID.sub("[redacted]", _MAC.sub("[redacted]", s))
    return s[:max_len]


def _int(value: object) -> int | None:
    try:
        return int(str(value).strip().split()[0])
    except (ValueError, IndexError):
        return None


def _float(value: object) -> float | None:
    try:
        return float(str(value).strip().split()[0])
    except (ValueError, IndexError):
        return None


# ------------------------------------------------------------------ lscpu / cpuinfo

def _flatten_lscpu(entries: list[dict], out: dict[str, str] | None = None) -> dict[str, str]:
    out = {} if out is None else out
    for e in entries:
        out[str(e.get("field", "")).rstrip(":").strip()] = str(e.get("data", "")).strip()
        _flatten_lscpu(e.get("children") or [], out)
    return out


def parse_lscpu_json(text: str) -> CpuInfo:
    try:
        fields = _flatten_lscpu(json.loads(text)["lscpu"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"unparseable lscpu output: {exc}") from exc
    return CpuInfo(
        model_name=clean(fields.get("Model name")), vendor=clean(fields.get("Vendor ID")),
        architecture=clean(fields.get("Architecture")), logical_cpus=_int(fields.get("CPU(s)")),
        sockets=_int(fields.get("Socket(s)")), cores_per_socket=_int(fields.get("Core(s) per socket")),
        threads_per_core=_int(fields.get("Thread(s) per core")),
        max_mhz=_float(fields.get("CPU max MHz")), min_mhz=_float(fields.get("CPU min MHz")),
        cache_l1d=clean(fields.get("L1d cache")), cache_l1i=clean(fields.get("L1i cache")),
        cache_l2=clean(fields.get("L2 cache")), cache_l3=clean(fields.get("L3 cache")),
        virtualization=clean(fields.get("Virtualization")), hypervisor=clean(fields.get("Hypervisor vendor")),
    )


def parse_proc_cpuinfo(text: str) -> CpuInfo:
    """Fallback when lscpu is unavailable: derive what /proc/cpuinfo can actually tell us."""
    model = vendor = None
    logical = 0
    mhz: list[float] = []
    for line in text.splitlines():
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if key == "processor":
            logical += 1
        elif key in ("model name", "Model", "cpu model") and model is None:
            model = clean(val)
        elif key == "vendor_id" and vendor is None:
            vendor = clean(val)
        elif key == "cpu MHz":
            f = _float(val)
            if f is not None:
                mhz.append(f)
    return CpuInfo(model_name=model, vendor=vendor, logical_cpus=logical or None,
                   max_mhz=max(mhz) if mhz else None)


# ------------------------------------------------------------------ memory

def parse_free_bytes(text: str) -> MemoryInfo:
    info = MemoryInfo()
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "Mem:" and len(parts) >= 7:
            info.total_bytes, info.used_bytes, info.available_bytes = int(parts[1]), int(parts[2]), int(parts[6])
        elif parts and parts[0] == "Swap:" and len(parts) >= 3:
            info.swap_total_bytes, info.swap_used_bytes = int(parts[1]), int(parts[2])
    if info.total_bytes is None:
        raise ValueError("no Mem: line in free output")
    return info


def parse_meminfo(text: str) -> MemoryInfo:
    kv: dict[str, int] = {}
    for line in text.splitlines():
        key, _, val = line.partition(":")
        n = _int(val)
        if n is not None:
            kv[key.strip()] = n * 1024 if val.strip().endswith("kB") else n
    if "MemTotal" not in kv:
        raise ValueError("MemTotal missing from /proc/meminfo")
    avail = kv.get("MemAvailable")
    return MemoryInfo(
        total_bytes=kv["MemTotal"], available_bytes=avail,
        used_bytes=kv["MemTotal"] - avail if avail is not None else None,
        swap_total_bytes=kv.get("SwapTotal"),
        swap_used_bytes=kv["SwapTotal"] - kv["SwapFree"] if "SwapTotal" in kv and "SwapFree" in kv else None,
    )


# ------------------------------------------------------------------ dmidecode

def parse_dmidecode(text: str) -> list[tuple[str, dict[str, str]]]:
    """Return [(section_title, {key: value})]. Multi-line values (lists) are ignored; only 'Key: Value'."""
    sections: list[tuple[str, dict[str, str]]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        handle = next((i for i, ln in enumerate(lines) if ln.startswith("Handle ")), None)
        if handle is None or handle + 1 >= len(lines):
            continue
        title, fields = lines[handle + 1].strip(), {}
        for ln in lines[handle + 2:]:
            if ln.startswith("\t") and ":" in ln and not ln.startswith("\t\t"):
                k, _, v = ln.strip().partition(":")
                fields[k.strip()] = v.strip()
        sections.append((title, fields))
    return sections


def _section(sections: list[tuple[str, dict[str, str]]], title: str) -> dict[str, str]:
    return next((f for t, f in sections if t == title), {})


def parse_dmi_baseboard(text: str) -> dict[str, str | None]:
    f = _section(parse_dmidecode(text), "Base Board Information")
    return {"board_vendor": clean(f.get("Manufacturer")), "board_name": clean(f.get("Product Name")),
            "board_version": clean(f.get("Version"))}


def parse_dmi_bios(text: str) -> dict[str, str | None]:
    f = _section(parse_dmidecode(text), "BIOS Information")
    return {"bios_vendor": clean(f.get("Vendor")), "bios_version": clean(f.get("Version")),
            "bios_date": clean(f.get("Release Date"))}


def parse_dmi_system(text: str) -> dict[str, str | None]:
    f = _section(parse_dmidecode(text), "System Information")
    return {"system_vendor": clean(f.get("Manufacturer")), "product_name": clean(f.get("Product Name")),
            "product_version": clean(f.get("Version"))}


_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}


def _dmi_size(value: str | None) -> int | None:
    m = re.match(r"^(\d+)\s*(B|KB|MB|GB|TB)$", (value or "").strip())
    return int(m.group(1)) * _UNITS[m.group(2)] if m else None


def parse_dmi_memory(text: str) -> tuple[list[MemoryModule], dict]:
    sections = parse_dmidecode(text)
    modules: list[MemoryModule] = []
    empty_slots = 0
    for title, f in sections:
        if title != "Memory Device":
            continue
        size = _dmi_size(f.get("Size"))
        if size is None:
            empty_slots += 1
            continue
        speed = _int(f.get("Configured Memory Speed") or f.get("Speed"))
        modules.append(MemoryModule(
            locator=clean(f.get("Locator")), size_bytes=size, type=clean(f.get("Type")), speed_mt_s=speed,
            form_factor=clean(f.get("Form Factor")), manufacturer=clean(f.get("Manufacturer")),
            part_number=clean(f.get("Part Number")),
        ))
    array = _section(sections, "Physical Memory Array")
    extra = {"slots_total": _int(array.get("Number Of Devices")), "max_capacity_bytes": _dmi_size(array.get("Maximum Capacity")),
             "slots_populated": len(modules), "empty_slots": empty_slots}
    return modules, extra


# ------------------------------------------------------------------ lsblk

_VIRTUAL_PREFIXES = ("zram", "ram", "loop", "vd", "xvd", "fd")


def _media_type(name: str, tran: str | None, rota: bool | None) -> str:
    if tran == "virtio" or name.startswith(_VIRTUAL_PREFIXES):
        return "virtual"          # the rotational flag is meaningless for virtual disks
    if name.startswith("nvme") or tran == "nvme":
        return "nvme"
    if rota is True:
        return "hdd"
    if rota is False:
        return "ssd"
    return "unknown"


def parse_lsblk_json(text: str, include_virtual_pseudo: bool = False) -> list[StorageDevice]:
    try:
        nodes = json.loads(text)["blockdevices"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"unparseable lsblk output: {exc}") from exc
    devices: list[StorageDevice] = []
    for n in nodes:
        name = str(n.get("name", ""))
        if n.get("type") != "disk":
            continue
        if not include_virtual_pseudo and (name.startswith(("zram", "ram", "loop")) or not n.get("size")):
            continue                     # swap-in-RAM / loop / zero-size pseudo devices are not storage hardware
        parts = [
            Partition(name=str(p.get("name")), size_bytes=_int(p.get("size")), fstype=clean(p.get("fstype")),
                      mountpoints=[m for m in (p.get("mountpoints") or []) if m])
            for p in _walk_children(n)
        ]
        devices.append(StorageDevice(
            name=name, model=clean(n.get("model")), size_bytes=_int(n.get("size")),
            media_type=_media_type(name, n.get("tran"), n.get("rota")),  # type: ignore[arg-type]
            transport=clean(n.get("tran")), removable=n.get("rm"), read_only=n.get("ro"), partitions=parts,
        ))
    return devices


def _walk_children(node: dict) -> list[dict]:
    out: list[dict] = []
    for c in node.get("children") or []:
        out.append(c)
        out.extend(_walk_children(c))
    return out


# ------------------------------------------------------------------ lspci / nvidia-smi

_GPU_CLASS = re.compile(r"VGA compatible controller|3D controller|Display controller", re.I)


def _strip_ids(value: str | None) -> str | None:
    return clean(re.sub(r"\s*\[[0-9a-fA-F]{4}\]\s*$", "", value or "")) if value else None


def parse_lspci_vmm(text: str) -> list[dict[str, str]]:
    records = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rec = {}
        for line in block.splitlines():
            k, _, v = line.partition(":")
            if v:
                rec[k.strip()] = v.strip()
        if rec.get("Slot"):
            records.append(rec)
    return records


def parse_lspci_gpus(text: str) -> list[GpuDevice]:
    gpus = []
    for rec in parse_lspci_vmm(text):
        cls = rec.get("Class", "")
        if not _GPU_CLASS.search(cls):
            continue
        device = _strip_ids(rec.get("Device"))
        gpus.append(GpuDevice(
            slot=clean(rec.get("Slot")), vendor=_strip_ids(rec.get("Vendor")),
            name=None if device is None or device.lower() == "device" else device,   # bare "Device [xxxx]" == unknown
            pci_class=_strip_ids(cls), driver=clean(rec.get("Driver")),
        ))
    return gpus


def parse_nvidia_smi_csv(text: str) -> list[tuple[str, int | None, str | None]]:
    rows = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0]:
            rows.append((clean(parts[0]) or parts[0], _int(parts[1]), clean(parts[2])))
    return rows
