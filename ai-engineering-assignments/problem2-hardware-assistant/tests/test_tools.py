import json
import subprocess

from hwassist import tools
from tests.conftest import ok


def test_schemas_are_valid_function_definitions():
    schemas = tools.tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names == {"get_cpu_info", "get_memory_info", "get_storage_info", "get_gpu_info", "get_motherboard_info", "get_system_overview"}
    for s in schemas:
        assert s["type"] == "function" and s["function"]["description"] and s["function"]["parameters"]["type"] == "object"


def test_no_tool_accepts_a_command_or_path_parameter():
    banned = {"command", "cmd", "shell", "path", "file", "args", "argv", "script", "binary"}
    for s in tools.tool_schemas():
        assert not banned & set(s["function"]["parameters"].get("properties", {}))


def test_execute_returns_json_with_provenance(laptop):
    out = json.loads(tools.execute_tool("get_cpu_info", {}))
    assert out["component"] == "cpu" and out["available"] and out["sources"]


def test_execute_with_arguments_and_json_string_arguments(laptop):
    assert json.loads(tools.execute_tool("get_storage_info", {"include_partitions": True}))["data"]["devices"][0]["partitions"]
    assert json.loads(tools.execute_tool("get_storage_info", '{"include_partitions": true}'))["data"]["devices"][0]["partitions"]
    assert json.loads(tools.execute_tool("get_cpu_info", None))["available"]


def test_unknown_tool_is_rejected_and_nothing_runs(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    for name in ("run_shell", "bash", "get_cpu_info; rm -rf /", "../etc/passwd"):
        out = json.loads(tools.execute_tool(name, {"command": "id"}))
        assert "unknown tool" in out["error"] and "get_cpu_info" in out["available_tools"]


def test_invalid_arguments_rejected(laptop):
    assert "invalid arguments" in json.loads(tools.execute_tool("get_cpu_info", {"command": "id"}))["error"]
    assert "invalid arguments" in json.loads(tools.execute_tool("get_storage_info", {"include_partitions": "maybe"}))["error"]
    assert "JSON object" in json.loads(tools.execute_tool("get_cpu_info", "{broken"))["error"]


def test_overview_contains_every_component(laptop):
    out = json.loads(tools.execute_tool("get_system_overview", {}))
    assert set(out) == {"cpu", "memory", "storage", "gpu", "motherboard"} and all(v["available"] for v in out.values())


def test_oversized_result_is_truncated_safely(laptop, monkeypatch):
    monkeypatch.setattr(tools, "MAX_RESULT_CHARS", 100)
    out = json.loads(tools.execute_tool("get_cpu_info", {}))
    assert "too large" in out["error"]
