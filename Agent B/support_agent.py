"""
Agent B — Customer Support Triage Agent
=======================================

Complex LangGraph agent with:
  - Classifier node (intent + sentiment + priority extraction)
  - Conditional router -> three specialist branches:
      * billing_specialist
      * technical_specialist
      * general_specialist
  - QA reviewer node (policy / tone / accuracy check, structured score)
  - Conditional edge: if QA fails AND retries < max -> revise
  - Reviser node (rewrites response using QA feedback, loops to QA)
  - Finalizer node (formats customer-ready reply with metadata)

Tracing via Langfuse callbacks (mirrors langgraph-tracer/src/graph_app.py).
"""

from __future__ import annotations
import logging
logging.basicConfig(level=logging.DEBUG)
import inspect
import json
import os
import re
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langfuse import Langfuse

try:
    from langfuse.langchain import CallbackHandler
except ImportError:
    from langfuse.callback import CallbackHandler

from langgraph.graph import END, StateGraph


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class SupportState(TypedDict):
    user_message: str
    customer_name: str
    intent: str               # billing | technical | general
    sentiment: str            # positive | neutral | negative
    priority: str             # low | medium | high
    draft_response: str
    qa_feedback: str
    qa_score: float           # 0.0 - 1.0
    qa_passed: bool
    retries: int
    final_response: str


QA_PASS_THRESHOLD = 0.8
MAX_RETRIES = 2
VALID_INTENTS = {"billing", "technical", "general"}


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
def build_llm(temperature: float = 0.2) -> ChatGoogleGenerativeAI:
    model_name = os.getenv("LANGGRAPH_MODEL", "gemini-2.5-pro")
    return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)


def build_langfuse_handler() -> tuple[CallbackHandler, Langfuse]:
    """Return (callback_handler, langfuse_client). Caller MUST flush the client
    after work is done to avoid losing spans on multi-run scripts."""
    host = os.getenv("LANGFUSE_HOST", os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"))
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")

    if not public_key or not secret_key:
        raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required.")

    client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)

    params = inspect.signature(CallbackHandler.__init__).parameters
    kwargs = {}
    if "public_key" in params:
        kwargs["public_key"] = public_key
    if "secret_key" in params:
        kwargs["secret_key"] = secret_key
    if "host" in params:
        kwargs["host"] = host
    return CallbackHandler(**kwargs), client


def _extract_json(raw: str) -> dict | list | None:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return None
    return None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def classifier_node(state: SupportState) -> SupportState:
    llm = build_llm(temperature=0.0)
    prompt = (
        "Classify the customer message. Return STRICT JSON with keys:\n"
        '  "intent": one of ["billing", "technical", "general"],\n'
        '  "sentiment": one of ["positive", "neutral", "negative"],\n'
        '  "priority": one of ["low", "medium", "high"].\n\n'
        "Rules:\n"
        " - billing: invoices, payments, refunds, subscriptions, pricing.\n"
        " - technical: bugs, errors, outages, integrations, performance.\n"
        " - general: everything else (info requests, feedback, account help).\n"
        " - priority=high if customer reports outage, data loss, or strong frustration.\n\n"
        f"Customer message:\n{state['user_message']}"
    )
    response = llm.invoke(prompt)
    parsed = _extract_json(response.content) or {}
    intent = str(parsed.get("intent", "general")).lower() if isinstance(parsed, dict) else "general"
    if intent not in VALID_INTENTS:
        intent = "general"
    sentiment = str(parsed.get("sentiment", "neutral")).lower() if isinstance(parsed, dict) else "neutral"
    priority = str(parsed.get("priority", "medium")).lower() if isinstance(parsed, dict) else "medium"
    return {
        **state,
        "intent": intent,
        "sentiment": sentiment,
        "priority": priority,
        "retries": 0,
    }


def _specialist_prompt(role: str, guardrails: str, state: SupportState) -> str:
    return (
        f"You are a {role}. Reply to the customer in a warm, professional tone. "
        "Acknowledge the issue, give concrete next steps, and never invent policies "
        "or commitments you cannot verify.\n"
        f"{guardrails}\n\n"
        f"Customer name: {state['customer_name']}\n"
        f"Detected sentiment: {state['sentiment']} | Priority: {state['priority']}\n"
        f"Customer message:\n{state['user_message']}"
    )


def billing_node(state: SupportState) -> SupportState:
    llm = build_llm(temperature=0.3)
    guardrails = (
        "Guardrails: Do NOT promise refunds without case review. Cite that "
        "billing tickets are resolved within 2 business days. Offer to "
        "escalate to the billing team if the customer has supporting documents."
    )
    response = llm.invoke(_specialist_prompt("senior billing specialist", guardrails, state))
    return {**state, "draft_response": response.content.strip()}


def technical_node(state: SupportState) -> SupportState:
    llm = build_llm(temperature=0.3)
    guardrails = (
        "Guardrails: Ask for environment details (OS, version, reproduction steps) "
        "if missing. Provide a numbered troubleshooting checklist before "
        "escalating to engineering. Do not guarantee fix ETAs."
    )
    response = llm.invoke(_specialist_prompt("senior technical support engineer", guardrails, state))
    return {**state, "draft_response": response.content.strip()}


def general_node(state: SupportState) -> SupportState:
    llm = build_llm(temperature=0.4)
    guardrails = (
        "Guardrails: Stay concise. If the question is ambiguous, ask one clarifying "
        "question. Point to the help center for self-service topics."
    )
    response = llm.invoke(_specialist_prompt("customer success representative", guardrails, state))
    return {**state, "draft_response": response.content.strip()}


