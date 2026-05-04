# LangGraph Agent Muster Test

Prototipe dua **LangGraph multi-node agent** dengan tracing **Langfuse**, dibangun untuk menguji pola umum agentic workflow: dekomposisi tugas, fan-out, self-critique, conditional routing, dan revise loop terjaga oleh hard cap.

Kedua agent berdiri sendiri (independent venv, `.env`, dan dependency) sehingga bisa dijalankan / dimodifikasi tanpa saling memengaruhi.

---

## Project overview

| Agent | Domain | Pola graph | Output |
| --- | --- | --- | --- |
| **Agent A — Research & Report** | Riset topik | `plan → research → critic ⇄ revise → report` | Laporan markdown (Title / Executive Summary / Findings / Conclusion) |
| **Agent B — Customer Support Triage** | Customer service | `classify → {billing\|technical\|general} → qa ⇄ revise → finalize` | Balasan customer-ready dengan header metadata (`intent / priority / sentiment / qa score`) |

Pola yang sengaja dipakai di **kedua** agent (untuk memvalidasi reusable pattern):

1. **State terstruktur** via `TypedDict` — semua field dinode read/write eksplisit, tanpa state global.
2. **Conditional revise loop** — tiap agent punya threshold mutu (`CONFIDENCE_THRESHOLD` / `QA_PASS_THRESHOLD`) **dan** hard cap (`MAX_ITERATIONS` / `MAX_RETRIES`) untuk mencegah loop tak terbatas.
3. **Structured LLM output (JSON)** dengan parser tahan banting `_extract_json` (toleran terhadap fence ` ```json ``` ` & teks pengantar).
4. **Langfuse tracing** via `CallbackHandler` yang dipasang ke `graph.invoke(..., config={"callbacks": [...]})` — kompatibel SDK lama (`langfuse.callback`) maupun baru (`langfuse.langchain`).
5. **`build_llm(temperature=...)`** per node — temperature berbeda untuk planner (0.1), classifier/critic/QA (0.0), specialist (0.3-0.4), reporter/reviser (0.2).

---

## Stack

- Python 3.x + venv per-agent (`Agent X/env/`)
- [`langgraph`](https://github.com/langchain-ai/langgraph) — orchestration graph
- [`langchain-google-genai`](https://pypi.org/project/langchain-google-genai/) → **Gemini 2.5 Pro** (default, bisa override via `LANGGRAPH_MODEL`)
- [`langfuse==4.0.4`](https://langfuse.com/) — observability (self-hosted di `dev.elit-dev.myelitest.com`, atau bisa diarahkan ke `cloud.langfuse.com`)

---

## Struktur

```
.
├── Agent A/                # Research & Report agent
│   ├── research_agent.py   # graph builder + run_once()
│   ├── test_runner.py      # 3 skenario test
│   ├── README.md           # detail arsitektur Agent A
│   ├── TESTING_NOTES.md    # behavior verified + known issues
│   ├── requirements.txt
│   └── env/                # venv (gitignored)
├── Agent B/                # Customer Support Triage agent
│   ├── support_agent.py
│   ├── test_runner.py      # 4 skenario test
│   ├── README.md
│   ├── TESTING_NOTES.md
│   ├── requirements.txt
│   └── env/
├── DEMO_TEST_SUMMARY.md    # hasil run demo cross-agent
├── CLAUDE.md               # panduan untuk Claude Code
└── README.md               # file ini
```

---

## Quick start (Windows / PowerShell)

Tiap agent punya venv sendiri di `Agent X/env/`. Tidak ada venv level project.

```powershell
# 1. Siapkan .env per agent (lihat contoh di bawah)

# 2. Install deps (sekali, atau saat requirements berubah)
& ".\Agent A\env\Scripts\python.exe" -m pip install -r ".\Agent A\requirements.txt"
& ".\Agent B\env\Scripts\python.exe" -m pip install -r ".\Agent B\requirements.txt"

# 3. Jalankan agent dengan sample input bawaan
& ".\Agent A\env\Scripts\python.exe" ".\Agent A\research_agent.py"
& ".\Agent B\env\Scripts\python.exe" ".\Agent B\support_agent.py"

# 4. Jalankan semua skenario test
& ".\Agent A\env\Scripts\python.exe" ".\Agent A\test_runner.py"
& ".\Agent B\env\Scripts\python.exe" ".\Agent B\test_runner.py"

# 5. Jalankan satu skenario test saja (id positional)
& ".\Agent A\env\Scripts\python.exe" ".\Agent A\test_runner.py" 1   # revise-loop
& ".\Agent B\env\Scripts\python.exe" ".\Agent B\test_runner.py" 4   # qa-revise-loop
```

**Test ids:**
- Agent A: `1` revise-loop, `2` custom-topic, `3` edge-empty
- Agent B: `1` billing, `2` technical, `3` general, `4` qa-revise-loop

---

## Konfigurasi `.env` (per agent)

```env
GOOGLE_API_KEY="..."
LANGFUSE_SECRET_KEY="..."
LANGFUSE_PUBLIC_KEY="..."
LANGFUSE_HOST="https://dev.elit-dev.myelitest.com"
LANGGRAPH_MODEL=gemini-2.5-pro
```

`LANGFUSE_HOST` otomatis fallback ke `LANGFUSE_BASE_URL`, lalu ke `https://cloud.langfuse.com`. `LANGFUSE_PUBLIC_KEY` & `LANGFUSE_SECRET_KEY` **wajib** — kalau kosong `build_langfuse_handler()` raise `ValueError`.

---

## Hasil demo (snapshot 2026-04-29)

| Agent | Tests | Status |
| --- | --- | --- |
| Agent A — Research Agent | 3/3 | ALL PASSED |
| Agent B — Customer Support Triage | 4/4 | ALL PASSED |

Detail per skenario di [`DEMO_TEST_SUMMARY.md`](./DEMO_TEST_SUMMARY.md).

---

## Dokumentasi lanjutan

- **Detail arsitektur per agent** → `Agent A/README.md`, `Agent B/README.md`
- **Behavior nyata + known issues** (mis. empty-topic hallucination Agent A, OTLP timeout Langfuse) → `Agent A/TESTING_NOTES.md`, `Agent B/TESTING_NOTES.md`
- **Panduan untuk Claude Code** (commands, arsitektur big-picture, gotchas) → `CLAUDE.md`
