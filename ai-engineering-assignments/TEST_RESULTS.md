# Test results

Run in the build sandbox: Ubuntu 24, Python 3.12, Node 22, **real** PostgreSQL 16 + pgvector 0.6.0, Redis 7.

| Suite | Result |
|---|---|
| Problem 1 backend (`pytest`) | **109 passed** (26 s) |
| Problem 1 frontend (`npm test`, `npm run build`) | **7 passed**; production build OK |
| Problem 2 (`pytest`) | **125 passed** (<1 s) |

## Problem 1 backend — 109 tests
| File | Tests | Covers |
|---|---|---|
| `test_security.py` | 43 | sanitisation, 11 injection attacks vs 4 benign texts, HMAC (round-trip, known vector, tamper, replay, malformed), SSRF (12 blocked URL forms), API-key hashing |
| `test_embeddings_reranking.py` | 14 | hashing embedder, Ollama/OpenAI embedders and Ollama/HTTP rerankers via mocked servers, dimension mismatch, failures |
| `test_agents_api.py` | 13 | registration, duplicate names, validation, injection, SSRF, auth on every route, key/secret rotation, rate limit, body-size cap |
| `test_posts_api.py` | 10 | draft/publish, draft privacy, author-only actions, filters, injection, threaded comments |
| `test_routing.py` | 9 | **integration** 3-stage routing on real pgvector, industry SQL filter, idempotency, top-N cap, reranker fallback, feedback loop |
| `test_delivery.py` | 14 | **integration** end-to-end via real RQ worker to a real HTTP receiver, signature verification, retries/backoff, non-retryable statuses, SSRF re-check, Redis outage |
| `test_engagement.py` | 6 | inbox, ack, feedback, cross-agent authorization |

Mutation checks performed: breaking the HMAC body binding and removing the author-exclusion rule each made tests fail.

## Problem 2 — 125 tests
| File | Tests | Covers |
|---|---|---|
| `test_executor.py` | 33 | allow-list, `shell=False`, timeout, missing command, permission errors, output cap, file/symlink/traversal guards |
| `test_parsers.py` | 24 | lscpu/lsblk/free/meminfo/dmidecode/lspci/nvidia-smi parsing, privacy redaction, unknown-not-guessed |
| `test_collectors.py` | 23 | every fallback path, non-root/VM behaviour, plus tests against the **real machine** (`/proc`, `/sys`) |
| `test_tools.py` | 8 | schemas, argument validation, unknown-tool refusal |
| `test_llm.py` | 15 | Ollama client via mock transport, error messages, remote-host refusal |
| `test_agent.py` | 12 | tool loop, follow-up context, history window, step limit, shell-tool refusal, injection stays in tool role |
| `test_cli.py` | 10 | inspect, chat session, slash commands, LLM errors, doctor |

Mutation checks performed: `shell=True` and adding `/proc/self/environ` to the allow-list each made tests fail.

## Not verified here
* A live Ollama server (not installable in the sandbox): the Ollama client, embedder and reranker are tested against mocked HTTP only.
* Browser UI interaction (build and API-client unit tests only).
