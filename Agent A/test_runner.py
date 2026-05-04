"""
Test runner for Agent A.
Three scenarios:
  1. revise-loop  -> threshold dipaksa tinggi supaya critic loop revise pasti jalan.
  2. custom       -> topik domain spesifik.
  3. edge-empty   -> topic string kosong (uji fallback planner).
"""

from __future__ import annotations

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import research_agent as ra


def banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def summarize(label: str, result: dict) -> None:
    banner(f"RESULT — {label}")
    print(f"sub_questions ({len(result['sub_questions'])}):")
    for q in result["sub_questions"]:
        print(f"  - {q}")
    print(f"\nconfidence: {result['confidence']:.2f}")
    print(f"iterations: {result['iterations']}")
    print(f"final_report length: {len(result['final_report'])} chars")
    preview = result["final_report"][:500].rstrip()
    print(f"\nreport preview:\n{preview}\n...")


def test_revise_loop() -> None:
    banner("TEST 1 — Force revise loop (threshold = 0.99)")
    original_threshold = ra.CONFIDENCE_THRESHOLD
    original_max = ra.MAX_ITERATIONS
    ra.CONFIDENCE_THRESHOLD = 0.99   # hampir mustahil dicapai sekali jalan
    ra.MAX_ITERATIONS = 2            # max 2 putaran critic
    try:
        result = ra.run_once(
            "Compare event-driven microservices vs orchestrated microservices "
            "for high-throughput payment systems."
        )
        summarize("revise-loop", result)
        assert result["iterations"] >= 1, "Critic should have run at least once."
        if result["confidence"] < 0.99:
            assert result["iterations"] == ra.MAX_ITERATIONS, (
                "Loop should have hit MAX_ITERATIONS when confidence stays below threshold."
            )
        print("[PASS] revise-loop test")
    finally:
        ra.CONFIDENCE_THRESHOLD = original_threshold
        ra.MAX_ITERATIONS = original_max


def test_custom_topic() -> None:
    banner("TEST 2 — Custom domain topic")
    result = ra.run_once(
        "Best practices untuk observability stack (logs, metrics, traces) "
        "pada arsitektur Kubernetes multi-tenant."
    )
    summarize("custom-topic", result)
    assert result["final_report"], "Final report must be non-empty."
    assert len(result["sub_questions"]) >= 1
    print("[PASS] custom-topic test")


def test_edge_empty() -> None:
    banner("TEST 3 — Edge case: empty topic")
    result = ra.run_once("")
    summarize("edge-empty", result)
    assert result["sub_questions"], "Planner fallback must produce at least one sub-question."
    assert result["final_report"], "Reporter must still emit a report."
    print("[PASS] edge-empty test")


TESTS = {
    "1": ("revise-loop", test_revise_loop),
    "2": ("custom", test_custom_topic),
    "3": ("edge-empty", test_edge_empty),
}


def main() -> None:
    selected = sys.argv[1:] or list(TESTS.keys())
    failures: list[str] = []
    for key in selected:
        if key not in TESTS:
            print(f"Unknown test id: {key}. Valid: {list(TESTS)}")
            continue
        name, fn = TESTS[key]
        try:
            fn()
        except AssertionError as e:
            print(f"[FAIL] {name}: {e}")
            failures.append(name)
        except Exception as e:
            print(f"[ERROR] {name}: {type(e).__name__}: {e}")
            failures.append(name)

    banner("SUMMARY")
    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
