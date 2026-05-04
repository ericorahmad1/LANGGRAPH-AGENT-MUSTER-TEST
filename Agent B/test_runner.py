"""
Test runner for Agent B (Customer Support Triage Agent).

Skenario:
  1. billing       -> pesan double charge => intent=billing, priority=high.
  2. technical     -> pesan crash dashboard => intent=technical.
  3. general       -> pertanyaan umum (jam operasional) => intent=general.
  4. qa-revise     -> threshold dipaksa 0.99 supaya QA reviser loop terbukti jalan.
"""

from __future__ import annotations

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import support_agent as sa


def banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def summarize(label: str, result: dict) -> None:
    banner(f"RESULT — {label}")
    print(f"intent     : {result['intent']}")
    print(f"sentiment  : {result['sentiment']}")
    print(f"priority   : {result['priority']}")
    print(f"qa_score   : {result['qa_score']:.2f}")
    print(f"qa_passed  : {result['qa_passed']}")
    print(f"retries    : {result['retries']}")
    print(f"final_response length: {len(result['final_response'])} chars")
    preview = result["final_response"][:600].rstrip()
    print(f"\nfinal_response preview:\n{preview}\n...")


def test_billing() -> None:
    banner("TEST 1 — Billing intent (double charge, high priority)")
    msg = (
        "Hi team, I was charged twice for my Pro subscription on April 25 and "
        "the duplicate charge has not been refunded. I have the receipts. "
        "This is the second time it happened and I'm pretty frustrated."
    )
    result = sa.run_once(msg, customer_name="Andi")
    summarize("billing", result)
    assert result["intent"] == "billing", f"Expected intent=billing, got {result['intent']}"
    assert result["final_response"], "final_response must be non-empty"
    assert "billing" in result["final_response"].lower() or "Intent: billing" in result["final_response"]
    print("[PASS] billing intent test")


def test_technical() -> None:
    banner("TEST 2 — Technical intent (dashboard crash)")
    msg = (
        "The dashboard crashes every time I open the analytics tab on Chrome 124. "
        "I get a blank screen and a 500 error in the console. Started yesterday."
    )
    result = sa.run_once(msg, customer_name="Sari")
    summarize("technical", result)
    assert result["intent"] == "technical", f"Expected intent=technical, got {result['intent']}"
    assert result["final_response"], "final_response must be non-empty"
    print("[PASS] technical intent test")


def test_general() -> None:
    banner("TEST 3 — General intent (operating hours)")
    msg = "Hi, what are your customer support operating hours on weekends?"
    result = sa.run_once(msg, customer_name="Budi")
    summarize("general", result)
    assert result["intent"] == "general", f"Expected intent=general, got {result['intent']}"
    assert result["final_response"], "final_response must be non-empty"
    print("[PASS] general intent test")


def test_qa_revise_loop() -> None:
    banner("TEST 4 — Force QA revise loop (threshold = 0.99)")
    original_threshold = sa.QA_PASS_THRESHOLD
    original_max = sa.MAX_RETRIES
    sa.QA_PASS_THRESHOLD = 0.99
    sa.MAX_RETRIES = 2
    try:
        msg = (
            "I cannot login to my account, it says 'invalid credentials' "
            "but I'm sure the password is correct. I tried reset 3 times. Help."
        )
        result = sa.run_once(msg, customer_name="Citra")
        summarize("qa-revise-loop", result)
        # Either QA finally passed at >=0.99 OR we hit MAX_RETRIES guard
        if not result["qa_passed"]:
            assert result["retries"] == sa.MAX_RETRIES, (
                f"QA didn't pass; retries should equal MAX_RETRIES, "
                f"got retries={result['retries']}"
            )
        assert result["final_response"], "final_response must still be produced"
        print("[PASS] qa-revise-loop test")
    finally:
        sa.QA_PASS_THRESHOLD = original_threshold
        sa.MAX_RETRIES = original_max


TESTS = {
    "1": ("billing", test_billing),
    "2": ("technical", test_technical),
    "3": ("general", test_general),
    "4": ("qa-revise-loop", test_qa_revise_loop),
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
