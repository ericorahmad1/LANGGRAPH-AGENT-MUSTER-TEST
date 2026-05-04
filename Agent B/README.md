# Agent B — Customer Support Triage Agent

Agent LangGraph multi-node untuk **triage tiket customer support**. Pesan customer diklasifikasi (intent + sentiment + priority), dirutekan ke salah satu dari tiga spesialis (billing / technical / general), kemudian dijaga oleh QA reviewer dengan loop revisi otomatis sebelum di-format menjadi balasan final. Seluruh eksekusi di-trace ke **Langfuse**.

---

## 1. Arsitektur Graph

```
                     ┌──────────┐
                     │ classify │  intent + sentiment + priority
                     └────┬─────┘
                          ▼  (route by intent)
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐      ┌──────────┐      ┌─────────┐
   │ billing │      │ technical│      │ general │
   └────┬────┘      └────┬─────┘      └────┬────┘
        └─────────────────┼─────────────────┘
                          ▼
                     ┌──────────┐
                     │   qa     │  score + passed + feedback (JSON)
                     └────┬─────┘
              qa_passed=False & retries<2
                          │
                ┌─────────┴─────────┐
                ▼                   ▼
           ┌─────────┐         ┌──────────┐
           │ revise  │──loop──▶│   qa     │
           └─────────┘         └────┬─────┘
                                    ▼ (lolos / max retry)
                               ┌──────────┐
                               │ finalize │  format reply + metadata
                               └────┬─────┘
                                    ▼
                                   END
```

**Threshold default:** `QA_PASS_THRESHOLD = 0.8`, `MAX_RETRIES = 2`.

---

## 2. State (`SupportState`)

| Field             | Tipe    | Deskripsi                                              |
| ----------------- | ------- | ------------------------------------------------------ |
| `user_message`    | `str`   | Pesan asli customer                                    |
| `customer_name`   | `str`   | Nama customer untuk salutation                         |
| `intent`          | `str`   | `billing` / `technical` / `general`                    |
| `sentiment`       | `str`   | `positive` / `neutral` / `negative`                    |
| `priority`        | `str`   | `low` / `medium` / `high`                              |
| `draft_response`  | `str`   | Draft jawaban dari spesialis / reviser                 |
| `qa_feedback`     | `str`   | Bullet feedback QA reviewer                            |
| `qa_score`        | `float` | Skor QA (0.0–1.0)                                      |
| `qa_passed`       | `bool`  | Lolos QA (passed AND `score ≥ 0.8`)                    |
| `retries`         | `int`   | Jumlah revisi yang sudah dilakukan                     |
| `final_response`  | `str`   | Balasan akhir + header metadata                        |

---

## 3. Penjelasan Node

| Node        | Tujuan                                                                                          | Temperature |
| ----------- | ----------------------------------------------------------------------------------------------- | ----------- |
| `classify`  | Ekstrak intent + sentiment + priority. Output strict JSON; fallback aman bila parse gagal.      | 0.0         |
| `billing`   | Spesialis billing. Guardrail: TIDAK menjanjikan refund tanpa review; SLA 2 hari kerja.          | 0.3         |
| `technical` | Spesialis teknis. Guardrail: minta repro steps; checklist troubleshooting; tanpa janji ETA.     | 0.3         |
| `general`   | Customer success. Guardrail: ringkas; klarifikasi 1 pertanyaan bila ambigu; arahkan help center.| 0.4         |
| `qa`        | Review draft: relevansi, faktual, tone, kepatuhan kebijakan, kejelasan. Output JSON terstruktur.| 0.0         |
| `revise`    | Rewrite draft sesuai `qa_feedback`; increment `retries`; balik ke `qa`.                         | 0.2         |
| `finalize`  | Tambah header metadata `[Intent / Priority / Sentiment / QA score]` + salutation jika belum.    | —           |

### Conditional edges

- `route_by_intent(state)` → `billing` | `technical` | `general` (default `general` jika invalid).
- `qa_decision(state)` →
  - `finalize` jika `qa_passed=True`,
  - `finalize` jika `retries ≥ 2`,
  - `revise` selainnya.

---

## 4. Guardrail Tiap Spesialis

| Spesialis  | Guardrail kunci                                                                |
| ---------- | ------------------------------------------------------------------------------ |
| Billing    | Tidak menjanjikan refund; SLA 2 hari kerja; tawarkan eskalasi billing team.    |
| Technical  | Tanya OS/version/repro steps; checklist troubleshooting; no fix-ETA promise.   |
| General    | Ringkas; satu clarifying question bila ambigu; arahkan ke help center.         |

---

## 5. Helper

- `build_llm()` – instansiasi `ChatGoogleGenerativeAI` (model dari env `LANGGRAPH_MODEL`).
- `build_langfuse_handler()` – setup Langfuse + `CallbackHandler` (kompatibel beberapa versi SDK).
- `_extract_json()` – parser JSON tahan ```json fence``` & teks pengantar.
- `_specialist_prompt()` – generator prompt seragam untuk tiga spesialis (DRY).

---

## 6. Tracing Langfuse

Setiap run dipanggil via:

```python
graph.invoke(
    initial,
    config={
        "run_name": "agent-b-support-triage",
        "tags": ["langgraph", "agent-b", "support"],
        "callbacks": [build_langfuse_handler()],
    },
)
```

Trace muncul di project Langfuse sesuai `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_HOST` di `.env`.

---

## 7. Konfigurasi `.env`

```env
GOOGLE_API_KEY="..."
LANGFUSE_SECRET_KEY="..."
LANGFUSE_PUBLIC_KEY="..."
LANGFUSE_HOST="https://dev.elit-dev.myelitest.com"
LANGGRAPH_MODEL=gemini-2.5-pro
```

---

## 8. Cara Menjalankan

```bash
cd "Agent B"
pip install -r requirements.txt
python support_agent.py
```

Default sample: customer mengeluh **double charge** subscription Pro (intent diharapkan = `billing`, priority = `high`).

Untuk pesan kustom panggil dari Python:

```python
from support_agent import run_once
result = run_once(
    "Aplikasi crash setiap kali saya buka dashboard di Chrome 124.",
    customer_name="Sari",
)
print(result["final_response"])
```

---

## 9. Output yang Dicetak

```
=== Classification ===
 intent=billing | sentiment=negative | priority=high

=== QA: score=0.86 | passed=True | retries=1 ===

=== Final Response ===
[Intent: billing | Priority: high | Sentiment: negative | QA score: 0.86]

Hi Andi,

...isi balasan...
```

---

## 10. Tuning Cepat

| Yang ingin diubah                           | Edit di `support_agent.py`        |
| ------------------------------------------- | --------------------------------- |
| Ambang lulus QA                             | `QA_PASS_THRESHOLD`               |
| Maksimum revisi otomatis                    | `MAX_RETRIES`                     |
| Daftar intent valid                         | `VALID_INTENTS` + node spesialis  |
| Guardrail per spesialis                     | String `guardrails` di tiap node  |
| Format header final response                | `finalizer_node`                  |
| Model LLM                                   | Env `LANGGRAPH_MODEL`             |

---

## 11. Menambah Spesialis Baru

1. Buat node `xxx_node(state)` mirip `billing_node`, definisikan guardrail.
2. Tambahkan ke `VALID_INTENTS`.
3. Daftarkan node + tambahkan mapping di `add_conditional_edges("classify", route_by_intent, {...})`.
4. Tambahkan edge `xxx → qa`.
