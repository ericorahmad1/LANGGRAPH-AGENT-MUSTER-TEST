# Agent A — Research & Report Agent

Agent LangGraph multi-node yang men-generate **laporan riset markdown** dari sebuah topik. Agent ini melakukan dekomposisi pertanyaan, riset paralel, kritik mandiri (self-critique), dan loop revisi otomatis sebelum menyusun laporan final. Seluruh eksekusi di-trace ke **Langfuse**.

---

## 1. Arsitektur Graph

```
              ┌──────────┐
              │  plan    │  decompose topic → 3-5 sub-questions
              └────┬─────┘
                   ▼
              ┌──────────┐
              │ research │  jawab setiap sub-question (fan-out)
              └────┬─────┘
                   ▼
              ┌──────────┐
              │  critic  │  scoring confidence + feedback (JSON)
              └────┬─────┘
        confidence < 0.8 dan iter < 2
                   │
        ┌──────────┴──────────┐
        ▼                     ▼
   ┌─────────┐          ┌──────────┐
   │ revise  │──loop───▶│  critic  │
   └─────────┘          └────┬─────┘
                             ▼ (lolos / max iter)
                        ┌──────────┐
                        │  report  │  final markdown report
                        └────┬─────┘
                             ▼
                            END
```

**Threshold default:** `CONFIDENCE_THRESHOLD = 0.8`, `MAX_ITERATIONS = 2`.

---

## 2. State (`ResearchState`)

| Field           | Tipe         | Deskripsi                                              |
| --------------- | ------------ | ------------------------------------------------------ |
| `topic`         | `str`        | Topik input dari user                                  |
| `sub_questions` | `List[str]`  | Hasil dekomposisi planner (3–5 pertanyaan)             |
| `findings`      | `List[dict]` | List `{question, answer}` dari researcher / reviser    |
| `critique`      | `str`        | Feedback bullet dari critic (untuk revisi berikutnya)  |
| `confidence`    | `float`      | Skor kepercayaan critic (0.0–1.0)                      |
| `iterations`    | `int`        | Jumlah putaran critic yang sudah berjalan              |
| `final_report`  | `str`        | Output akhir markdown                                  |

---

## 3. Penjelasan Node

| Node       | Tujuan                                                                                  | Temperature |
| ---------- | --------------------------------------------------------------------------------------- | ----------- |
| `plan`     | Memecah topik jadi 3–5 sub-question non-overlapping. Output strict JSON array.          | 0.1         |
| `research` | Loop tiap sub-question, panggil LLM untuk jawaban faktual 4–7 kalimat.                  | 0.3         |
| `critic`   | Mengevaluasi seluruh Q&A: nilai `confidence` (float) + `feedback` (bullet actionable).  | 0.0         |
| `revise`   | Re-write tiap finding berdasarkan feedback critic, kemudian balik ke `critic`.          | 0.2         |
| `report`   | Komposisi laporan markdown final: Title, Executive Summary, Findings, Conclusion.       | 0.2         |

### Conditional edge (`should_revise`)
- Jika `confidence ≥ 0.8` → langsung ke `report`.
- Jika `iterations ≥ 2` → ke `report` (cegah infinite loop).
- Sisanya → `revise` (lalu kembali ke `critic`).

---

## 4. Helper

- `build_llm()` – instansiasi `ChatGoogleGenerativeAI` (model dari env `LANGGRAPH_MODEL`).
- `build_langfuse_handler()` – setup Langfuse + `CallbackHandler` (kompatibel beberapa versi SDK).
- `_extract_json()` – parser JSON tahan banting (tahan ```json fence``` & teks pengantar).

---

## 5. Tracing Langfuse

Setiap run dipanggil via:

```python
graph.invoke(
    initial,
    config={
        "run_name": "agent-a-research-report",
        "tags": ["langgraph", "agent-a", "research"],
        "callbacks": [build_langfuse_handler()],
    },
)
```

Trace muncul di project Langfuse sesuai `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_HOST` di `.env`.

---

## 6. Konfigurasi `.env`

```env
GOOGLE_API_KEY="..."
LANGFUSE_SECRET_KEY="..."
LANGFUSE_PUBLIC_KEY="..."
LANGFUSE_HOST="https://dev.elit-dev.myelitest.com"
LANGGRAPH_MODEL=gemini-2.5-pro
```

---

## 7. Cara Menjalankan

```bash
cd "Agent A"
pip install -r requirements.txt
python research_agent.py
```

Default sample topic: perbandingan **RAG vs fine-tuning** untuk customer-support assistant.

Untuk topik kustom panggil dari Python:

```python
from research_agent import run_once
result = run_once("Perbandingan event-driven vs orchestrated microservices.")
print(result["final_report"])
```

---

## 8. Output yang Dicetak

```
=== Sub-questions ===
 - ...
=== Critic confidence: 0.86 after 1 iteration(s) ===
=== Final Report ===
# Title
## Executive Summary
- ...
## Findings
### <sub-question>
...
## Conclusion
```

---

## 9. Tuning Cepat

| Yang ingin diubah                         | Edit di `research_agent.py` |
| ----------------------------------------- | --------------------------- |
| Ambang confidence untuk lolos             | `CONFIDENCE_THRESHOLD`      |
| Maksimum putaran revisi                   | `MAX_ITERATIONS`            |
| Jumlah sub-question planner               | Prompt di `planner_node`    |
| Format laporan akhir                      | Prompt di `reporter_node`   |
| Model LLM                                 | Env `LANGGRAPH_MODEL`       |