def qa_node(state: SupportState) -> SupportState:
    llm = build_llm(temperature=0.0)
    prompt = (
        "You are a QA reviewer for customer support replies. Evaluate the draft "
        "below against these criteria: relevance to issue, factual safety, tone "
        "(empathetic and professional), policy compliance, and clarity.\n"
        "Return STRICT JSON with keys:\n"
        '  "score": float between 0.0 and 1.0,\n'
        '  "passed": boolean,\n'
        '  "feedback": short bullet list (string) describing concrete fixes.\n\n'
        f"Intent: {state['intent']} | Sentiment: {state['sentiment']} | Priority: {state['priority']}\n"
        f"Customer message:\n{state['user_message']}\n\n"
        f"Draft response:\n{state['draft_response']}"
    )
    response = llm.invoke(prompt)
    parsed = _extract_json(response.content) or {}
    score = float(parsed.get("score", 0.5)) if isinstance(parsed, dict) else 0.5
    score = max(0.0, min(1.0, score))
    passed = bool(parsed.get("passed", score >= QA_PASS_THRESHOLD)) if isinstance(parsed, dict) else score >= QA_PASS_THRESHOLD
    feedback = parsed.get("feedback", "No QA feedback parsed.") if isinstance(parsed, dict) else response.content
    return {
        **state,
        "qa_score": score,
        "qa_passed": passed and score >= QA_PASS_THRESHOLD,
        "qa_feedback": feedback,
    }


def reviser_node(state: SupportState) -> SupportState:
    llm = build_llm(temperature=0.2)
    prompt = (
        "Rewrite the draft using the QA feedback. Keep the same intent and "
        "guardrails; address every weakness. Output ONLY the revised reply.\n\n"
        f"Customer message:\n{state['user_message']}\n\n"
        f"Previous draft:\n{state['draft_response']}\n\n"
        f"QA feedback:\n{state['qa_feedback']}"
    )
    response = llm.invoke(prompt)
    return {
        **state,
        "draft_response": response.content.strip(),
        "retries": state["retries"] + 1,
    }


def finalizer_node(state: SupportState) -> SupportState:
    header = (
        f"[Intent: {state['intent']} | Priority: {state['priority']} | "
        f"Sentiment: {state['sentiment']} | QA score: {state['qa_score']:.2f}]"
    )
    salutation_name = state["customer_name"] or "there"
    body = state["draft_response"]
    if not body.lower().startswith(("hi ", "hello ", "dear ")):
        body = f"Hi {salutation_name},\n\n{body}"
    final = f"{header}\n\n{body}"
    return {**state, "final_response": final}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------
def route_by_intent(state: SupportState) -> str:
    return state["intent"] if state["intent"] in VALID_INTENTS else "general"


def qa_decision(state: SupportState) -> str:
    if state["qa_passed"]:
        return "finalize"
    if state["retries"] >= MAX_RETRIES:
        return "finalize"
    return "revise"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def build_graph():
    workflow = StateGraph(SupportState)
    workflow.add_node("classify", classifier_node)
    workflow.add_node("billing", billing_node)
    workflow.add_node("technical", technical_node)
    workflow.add_node("general", general_node)
    workflow.add_node("qa", qa_node)
    workflow.add_node("revise", reviser_node)
    workflow.add_node("finalize", finalizer_node)

    workflow.set_entry_point("classify")
    workflow.add_conditional_edges(
        "classify",
        route_by_intent,
        {"billing": "billing", "technical": "technical", "general": "general"},
    )
    workflow.add_edge("billing", "qa")
    workflow.add_edge("technical", "qa")
    workflow.add_edge("general", "qa")
    workflow.add_conditional_edges(
        "qa",
        qa_decision,
        {"revise": "revise", "finalize": "finalize"},
    )
    workflow.add_edge("revise", "qa")
    workflow.add_edge("finalize", END)
    return workflow.compile()


def run_once(user_message: str, customer_name: str = "") -> SupportState:
    graph = build_graph()
    handler, client = build_langfuse_handler()
    initial: SupportState = {
        "user_message": user_message,
        "customer_name": customer_name,
        "intent": "",
        "sentiment": "",
        "priority": "",
        "draft_response": "",
        "qa_feedback": "",
        "qa_score": 0.0,
        "qa_passed": False,
        "retries": 0,
        "final_response": "",
    }
    try:
        return graph.invoke(
            initial,
            config={
                "run_name": "agent-b-support-triage",
                "tags": ["langgraph", "agent-b", "support"],
                "callbacks": [handler],
            },
        )
    finally:
        try:
            client.flush()
        except Exception as e:
            logging.getLogger("agent_b").warning("Langfuse flush failed: %s", e)


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")

    sample_message = (
        "Hi team, I was charged twice for my Pro subscription on April 25 and "
        "the duplicate charge has not been refunded. I have the receipts. "
        "This is the second time it happened and I'm pretty frustrated."
    )
    result = run_once(sample_message, customer_name="Andi")

    print("\n=== Classification ===")
    print(f" intent={result['intent']} | sentiment={result['sentiment']} | "
          f"priority={result['priority']}")
    print(f"\n=== QA: score={result['qa_score']:.2f} | passed={result['qa_passed']} "
          f"| retries={result['retries']} ===")
    print(f"\n=== Final Response ===\n\n{result['final_response']}")
