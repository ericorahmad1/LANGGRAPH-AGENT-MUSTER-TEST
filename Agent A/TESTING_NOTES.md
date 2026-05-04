# Agent A — Testing Notes

Catatan hasil testing tanggal 2026-04-28. Disimpan untuk referensi perbaikan & dokumentasi behavior nyata.

---

## 1. Hasil Test (3 skenario, semua PASS)

| #  | Skenario             | Confidence | Iterations | Catatan                                                  |
| -- | -------------------- | ---------- | ---------- | -------------------------------------------------------- |
| 1  | revise-loop (T=0.99) | 0.60       | 2 (max)    | Loop `critic ↔ revise` jalan, hit MAX_ITERATIONS guard.  |
| 2  | custom (Bahasa ID)   | 0.98       | 1          | Lolos threshold langsung; output mengikuti bahasa input. |
| 3  | edge-empty           | 0.95       | 2          | Tidak crash; **tapi LLM hallucinate topik** (lihat #2).  |

---

## 2. Issue: Empty topic menyebabkan halusinasi topik

**Gejala.** Saat `topic=""` dipassed ke `run_once`, planner fallback mengisi `sub_questions = [""]`. Researcher menerima sub-question kosong, lalu LLM **memilih topik sendiri** (dalam test ini muncul "declining cost of solar energy"). Critic + reporter tetap jalan dan menghasilkan laporan yang terdengar wajar — padahal user tidak meminta apa-apa.

**Risiko.** Production bisa generate konten yang tidak diminta. Tagihan token terbuang. Tracing Langfuse mengandung run yang menyesatkan.

**Rekomendasi fix (urut dari paling sederhana):**
1. Validasi awal di `run_once`: `if not topic.strip(): raise ValueError("topic is required")`.
2. Tambah node `validate` sebelum `plan`; bila topic kosong, set `final_report = "Topic required"` dan langsung edge ke END.
3. Per `planner_node`: bila parsing gagal **dan** topic kosong, return state dengan flag error agar conditional edge bisa skip ke END.

---

## 3. Issue: Langfuse span export timeout

**Gejala.** Setiap run muncul:
```
Failed to export span batch ... HTTPSConnectionPool(host='dev.elit-dev.myelitest.com', ... read timeout=~0.1s)
```

**Diagnosa.** Read timeout sangat rendah (~60–270 ms) menunjukkan server `dev.elit-dev.myelitest.com` lambat / tidak konsisten merespon endpoint OTLP Langfuse. Bukan masalah agent — eksekusi graph **tetap selesai** dan tidak terpengaruh.

**Yang bisa dicoba:**
- Naikkan timeout exporter via env var:
  - `OTEL_EXPORTER_OTLP_TIMEOUT=10000` (ms)
  - atau `LANGFUSE_FLUSH_INTERVAL` & `LANGFUSE_HTTPX_TIMEOUT` (cek versi SDK 4.0.4).
- Test dengan `LANGFUSE_HOST=https://cloud.langfuse.com` untuk konfirmasi: kalau cloud OK → masalah di self-hosted dev.
- Verifikasi di dashboard Langfuse: run `agent-a-research-report` apakah muncul (run-level metadata kemungkinan masih masuk meski span batch drop).

---

## 4. Behavior yang sudah terverifikasi PASTI bekerja

- ✅ Conditional edge `should_revise` dual-path: confidence cukup → report; iterations habis → report.
- ✅ Fan-out researcher: `len(findings) == len(sub_questions)` di setiap run.
- ✅ `_extract_json` parse output critic JSON dengan/atau tanpa ` ```json ` fence.
- ✅ Multi-bahasa (Inggris & Indonesia) tanpa konfigurasi tambahan.
- ✅ Loop `critic → revise → critic` dijaga oleh `MAX_ITERATIONS` (tidak ada infinite loop).
