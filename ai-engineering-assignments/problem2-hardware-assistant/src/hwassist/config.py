from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HWASSIST_", env_file=".env", extra="ignore")

    ollama_host: str = "http://127.0.0.1:11434"
    model: str = "llama3.1:8b"          # must support tool calling (llama3.1, qwen2.5, mistral-nemo, ...)
    llm_timeout_seconds: float = 180.0
    temperature: float = 0.1
    max_tool_steps: int = 6
    history_turns: int = 8
    # Privacy: hardware data is only ever sent to a loopback Ollama unless explicitly allowed.
    allow_remote_llm: bool = False


def get_settings() -> Settings:
    return Settings()
