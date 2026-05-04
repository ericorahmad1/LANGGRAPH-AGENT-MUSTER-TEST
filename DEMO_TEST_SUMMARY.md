# Demo Test Summary

**Run date:** 2026-04-29
**Environment:** Windows 11 (venv per agent), Gemini via google-genai

## Result overview

| Agent | Tests | Status |
|---|---|---|
| Agent A — Research Agent | 3/3 | ALL PASSED |
| Agent B — Customer Support Triage | 4/4 | ALL PASSED |

## Agent A — Research Agent (`Agent A/test_runner.py`)

| # | Scenario | sub_questions | confidence | iterations | Result |
|---|---|---|---|---|---|
| 1 | revise-loop (threshold forced 0.99) | 3 | 0.85 | 2 | PASS |
| 2 | custom-topic (Kubernetes observability) | 4 | 1.00 | 1 | PASS |
| 3 | edge-empty (empty topic fallback) | 4 | 0.95 | 1 | PASS |

Detail: see `Agent A/test_result_demo.txt`.

## Agent B — Customer Support Triage (`Agent B/test_runner.py`)

| # | Scenario | intent | priority | qa_score | qa_passed | retries | Result |
|---|---|---|---|---|---|---|---|
| 1 | billing (double charge) | billing | high | 1.00 | True | 0 | PASS |
| 2 | technical (dashboard crash) | technical | high | 1.00 | True | 0 | PASS |
| 3 | general (operating hours) | general | low | 1.00 | True | 1 | PASS |
| 4 | qa-revise-loop (threshold forced 0.99) | technical | high | 1.00 | True | 0 | PASS |

Detail: see `Agent B/test_result_demo.txt`.

## How to reproduce

```
cd "Agent A" && ./env/Scripts/python.exe test_runner.py
cd "Agent B" && ./env/Scripts/python.exe test_runner.py
```
