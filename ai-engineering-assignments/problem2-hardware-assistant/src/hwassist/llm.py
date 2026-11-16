"""LLM access. Default: a local Ollama server (/api/chat with native tool calling)."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import httpx


class LLMError(RuntimeError):
    """User-presentable LLM failure (server down, model missing, bad response)."""


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class AssistantMessage:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage: ...


def is_loopback_host(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OllamaClient:
    def __init__(self, host: str, model: str, timeout: float = 180.0, temperature: float = 0.1,
                 allow_remote: bool = False, client: httpx.Client | None = None):
        if not is_loopback_host(host) and not allow_remote:
            raise LLMError(
                f"Refusing to send hardware data to non-local LLM host {host!r}. "
                "Use a local Ollama, or pass --allow-remote-llm if you understand the privacy implications."
            )
        self.model = model
        self._url = host.rstrip("/") + "/api/chat"
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout)

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        body = {"model": self.model, "messages": messages, "tools": tools, "stream": False,
                "options": {"temperature": self._temperature}}
        try:
            resp = self._client.post(self._url, json=body)
        except httpx.ConnectError as exc:
            raise LLMError("Cannot connect to Ollama. Start it with `ollama serve` "
                           f"(expected at {self._url.rsplit('/api', 1)[0]}).") from exc
        except httpx.TimeoutException as exc:
            raise LLMError("The LLM timed out. Try a smaller model or raise HWASSIST_LLM_TIMEOUT_SECONDS.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        if resp.status_code == 404:
            raise LLMError(f"Model {self.model!r} not found. Install it with `ollama pull {self.model}`.")
        if resp.status_code == 400 and "tools" in resp.text.lower():
            raise LLMError(f"Model {self.model!r} does not support tool calling; choose e.g. llama3.1 or qwen2.5.")
        if resp.status_code >= 400:
            raise LLMError(f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            msg = resp.json()["message"]
            calls = [ToolCall(c["function"]["name"], c["function"].get("arguments") or {})
                     for c in msg.get("tool_calls") or []]
            return AssistantMessage(content=msg.get("content") or "", tool_calls=calls)
        except (KeyError, TypeError, ValueError) as exc:
            raise LLMError("Unexpected response format from Ollama.") from exc

    def list_models(self) -> list[str]:
        try:
            r = self._client.get(self._url.replace("/api/chat", "/api/tags"))
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"Cannot list Ollama models: {exc}") from exc
