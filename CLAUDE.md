# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

Two independent LangGraph prototypes, each self-contained with its own `.env`, `requirements.txt`, and pre-created `env/` venv:

- `Agent A/` — Research & Report agent (`research_agent.py`)
- `Agent B/` — Customer Support Triage agent (`support_agent.py`)

`DEMO_TEST_SUMMARY.md` at the root is the latest cross-agent test snapshot.

## Common commands (PowerShell, Windows)

Each agent has its own venv at `Agent X/env/`. Use it directly — do not assume a project-wide venv.

```powershell
# Install deps (do once per agent, when requirements change)
& ".\Agent A\env\Scripts\python.exe" -m pip install -r ".\Agent A\requirements.txt"

# Run agent end-to-end with the built-in sample input
& ".\Agent A\env\Scripts\python.exe" ".\Agent A\research_agent.py"
& ".\Agent B\env\Scripts\python.exe" ".\Agent B\support_agent.py"

# Run all test scenarios for an agent
& ".\Agent A\env\Scripts\python.exe" ".\Agent A\test_runner.py"
& ".\Agent B\env\Scripts\python.exe" ".\Agent B\test_runner.py"

# Run a single scenario (test ids are positional args)
& ".\Agent A\env\Scripts\python.exe" ".\Agent A\test_runner.py" 1   # revise-loop
& ".\Agent B\env\Scripts\python.exe" ".\Agent B\test_runner.py" 3   # qa-revise-loop
```

Test ids:
- Agent A: `1` revise-loop, `2` custom, `3` edge-empty
- Agent B: `1` billing, `2` technical, `3` general, `4` qa-revise-loop

There is no lint/typecheck tooling configured.

## Architecture — shared shape

Both agents share the same skeleton; understand it once and the rest reads quickly.

1. **State** — a `TypedDict` carrying every field nodes read or write (no hidden mutable globals).
2. **Nodes** — plain functions `(state) -> state`. Each node calls `build_llm(temperature=...)` (different temps per role) and returns a new state dict via `{**state, ...}`.
3. **Conditional edges** — pure routing functions returning the next node name; gating uses both a quality threshold (`CONFIDENCE_THRESHOLD` / `QA_PASS_THRESHOLD`) and a hard cap (`MAX_ITERATIONS` / `MAX_RETRIES`) to prevent infinite revise loops.
4. **Helpers** — `build_llm`, `build_langfuse_handler`, `_extract_json`. Duplicated verbatim across both agents (intentional — they are independent prototypes).

### LLM + Langfuse wiring (important)

- LLM is `ChatGoogleGenerativeAI`, model from env `LANGGRAPH_MODEL` (default `gemini-2.5-pro`).
- `build_langfuse_handler()` returns a **tuple** `(handler, client)` — the caller MUST `client.flush()` in a `finally` block, otherwise spans are dropped on multi-run scripts. `run_once` already does this.
- The handler is constructed via `inspect.signature` to stay compatible with both the old (`langfuse.callback`) and new (`langfuse.langchain`) SDK import paths. Don't simplify this — it is deliberate cross-version compatibility.
- Run config passes `run_name`, `tags`, and `callbacks=[handler]` to `graph.invoke(...)`. Keep this pattern when adding new entry points.
- LLM JSON output is parsed by `_extract_json`, which tolerates ` ```json ``` ` fences and prose around the JSON. Re-use it for any new structured-output node.

### Agent A graph
`plan → research → critic → (revise → critic)* → report → END`
Critic emits `{confidence, feedback}`. `should_revise` routes to `revise` while `confidence < CONFIDENCE_THRESHOLD` AND `iterations < MAX_ITERATIONS`.

### Agent B graph
`classify → {billing|technical|general} → qa → (revise → qa)* → finalize → END`
Classifier emits `{intent, sentiment, priority}` (intent falls back to `general` on parse failure or invalid value). Specialists share `_specialist_prompt(role, guardrails, state)` for DRY prompt assembly — when adding a new specialist, follow the steps in `Agent B/README.md` §11.

## Known behaviors / gotchas

(From `Agent A/TESTING_NOTES.md` and `Agent B/TESTING_NOTES.md` — read those before debugging.)

- **Empty topic in Agent A is not validated.** `run_once("")` does not crash; the planner falls back to `[""]`, the LLM picks its own topic, and a plausible-but-unrequested report is generated. If hardening is in scope, add validation in `run_once` or a `validate` node before `plan`.
- **Langfuse OTLP timeouts on `dev.elit-dev.myelitest.com` are expected** and do not affect graph execution. To raise the limit set `OTEL_EXPORTER_OTLP_TIMEOUT=10000` (ms). To rule out the agent, swap `LANGFUSE_HOST` to `https://cloud.langfuse.com`.
- Agent B's `qa_passed` is the AND of the LLM's `passed` flag AND `score >= QA_PASS_THRESHOLD` — both must hold to skip the revise loop.
- `test_runner.py` mutates module-level constants (`CONFIDENCE_THRESHOLD`, `MAX_ITERATIONS`) inside a `try/finally` to force the revise-loop scenarios. Restore in `finally` if you add similar tests.

## Required env vars (per-agent `.env`)

```
GOOGLE_API_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_HOST=https://dev.elit-dev.myelitest.com
LANGGRAPH_MODEL=gemini-2.5-pro
```

`LANGFUSE_HOST` falls back to `LANGFUSE_BASE_URL`, then to `https://cloud.langfuse.com`. Missing public/secret keys raise immediately in `build_langfuse_handler`.
