# Problem 2 — Linux Hardware Q&A Assistant

A local, CLI chat assistant that answers questions about your Linux laptop's **CPU, RAM, storage, GPU and
motherboard**. A local LLM (Ollama) decides which *tool* to call; every fact in an answer comes from parsed
system output — nothing is hard-coded or invented.

## Requirements
Python 3.11+, Linux, [Ollama](https://ollama.com) with a **tool-calling model** (e.g. `llama3.1:8b`, `qwen2.5:7b`).
Optional system tools (the assistant degrades gracefully without them): `lscpu lsblk free lspci dmidecode nvidia-smi`.

## Install & run
```bash
cd problem2-hardware-assistant
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .      # provides the `hwassist` command

ollama pull llama3.1:8b && ollama serve                  # in another terminal if not already running

hwassist doctor            # which commands work, root?, Ollama + model reachable?
hwassist chat              # interactive assistant      (or: python -m hwassist chat)
hwassist inspect all --json    # structured data WITHOUT an LLM (exactly what the tools return)
hwassist inspect gpu
sudo hwassist inspect motherboard   # root unlocks dmidecode (RAM module type/speed, board model)
```
Example session:
```
you › what cpu do I have and how many cores?
tools: get_cpu_info
Intel Core i7-1165G7 — 4 physical cores / 8 threads, max 4700 MHz.
you › and the RAM?            # follow-up; context is kept
you › what motherboard is it?
I can't determine it: no DMI data is readable (dmidecode needs root; /sys/class/dmi is empty in VMs).
```
Chat commands: `/tools` `/reset` `/help` `/exit`. Flags: `--model`, `--host`, `--hide-tools`.
Config via env (`.env.example`): `HWASSIST_MODEL`, `HWASSIST_OLLAMA_HOST`, …

## Tests
```bash
pip install -r requirements-dev.txt && pytest
```
Parser tests use realistic captured formats; collector tests simulate laptops/VMs/non-root machines by replacing
only the three executor primitives; several tests run against the **real machine** and compare with `/proc` and `/sys`.
The LLM boundary is tested with a scripted test double and `httpx.MockTransport` (no live model needed).

## Architecture
```
cli.py ─▶ agent.py (conversation loop, history window, step limit)
              │  tool calls                      ▲ tool results (JSON)
              ▼                                  │
          llm.py (Ollama /api/chat) ◀──▶ tools.py (registry + Pydantic arg validation)
                                              │
                                        collectors.py (merge sources, fall back, record errors/notes)
                                              │
                      parsers.py (pure: text → Pydantic models)      executor.py  ◀── ONLY OS access
```
* **Tool/function calling** — six tools (`get_cpu_info`, `get_memory_info`, `get_storage_info`, `get_gpu_info`,
  `get_motherboard_info`, `get_system_overview`) with JSON-schema parameters. Unknown tools / bad arguments return a
  structured error to the model; the loop is capped (`max_tool_steps`).
* **Structured output** — Pydantic models; unknown stays `None` and is omitted, never guessed. Human-readable sizes
  (`15.5 GiB`) are computed deterministically so the LLM never does unit maths. Virtual disks are labelled `virtual`
  rather than mis-reported as HDD/SSD.
* **Fallbacks** — `lscpu`→`/proc/cpuinfo`, `free`→`/proc/meminfo`, `lsblk`→`/sys/block`, `dmidecode`→`/sys/class/dmi/id`,
  `lspci`→`/sys/class/drm`. Each report lists `sources`, typed `errors` (`not_installed`, `permission_denied`, `timeout`,
  `not_found`, `parse_error`…) and plain-English `notes`, which the system prompt requires the model to relay.
* **Conversation** — rolling window of the last N turns (user + tool calls + tool results + answer), so follow-ups like
  "and how much of it is free?" work; `/reset` clears it.

## Security & privacy decisions
* **Strict allow-list** (`executor.ALLOWED_COMMANDS`): commands are selected by key; argv is hard-coded. The LLM/user cannot
  supply a command name, flag or path (tests assert no tool exposes such a parameter).
* `subprocess.run(argv_list, shell=False, timeout=…, stdin=DEVNULL)`, binary resolved from a fixed system `PATH`, environment
  reduced to `PATH/LC_ALL/LANG`, output capped at 1 MB.
* `/proc` and `/sys` reads only for explicit paths/regexes, and the *resolved* path must still be under `/proc` or `/sys`.
* No `sudo` anywhere: privilege problems are reported, not escalated.
* **Privacy:** serial numbers, UUIDs, asset tags are never requested; MAC/UUID patterns in free text are masked. All data
  stays on the machine: the client **refuses non-loopback LLM hosts** unless `--allow-remote-llm` is given.
* **Prompt-injection hygiene:** hardware strings are sanitised (control chars stripped, length-capped) and only ever reach
  the model in the `tool` role; the system prompt marks tool output as untrusted.

## Limitations
* Answer faithfulness ultimately depends on the model; the design minimises risk (grounding rules, deterministic sizes,
  explicit unavailability notes) but cannot mathematically prevent a weak model from misreporting tool data. Use a
  tool-capable ≥7B model.
* Not validated against a live Ollama in the build environment (none available); the client is verified against a mocked
  Ollama API. Run `hwassist doctor` then `hwassist chat` to confirm on your machine.
* Linux only; RAM module details, board model and some BIOS fields need root and real SMBIOS data (absent in most VMs).
