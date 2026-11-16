import json

from typer.testing import CliRunner

from hwassist import cli
from hwassist.llm import LLMError
from tests.test_agent import ScriptedLLM, call, say

runner = CliRunner()


def test_inspect_all_json_on_real_machine():
    r = runner.invoke(cli.app, ["inspect", "all", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert set(data) == {"cpu", "memory", "storage", "gpu", "motherboard"}
    assert data["memory"]["available"] and data["memory"]["data"]["total_bytes"] > 0


def test_inspect_component_table(laptop):
    r = runner.invoke(cli.app, ["inspect", "cpu"])
    assert r.exit_code == 0 and "i7-1165G7" in r.stdout and "available" in r.stdout


def test_inspect_shows_errors_and_notes_when_unavailable(system):
    r = runner.invoke(cli.app, ["inspect", "motherboard"])
    assert r.exit_code == 0 and "UNAVAILABLE" in r.stdout and "note:" in r.stdout


def test_inspect_rejects_unknown_component():
    assert runner.invoke(cli.app, ["inspect", "bios; rm -rf /"]).exit_code != 0


def test_chat_session_with_followup_and_exit(laptop, monkeypatch):
    llm = ScriptedLLM(call("get_cpu_info"), say("You have an **i7-1165G7**."), say("It has 4 physical cores."))
    llm.model = "scripted"
    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: llm)
    r = runner.invoke(cli.app, ["chat"], input="what cpu do I have?\nhow many cores?\n/exit\n")
    assert r.exit_code == 0
    assert "i7-1165G7" in r.stdout and "4 physical cores" in r.stdout and "get_cpu_info" in r.stdout


def test_chat_slash_commands_and_blank_lines(monkeypatch):
    llm = ScriptedLLM(say("hi"))
    llm.model = "scripted"
    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: llm)
    r = runner.invoke(cli.app, ["chat"], input="\n/tools\n/reset\n/help\n/exit\n")
    assert r.exit_code == 0 and "get_gpu_info" in r.stdout and "conversation cleared" in r.stdout and llm.requests == []


def test_chat_survives_llm_errors(monkeypatch):
    class Down:
        model = "m"
        def chat(self, *a):
            raise LLMError("Cannot connect to Ollama. Start it with `ollama serve`")
    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: Down())
    r = runner.invoke(cli.app, ["chat"], input="hello\n/exit\n")
    assert r.exit_code == 0 and "ollama serve" in r.stdout


def test_chat_ends_cleanly_on_eof(monkeypatch):
    llm = ScriptedLLM()
    llm.model = "m"
    monkeypatch.setattr(cli, "_build_client", lambda *a, **k: llm)
    assert runner.invoke(cli.app, ["chat"], input="").exit_code == 0


def test_chat_refuses_remote_llm_host():
    r = runner.invoke(cli.app, ["chat", "--host", "http://example.com:11434"])
    assert r.exit_code == 2 and "non-local" in r.stdout


def test_doctor_runs_without_ollama():
    r = runner.invoke(cli.app, ["doctor", "--host", "http://127.0.0.1:1"])
    assert r.exit_code == 0 and "lscpu" in r.stdout and "ollama" in r.stdout.lower()
