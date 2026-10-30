import json
import os
import re
import time
import uuid
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from memory import select_relevant_memory
from tools import TOOLS_SCHEMA, execute_tool

from privacy import contains_secret, redact

load_dotenv(override=True)                       # .env always wins over Windows variables
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
MAX_STEPS = 5                                    # max LLM calls per question (no infinite loops)
HISTORY_TURNS = 4                                # last 4 messages = short-term memory
MAX_RETRIES = 3                                  # retries for rate limits / network errors
TRACE_FILE = Path(__file__).parent / "data" / "traces.jsonl"

# Output guard: the model sometimes slips Chinese/Japanese/Korean/Arabic characters into
# Hindi/Gujarati/English answers. Code detects this and forces one rewrite.
STRAY_SCRIPT_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af\u0600-\u06ff]")
REWRITE_PROMPT = ("[Automatic check] Your previous answer contained characters from a different "
                  "script (Chinese, Japanese, Korean or Arabic). Rewrite the same answer in the "
                  "student's own language using ONLY that language's script. Keep all facts, "
                  "numbers and email addresses unchanged.")

_client = None


def get_client():
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise RuntimeError("GROQ_API_KEY is missing in .env")
        _client = Groq(api_key=key)
    return _client


SYSTEM_PROMPT = """You are the Student Support Agent for a PGDM institute. You help students with fees, scholarships, course/programme changes, institute policies and support requests.

DECISION RULES
1. Greetings, thanks or general chat -> answer directly. Do NOT call any tool.
2. The student's OWN data (fee status, balance, due date, scholarship status) -> ALWAYS call the matching tool. Never guess or invent numbers.
3. Rules / policy questions ("can I...", "what is the rule...", "how do I...") -> call search_policy and answer ONLY from the returned chunks. Mention the policy section you used.
4. If search_policy returns no_match, or the chunks do not actually answer the question, say clearly that the student handbook does not cover this, and offer to raise a support ticket. Never answer from general knowledge.
5. If the student states a USEFUL LONG-TERM fact about themselves (their programme, or how they like answers), call save_memory. Never save OTPs, passwords, card numbers, or temporary feelings/situations. If asked to remember such things, politely say you cannot store them.
6. Use the "Remembered facts" below when they answer the question (e.g. "which programme am I in?") - no tool is needed then. Always follow remembered preferences.
7. If a tool returns status "error" or "missing_data", explain the problem simply and offer to raise a support ticket. Never make up the missing data.
8. Call create_support_ticket only when the student reports a SPECIFIC problem, or agrees to your offer for a specific problem already discussed in the conversation. If the student just says "raise a ticket" without saying what the problem is, ASK them to describe the issue first. Never invent the issue description.
9. Questions may need more than one tool (e.g. fee status + late fee rule) - call all that are needed, then combine.

SCOPE
10. You ONLY handle student-support topics: fees, payments, scholarships, courses/electives, programme, attendance, exams, personal record details, institute policies and support tickets.
    For anything else (coding help, general knowledge, homework, news, jokes, other websites) politely say this is outside what you can help with, and do NOT provide the answer, code or facts - not even partially. Then mention what you can help with.

LANGUAGE
11. Reply in the same language AND script the student used (English, Hindi, Gujarati, Hinglish, etc.). Use only that language's script - never mix in words or characters from other scripts (for example never output Chinese, Japanese, Korean or Arabic characters in a Gujarati, Hindi or English answer). Keep names, IDs, amounts and email addresses as they are.
12. Tool inputs (such as search_policy queries) must always be written in ENGLISH, even when the student writes in another language.

STYLE
- Be clear, friendly and concise. Use Rs and Indian number format for money (e.g. Rs 1,00,000).
- Do not show raw JSON or internal tool names to the student.
- Write ticket IDs exactly as the tool returns them."""


