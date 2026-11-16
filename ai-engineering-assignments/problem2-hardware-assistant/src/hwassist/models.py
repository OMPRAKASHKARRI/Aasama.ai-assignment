"""Structured hardware data (Pydantic). Every field is Optional: unknown stays None, it is never guessed."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field


def human_bytes(n: int | None) -> str | None:
    """Deterministic IEC formatting so the LLM never has to do unit arithmetic."""
    if n is None:
        return None
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if size < 1024 or unit == "PiB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return None


class CpuInfo(BaseModel):
    model_name: str | None = None
    vendor: str | None = None
    architecture: str | None = None
    logical_cpus: int | None = None
    sockets: int | None = None
    cores_per_socket: int | None = None
    threads_per_core: int | None = None
    max_mhz: float | None = None
    min_mhz: float | None = None
    cache_l1d: str | None = None
    cache_l1i: str | None = None
    cache_l2: str | None = None
    cache_l3: str | None = None
    virtualization: str | None = None
    hypervisor: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def physical_cores(self) -> int | None:
        if self.sockets and self.cores_per_socket:
            return self.sockets * self.cores_per_socket
        return None


class MemoryModule(BaseModel):
    locator: str | None = None
    size_bytes: int | None = None
    type: str | None = None
    speed_mt_s: int | None = None
    form_factor: str | None = None
    manufacturer: str | None = None
    part_number: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def size_human(self) -> str | None:
        return human_bytes(self.size_bytes)


class MemoryInfo(BaseModel):
    total_bytes: int | None = None
    available_bytes: int | None = None
    used_bytes: int | None = None
    swap_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    slots_total: int | None = None
    slots_populated: int | None = None
    max_capacity_bytes: int | None = None
    modules: list[MemoryModule] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_human(self) -> str | None:
        return human_bytes(self.total_bytes)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def available_human(self) -> str | None:
        return human_bytes(self.available_bytes)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def used_human(self) -> str | None:
        return human_bytes(self.used_bytes)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def swap_total_human(self) -> str | None:
        return human_bytes(self.swap_total_bytes)


class Partition(BaseModel):
    name: str
    size_bytes: int | None = None
    fstype: str | None = None
    mountpoints: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def size_human(self) -> str | None:
        return human_bytes(self.size_bytes)


class StorageDevice(BaseModel):
    name: str
    model: str | None = None
    size_bytes: int | None = None
    media_type: Literal["nvme", "ssd", "hdd", "virtual", "unknown"] = "unknown"
    transport: str | None = None
    removable: bool | None = None
    read_only: bool | None = None
    partitions: list[Partition] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def size_human(self) -> str | None:
        return human_bytes(self.size_bytes)


class StorageInfo(BaseModel):
    devices: list[StorageDevice] = Field(default_factory=list)
    total_bytes: int | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_human(self) -> str | None:
        return human_bytes(self.total_bytes)


class GpuDevice(BaseModel):
    slot: str | None = None
    vendor: str | None = None
    name: str | None = None
    pci_class: str | None = None
    driver: str | None = None
    vram_mib: int | None = None
    driver_version: str | None = None


class GpuInfo(BaseModel):
    devices: list[GpuDevice] = Field(default_factory=list)


class MotherboardInfo(BaseModel):
    board_vendor: str | None = None
    board_name: str | None = None
    board_version: str | None = None
    bios_vendor: str | None = None
    bios_version: str | None = None
    bios_date: str | None = None
    system_vendor: str | None = None
    product_name: str | None = None
    product_version: str | None = None


class ComponentReport(BaseModel):
    """What a tool returns to the LLM: data + provenance + every reason something is missing."""
    component: str
    available: bool
    data: dict | None = None
    sources: list[str] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
