# Agent B — Testing Notes

Catatan hasil testing tanggal 2026-04-28. Disimpan untuk referensi perbaikan & dokumentasi behavior nyata.

---

## 1. Hasil Test (4 skenario, semua PASS)

| #  | Skenario              | Intent    | Priority | QA score | Retries | QA passed |
| -- | --------------------- | --------- | -------- | -------- | ------- | --------- |
| 1  | billing (double chg)  | billing   | high     | 0.95     | 0       | ✅         |
| 2  | technical (crash)     | technical | high     | 0.95     | 0       | ✅         |
| 3  | general (op hours)    | general   | low      | 1.00     | **1**   | ✅         |
| 4  | qa-revise (T=0.99)    | technical | high     | 1.00     | **2**   | ✅         |

---

## 2. Behavior yang sudah terverifikasi PASTI bekerja

- ✅ Conditional router `route_by_intent` mengarahkan ke 3 cabang spesialis dengan benar.
- ✅ Conditional `qa_decision` dual-path: `qa_passed=True` → finalize; `retries >= MAX_RETRIES` → finalize.
- ✅ Loop `qa → revise → qa` dijaga oleh `MAX_RETRIES` (tidak ada infinite loop).
- ✅ `_extract_json` parse output classifier & QA dengan fallback aman.
- ✅ Header metadata `[Intent: ... | Priority: ... | Sentiment: ... | QA score: ...]` muncul konsisten.
- ✅ Sentiment & priority detection sesuai konteks pesan.

---

## 3. Issue: Double salutation di finalizer

**Gejala.** Final response sering mengandung greeting 2×, contoh:

```
[Intent: billing | Priority: high | ...]

Hi Andi,                       <-- dari finalizer prepend

Of course. Here is a professional and warm reply you can use.

***

**Subject: Regarding Your Duplicate Charge Inquiry [Ticket #72519]**

Hi Andi,                       <-- dari LLM body
...
```

**Akar masalah.** Logic di `finalizer_node`:
```python
if not body.lower().startswith(("hi ", "hello ", "dear ")):
    body = f"Hi {salutation_name},\n\n{body}"
```
hanya cek **prefix string**. Bila spesialis mengembalikan preamble ("Of course. Here is …") atau subject line ("**Subject: …**"), prefix check gagal → finalizer prepend "Hi X," — sementara body LLM **juga** sudah memuat "Hi X,".

**Rekomendasi fix:**
1. **Perketat prompt spesialis**: tambahkan instruksi `"Output ONLY the reply text. Do NOT include 'Subject:', preamble like 'Here is a reply', or any meta commentary."` di tiap `_specialist_prompt`.
2. **Detect greeting di awal body lebih agresif**: scan 200 char pertama body untuk pattern greeting (regex `(?im)^(hi|hello|dear)\s+\w+,`); jika ditemukan, skip prepend.
3. **Atau hapus auto-prepend**: percayakan greeting sepenuhnya ke LLM, finalizer hanya tambahkan header metadata.

---

## 4. Issue: LLM menambah preamble / subject line yang tidak diminta

**Gejala.** Spesialis kadang menjawab dengan format:
```
Of course. Here is a professional and warm reply you can use.

***

**Subject: Regarding Your Login Issue - We're Here to Help**

Hi Citra,
...
```

Padahal customer akan menerima ini sebagai **balasan langsung**, bukan template untuk agen support.

**Rekomendasi fix.** Update `_specialist_prompt` dengan instruksi ketat:
```
Output rules:
- Reply directly to the customer in second person.
- Do NOT include "Subject:" lines.
- Do NOT include preamble like "Here is a reply" / "Of course".
- Do NOT include placeholders like "[Your Name]" or "[Link]".
```

---

## 5. Catatan: QA reviewer cukup ketat (fitur, bukan bug)

Test 3 (general intent, threshold default 0.8): meski pertanyaan trivial (jam operasional), QA tetap minta 1× revise sebelum lolos dengan score 1.00. Ini menunjukkan QA reviewer **bekerja agresif** untuk menambah polish.

Trade-off: kalau biaya token jadi concern, naikkan ambang ke 0.7 atau perlonggar kriteria di prompt QA.

---

## 6. Issue Langfuse span export timeout (sama dengan Agent A)

```
Failed to export span batch ... HTTPSConnectionPool(host='dev.elit-dev.myelitest.com', ... read timeout=~0.05–0.4s)
ValueError: Attempted to set connect timeout to -0.0005..., but the timeout cannot be set to a value less than or equal to 0.
```

`ValueError` baru di Agent B berasal dari OpenTelemetry exporter saat deadline batch sudah habis (`deadline_sec - time()` menghasilkan angka negatif). **Tidak mempengaruhi eksekusi agent** — cuma noise di stderr.

Workaround sama dengan Agent A:
- Set `OTEL_EXPORTER_OTLP_TIMEOUT=10000` (ms) di `.env`.
- Atau test dengan `LANGFUSE_HOST=https://cloud.langfuse.com` untuk konfirmasi server-side issue.
