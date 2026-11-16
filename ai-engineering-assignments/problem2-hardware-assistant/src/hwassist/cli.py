"""Command line interface:  hwassist chat | inspect | doctor"""
from __future__ import annotations

import json
import os
from enum import Enum
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from hwassist import __version__
from hwassist.agent import HardwareAssistant
from hwassist.collectors import COLLECTORS, collect_all
from hwassist.config import get_settings
from hwassist.executor import ALLOWED_COMMANDS, run_allowed
from hwassist.llm import LLMError, OllamaClient
from hwassist.tools import TOOLS

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Local Linux hardware Q&A assistant (CPU, RAM, storage, GPU, motherboard).")
console = Console()


class Component(str, Enum):
    cpu = "cpu"
    memory = "memory"
    storage = "storage"
    gpu = "gpu"
    motherboard = "motherboard"
    all = "all"


BANNER = ("Ask about your CPU, RAM, storage, GPU or motherboard. "
          "Commands: [bold]/help[/] [bold]/tools[/] [bold]/reset[/] [bold]/exit[/]")


def _build_client(host: str | None, model: str | None, allow_remote: bool) -> OllamaClient:
    s = get_settings()
    return OllamaClient(host or s.ollama_host, model or s.model, s.llm_timeout_seconds, s.temperature,
                        allow_remote or s.allow_remote_llm)


@app.command()
def chat(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Ollama model (must support tools)."),
    host: Optional[str] = typer.Option(None, "--host", help="Ollama URL (default http://127.0.0.1:11434)."),
    allow_remote_llm: bool = typer.Option(False, "--allow-remote-llm", help="Permit a non-local LLM host."),
    show_tools: bool = typer.Option(True, "--show-tools/--hide-tools", help="Show which tools the model calls."),
) -> None:
    """Interactive chat about this machine's hardware."""
    s = get_settings()
    try:
        client = _build_client(host, model, allow_remote_llm)
    except LLMError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2)
    assistant = HardwareAssistant(client, s.max_tool_steps, s.history_turns)
    console.print(Panel.fit(BANNER, title=f"hwassist {__version__} · model {client.model} · 100% local"))

    while True:
        try:
            question = console.input("[bold cyan]you ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not question:
            continue
        if question.lower() in ("/exit", "/quit", "exit", "quit"):
            break
        if question == "/reset":
            assistant.reset()
            console.print("[dim]conversation cleared[/]")
            continue
        if question == "/help":
            console.print(BANNER)
            continue
        if question == "/tools":
            for t in TOOLS.values():
                console.print(f"[bold]{t.name}[/] — {t.description}")
            continue
        try:
            with console.status("thinking…"):
                answer = assistant.ask(question)
        except LLMError as exc:
            console.print(f"[red]{exc}[/]")
            continue
        except KeyboardInterrupt:
            console.print("[yellow]cancelled[/]")
            continue
        if show_tools and answer.tool_calls:
            console.print("[dim]tools: " + ", ".join(f"{r.name}{'' if r.ok else ' (error)'}" for r in answer.tool_calls) + "[/]")
        console.print(Markdown(answer.text))


@app.command()
def inspect(
    component: Component = typer.Argument(Component.all, help="What to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Print structured JSON only."),
) -> None:
    """Print structured hardware data WITHOUT using an LLM (what the assistant's tools see)."""
    reports = collect_all() if component is Component.all else {component.value: COLLECTORS[component.value]()}
    if json_output:
        typer.echo(json.dumps({k: v.model_dump(exclude_none=True) for k, v in reports.items()}, indent=2))
        return
    for name, rep in reports.items():
        table = Table(title=f"{name} ({'available' if rep.available else 'UNAVAILABLE'})", show_lines=False)
        table.add_column("field", style="bold")
        table.add_column("value", overflow="fold")
        for k, v in (rep.data or {}).items():
            table.add_row(k, json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v))
        console.print(table)
        for e in rep.errors:
            console.print(f"  [yellow]![/] {e.get('kind')}: {e.get('message')}  [dim]({e.get('source') or ', '.join(e.get('sources', []))})[/]")
        for n in rep.notes:
            console.print(f"  [dim]note: {n}[/]")


@app.command()
def doctor(host: Optional[str] = typer.Option(None, "--host"), model: Optional[str] = typer.Option(None, "--model", "-m")) -> None:
    """Check which system commands exist, privileges, and whether Ollama and the model are ready."""
    table = Table(title="allow-listed commands")
    table.add_column("key"); table.add_column("status")
    seen: dict[str, str] = {}
    for key in ALLOWED_COMMANDS:
        r = run_allowed(key)
        seen[key] = "ok" if r.ok else f"{r.error_kind.value if r.error_kind else 'failed'}: {r.message[:60]}"
        table.add_row(key, ("[green]" if r.ok else "[yellow]") + seen[key] + "[/]")
    console.print(table)
    console.print(f"running as root: {'yes' if os.geteuid() == 0 else 'no (dmidecode will be unavailable; /sys DMI is used instead)'}")
    try:
        client = _build_client(host, model, False)
        models = client.list_models()
        wanted = client.model if ":" in client.model else client.model + ":latest"
        have = wanted in models
        console.print(f"ollama reachable: [green]yes[/] · model {client.model}: " + ("[green]installed[/]" if have else f"[red]missing[/] → ollama pull {client.model}"))
    except LLMError as exc:
        console.print(f"ollama: [red]{exc}[/]")


@app.callback(invoke_without_command=False)
def main() -> None:
    """hwassist"""


if __name__ == "__main__":
    app()