# ---------------------------------------------------------------- context
def build_context(question, student_id, history):
    """CONTEXT SELECTION: only what this question needs (never the whole handbook)."""
    memory_items = select_relevant_memory(student_id, question)
    facts = "\n".join(f"- {m['fact']}" for m in memory_items) or "- none"
    session_info = (f"Logged-in student ID: {student_id}\n"
                    f"Today's date: {date.today().isoformat()}\n"
                    f"Remembered facts about this student:\n{facts}")
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": session_info}]
    for m in (history or [])[-HISTORY_TURNS:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": question})
    return messages, memory_items


# ---------------------------------------------------------------- LLM call
def call_llm(messages):
    """Call Groq with tools. Retries on rate-limit / network errors with backoff."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return get_client().chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS_SCHEMA,
                tool_choice="auto", temperature=0, max_tokens=1500)
        except Exception as e:                      # RateLimitError, APIConnectionError, ...
            last_error = e
            name = type(e).__name__
            if "RateLimit" in name or "Connection" in name or "Timeout" in name or "InternalServer" in name:
                time.sleep(2 ** attempt * 2)        # 2s, 4s, 8s
                continue
            raise
    raise last_error


# ---------------------------------------------------------------- agent loop
def run_agent(question, student_id, history=None, save_trace=True):
    """Answer one question. Returns a trace dict (answer + everything that happened)."""
    start = time.perf_counter()
    raw = (question or "").strip()
    question = redact(raw)                                   # secrets never reach the LLM, memory or trace
    history = [{**m, "content": redact(m.get("content"))} for m in (history or [])]
    trace = {
        "trace_id": "TR-" + uuid.uuid4().hex[:8].upper(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "student_id": student_id, "model": MODEL, "question": question,
        "decision": "", "tools": [], "evidence": {"policy_chunks": [], "memory": []},
        "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
        "answer": "", "status": "ok",
        "sensitive_redacted": contains_secret(raw),
    }
    if not question:
        trace.update(answer="Please type a question.", decision="empty_input")
        return _finish(trace, start, save_trace)

    messages, memory_items = build_context(question, student_id, history)
    trace["context_memory"] = [m["fact"] for m in memory_items]   # what memory was SENT

    for step in range(1, MAX_STEPS + 1):
        try:
            resp = call_llm(messages)
        except Exception as e:
            trace.update(status="llm_error", error=f"{type(e).__name__}: {e}",
                         answer="Sorry, the AI service is not responding right now. Please try again in a minute.")
            break

        trace["llm_calls"] += 1
        if resp.usage:
            trace["input_tokens"] += resp.usage.prompt_tokens or 0
            trace["output_tokens"] += resp.usage.completion_tokens or 0
        msg = resp.choices[0].message

        # ---- No tool call -> this is the final answer
        if not msg.tool_calls:
            answer = (msg.content or "").strip() or \
                "Sorry, I could not generate an answer. Please rephrase your question."
            # OUTPUT GUARD: stray foreign-script characters -> one rewrite, else strip them
            if STRAY_SCRIPT_RE.search(answer):
                if not trace.get("language_guard") and step < MAX_STEPS:
                    trace["language_guard"] = "rewrite_requested"
                    messages.append({"role": "assistant", "content": answer})
                    messages.append({"role": "user", "content": REWRITE_PROMPT})
                    continue
                answer = re.sub(r" {2,}", " ", STRAY_SCRIPT_RE.sub("", answer))
                trace["language_guard"] = "stripped"
            elif trace.get("language_guard") == "rewrite_requested":
                trace["language_guard"] = "rewritten_ok"
            trace["answer"] = answer
            break

        # ---- Tool call(s): run them and give results back to the LLM
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments or "{}"}}
                                        for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}") or {}
            except json.JSONDecodeError:
                args = {}
            t0 = time.perf_counter()
            result = execute_tool(tc.function.name, args, student_id)
            trace["tools"].append({
                "step": step, "tool": tc.function.name, "args": args,
                "status": result.get("status"),
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "result": _short(result)})
            for c in result.get("chunks", []):
                trace["evidence"]["policy_chunks"].append({"id": c["id"], "score": c["score"]})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False)})
    else:
        trace.update(status="max_steps",
                     answer="Sorry, I could not complete this request. Please try rephrasing it.")

    trace["evidence"]["memory"] = _memory_used(memory_items, trace["answer"])
    return _finish(trace, start, save_trace)


# ---------------------------------------------------------------- helpers
def _short(result):
    """Keep traces readable: replace long policy text with chunk ids."""
    r = dict(result)
    if "chunks" in r:
        r["chunks"] = [c["id"] for c in r["chunks"]]
    return r


def _memory_used(memory_items, answer):
    """Memory evidence = sent memory items whose key words appear in the answer."""
    used, ans = [], (answer or "").lower()
    for m in memory_items:
        words = [w for w in m["fact"].lower().replace(":", " ").split() if len(w) > 3]
        if m["category"] == "preference" or any(w in ans for w in words):
            used.append({"id": m["id"], "fact": m["fact"]})
    return used


def _decision(trace):
    names = [t["tool"] for t in trace["tools"]]
    if trace["decision"]:
        return trace["decision"]
    if not names:
        return "answered_from_memory" if trace["evidence"]["memory"] and trace["context_memory"] \
            and any(m["fact"] for m in trace["evidence"]["memory"]) else "answered_directly"
    if names == ["search_policy"]:
        return "retrieved_policy"
    return "used_tools"


def _finish(trace, start, save_trace):
    trace["total_tokens"] = trace["input_tokens"] + trace["output_tokens"]
    trace["latency_s"] = round(time.perf_counter() - start, 2)
    trace["tools_used"] = [t["tool"] for t in trace["tools"]]
    trace["decision"] = _decision(trace)
    if save_trace:
        TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with TRACE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")
    return trace


# ---------------------------------------------------------------- terminal chat
if __name__ == "__main__":
    sid = (input("Student ID [S101]: ").strip() or "S101").upper()
    history = []
    print(f"Chatting as {sid} using {MODEL}. Type 'exit' to quit, 'new' for a new session.\n")
    while True:
        q = input("You: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if q.lower() == "new":
            history = []
            print("-- new session (chat history cleared, long-term memory kept) --\n")
            continue
        tr = run_agent(q, sid, history)
        print(f"\nAgent: {tr['answer']}\n")
        print(f"  [decision={tr['decision']} | tools={tr['tools_used']} | "
              f"chunks={[c['id'] for c in tr['evidence']['policy_chunks']]} | "
              f"memory={[m['fact'] for m in tr['evidence']['memory']]} | "
              f"tokens in/out={tr['input_tokens']}/{tr['output_tokens']} | {tr['latency_s']}s]\n")
        history += [{"role": "user", "content": q}, {"role": "assistant", "content": tr["answer"]}]
