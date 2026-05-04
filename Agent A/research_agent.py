"""
Agent A — Research & Report Agent
=================================

Complex LangGraph agent with:
  - Planner node (decomposes topic into sub-questions)
  - Researcher node (fan-out: investigates every sub-question in one pass)
  - Critic node (scores draft & emits structured feedback)
  - Conditional edge: if confidence < threshold AND iterations < max -> revise
  - Reviser node (rewrites findings using critic feedback, loops back to critic)
  - Reporter node (composes final markdown report)

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
from typing import List, TypedDict

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
class ResearchState(TypedDict):
    topic: str
    sub_questions: List[str]
    findings: List[dict]          # [{"question": str, "answer": str}]
    critique: str
    confidence: float             # 0.0 - 1.0
    iterations: int
    final_report: str


CONFIDENCE_THRESHOLD = 0.8
MAX_ITERATIONS = 2


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
    """Best-effort JSON extractor: tolerates ```json fences and prose."""
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
def planner_node(state: ResearchState) -> ResearchState:
    llm = build_llm(temperature=0.1)
    prompt = (
        "You are a senior research planner. Decompose the topic below into "
        "3-5 focused, non-overlapping sub-questions that together cover the "
        "topic exhaustively.\n"
        "Return ONLY a JSON array of strings.\n\n"
        f"Topic: {state['topic']}"
    )
    response = llm.invoke(prompt)
    parsed = _extract_json(response.content) or []
    sub_questions = [str(q) for q in parsed][:5] if isinstance(parsed, list) else []
    if not sub_questions:
        sub_questions = [state["topic"]]
    return {**state, "sub_questions": sub_questions, "iterations": 0}


def researcher_node(state: ResearchState) -> ResearchState:
    llm = build_llm(temperature=0.3)
    findings: List[dict] = []
    for question in state["sub_questions"]:
        prompt = (
            "You are a domain researcher. Answer the question below with "
            "concrete facts, mechanisms, and concise reasoning. 4-7 sentences.\n\n"
            f"Topic: {state['topic']}\n"
            f"Sub-question: {question}"
        )
        response = llm.invoke(prompt)
        findings.append({"question": question, "answer": response.content.strip()})
    return {**state, "findings": findings}


def critic_node(state: ResearchState) -> ResearchState:
    llm = build_llm(temperature=0.0)
    payload = "\n\n".join(
        f"Q: {f['question']}\nA: {f['answer']}" for f in state["findings"]
    )
    prompt = (
        "You are a strict research critic. Evaluate the Q&A set below for "
        "factual rigor, coverage of the topic, and absence of hallucinations.\n"
        "Return STRICT JSON with keys:\n"
        '  "confidence": float between 0.0 and 1.0,\n'
        '  "feedback": short actionable improvements (3-6 bullet lines as one string).\n\n'
        f"Topic: {state['topic']}\n\n"
        f"Findings:\n{payload}"
    )
    response = llm.invoke(prompt)
    parsed = _extract_json(response.content) or {}
    confidence = float(parsed.get("confidence", 0.5)) if isinstance(parsed, dict) else 0.5
    feedback = parsed.get("feedback", "No feedback parsed.") if isinstance(parsed, dict) else response.content
    return {
        **state,
        "confidence": max(0.0, min(1.0, confidence)),
        "critique": feedback,
        "iterations": state["iterations"] + 1,
    }


def reviser_node(state: ResearchState) -> ResearchState:
    llm = build_llm(temperature=0.2)
    revised: List[dict] = []
    for finding in state["findings"]:
        prompt = (
            "Revise the answer below using the critic feedback. Address every "
            "weakness; keep it factual and tight (4-7 sentences).\n\n"
            f"Topic: {state['topic']}\n"
            f"Sub-question: {finding['question']}\n"
            f"Previous answer: {finding['answer']}\n\n"
            f"Critic feedback:\n{state['critique']}"
        )
        response = llm.invoke(prompt)
        revised.append({"question": finding["question"], "answer": response.content.strip()})
    return {**state, "findings": revised}


def reporter_node(state: ResearchState) -> ResearchState:
    llm = build_llm(temperature=0.2)
    payload = "\n\n".join(
        f"### {f['question']}\n{f['answer']}" for f in state["findings"]
    )
    prompt = (
        "Compose a polished markdown research report. Structure:\n"
        "  # Title\n  ## Executive Summary (3-5 bullets)\n"
        "  ## Findings (one subsection per sub-question)\n"
        "  ## Conclusion\n\n"
        f"Topic: {state['topic']}\n\n"
        f"Source findings:\n{payload}"
    )
    response = llm.invoke(prompt)
    return {**state, "final_report": response.content}


# ---------------------------------------------------------------------------
# Conditional routing
# ---------------------------------------------------------------------------
def should_revise(state: ResearchState) -> str:
    if state["confidence"] >= CONFIDENCE_THRESHOLD:
        return "report"
    if state["iterations"] >= MAX_ITERATIONS:
        return "report"
    return "revise"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def build_graph():
    workflow = StateGraph(ResearchState)
    workflow.add_node("plan", planner_node)
    workflow.add_node("research", researcher_node)
    workflow.add_node("critic", critic_node)
    workflow.add_node("revise", reviser_node)
    workflow.add_node("report", reporter_node)

    workflow.set_entry_point("plan")
    workflow.add_edge("plan", "research")
    workflow.add_edge("research", "critic")
    workflow.add_conditional_edges(
        "critic",
        should_revise,
        {"revise": "revise", "report": "report"},
    )
    workflow.add_edge("revise", "critic")
    workflow.add_edge("report", END)
    return workflow.compile()


def run_once(topic: str) -> ResearchState:
    graph = build_graph()
    handler, client = build_langfuse_handler()
    initial: ResearchState = {
        "topic": topic,
        "sub_questions": [],
        "findings": [],
        "critique": "",
        "confidence": 0.0,
        "iterations": 0,
        "final_report": "",
    }
    try:
        return graph.invoke(
            initial,
            config={
                "run_name": "agent-a-research-report",
                "tags": ["langgraph", "agent-a", "research"],
                "callbacks": [handler],
            },
        )
    finally:
        try:
            client.flush()
        except Exception as e:
            logger_name = logging.getLogger("agent_a")
            logger_name.warning("Langfuse flush failed: %s", e)


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parent / ".env")

    sample_topic = (
        "How retrieval-augmented generation (RAG) compares to fine-tuning "
        "for enterprise customer-support assistants."
    )
    result = run_once(sample_topic)

    print("\n=== Sub-questions ===")
    for q in result["sub_questions"]:
        print(f" - {q}")
    print(f"\n=== Critic confidence: {result['confidence']:.2f} "
          f"after {result['iterations']} iteration(s) ===")
    print("\n=== Final Report ===\n")
    print(result["final_report"])
