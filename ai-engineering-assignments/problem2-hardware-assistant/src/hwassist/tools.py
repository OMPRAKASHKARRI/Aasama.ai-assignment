"""LLM tool definitions (function calling) and a validated dispatcher.

The model can only request tools from this registry; arguments are validated by Pydantic; unknown tools and
bad arguments produce a structured error that is fed back to the model rather than raising.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, ValidationError

from hwassist import collectors

MAX_RESULT_CHARS = 14_000


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_modules: bool = True


class StorageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_partitions: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: Callable[..., object]


def _overview(_: NoArgs) -> dict:
    return {k: v.model_dump(exclude_none=True) for k, v in collectors.collect_all().items()}


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("get_cpu_info", "CPU model, vendor, architecture, cores/threads, clock speeds and caches.", NoArgs,
         lambda a: collectors.collect_cpu()),
    Tool("get_memory_info", "RAM total/used/available, swap, and (when readable) DIMM type, speed and slots.",
         MemoryArgs, lambda a: collectors.collect_memory(a.include_modules)),
    Tool("get_storage_info", "Disks: model, size, SSD/HDD/NVMe type, transport and optionally partitions.",
         StorageArgs, lambda a: collectors.collect_storage(a.include_partitions)),
    Tool("get_gpu_info", "Graphics adapters: vendor, model, driver and VRAM when available.", NoArgs,
         lambda a: collectors.collect_gpu()),
    Tool("get_motherboard_info", "Motherboard, BIOS/UEFI and system vendor/product from DMI.", NoArgs,
         lambda a: collectors.collect_motherboard()),
    Tool("get_system_overview", "All of the above in one call. Use for broad questions like 'what are my specs'.",
         NoArgs, _overview),
)}


def tool_schemas() -> list[dict]:
    """Ollama/OpenAI-style function definitions."""
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.args.model_json_schema()}} for t in TOOLS.values()]


def execute_tool(name: str, arguments: dict | str | None) -> str:
    """Validate and run a tool; always returns a JSON string (errors included)."""
    tool = TOOLS.get(name)
    if tool is None:
        return json.dumps({"error": f"unknown tool {name!r}", "available_tools": sorted(TOOLS)})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except ValueError:
            return json.dumps({"error": "tool arguments must be a JSON object"})
    try:
        args = tool.args.model_validate(arguments or {})
    except ValidationError as exc:
        return json.dumps({"error": "invalid arguments", "details": [e["msg"] for e in exc.errors()]})
    result = tool.run(args)
    payload = result.model_dump(exclude_none=True) if isinstance(result, BaseModel) else result
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = json.dumps({"error": "result too large; call a more specific tool", "truncated_preview": text[:2000]})
    return text
