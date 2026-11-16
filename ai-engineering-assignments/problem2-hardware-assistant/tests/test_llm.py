import json

import httpx
import pytest

from hwassist.llm import LLMError, OllamaClient


def client(handler, **kw):
    return OllamaClient("http://127.0.0.1:11434", "llama3.1:8b", client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)


def test_parses_tool_calls_and_sends_tools_stream_false():
    def handler(req):
        body = json.loads(req.content)
        assert req.url.path == "/api/chat" and body["stream"] is False and body["model"] == "llama3.1:8b"
        assert body["tools"][0]["function"]["name"] == "t" and body["options"]["temperature"] == 0.1
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "get_cpu_info", "arguments": {}}}]}})
    msg = client(handler).chat([{"role": "user", "content": "hi"}], [{"function": {"name": "t"}}])
    assert [c.name for c in msg.tool_calls] == ["get_cpu_info"] and msg.content == ""


def test_plain_answer():
    msg = client(lambda r: httpx.Response(200, json={"message": {"content": "You have 16 GiB."}})).chat([], [])
    assert msg.content == "You have 16 GiB." and msg.tool_calls == []


def test_connection_refused_message_is_actionable():
    def handler(req):
        raise httpx.ConnectError("refused")
    with pytest.raises(LLMError, match="ollama serve"):
        client(handler).chat([], [])


def test_timeout_message():
    def handler(req):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(LLMError, match="timed out"):
        client(handler).chat([], [])


def test_missing_model_suggests_pull():
    with pytest.raises(LLMError, match="ollama pull llama3.1:8b"):
        client(lambda r: httpx.Response(404, json={"error": "model not found"})).chat([], [])


def test_model_without_tool_support():
    with pytest.raises(LLMError, match="does not support tool calling"):
        client(lambda r: httpx.Response(400, text='{"error":"registry.ollama.ai/x does not support tools"}')).chat([], [])


def test_garbage_response():
    with pytest.raises(LLMError, match="Unexpected response"):
        client(lambda r: httpx.Response(200, json={"nope": 1})).chat([], [])


@pytest.mark.parametrize("host", ["http://example.com:11434", "http://192.168.1.50:11434", "https://api.openai.com"])
def test_refuses_remote_hosts_by_default(host):
    with pytest.raises(LLMError, match="non-local"):
        OllamaClient(host, "m")


@pytest.mark.parametrize("host", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"])
def test_accepts_loopback(host):
    assert OllamaClient(host, "m").model == "m"


def test_remote_allowed_only_with_explicit_flag():
    assert OllamaClient("http://10.0.0.5:11434", "m", allow_remote=True)


def test_list_models():
    c = client(lambda r: httpx.Response(200, json={"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5:7b"}]}))
    assert c.list_models() == ["llama3.1:8b", "qwen2.5:7b"]
