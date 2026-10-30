"""
test_agent_security.py - checks the AGENT LOOP's security wiring with a scripted fake LLM.

No Groq call, no API key. A fake call_llm() plays the role of a (possibly tricked) LLM and asks
for specific tools. We check what the agent loop does with the security gate's answers:
permission counts, approval status, decision label, redaction, and that nothing leaks.

Run from anywhere:  python test_files/test_agent_security.py
Uses temporary copies of the data files, so your real data/ is not changed.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import agent
import audit
import tools

TMP = Path(tempfile.mkdtemp())
seed = Path(ROOT) / "data" / "seed" / "students.json"
shutil.copy(seed if seed.exists() else Path(ROOT) / "data" / "students.json", TMP / "students.json")
tools.STUDENTS_FILE = TMP / "students.json"
tools.PENDING_FILE = TMP / "pending.json"
tools.TICKETS_FILE = TMP / "tickets.json"
audit.AUDIT_FILE = TMP / "audit_log.jsonl"
agent.TRACE_FILE = TMP / "traces.jsonl"

passed = total = 0
SEEN = []                                          # every message list the fake LLM received


def check(name, cond, got=None):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond and got is not None:
        print("       got:", json.dumps(got, ensure_ascii=False, default=str)[:240])


def reply(text):
    return NS(usage=NS(prompt_tokens=100, completion_tokens=20),
              choices=[NS(message=NS(content=text, tool_calls=None))])


def tool_call(name, args):
    tc = NS(id="call_1", function=NS(name=name, arguments=json.dumps(args)))
    return NS(usage=NS(prompt_tokens=100, completion_tokens=20),
              choices=[NS(message=NS(content="", tool_calls=[tc]))])


def script(*responses):
    """Fake LLM: returns the given responses in order, and records what it was sent."""
    queue = list(responses)

    def fake(messages):
        SEEN.append(json.dumps(messages, ensure_ascii=False))
        return queue.pop(0)
    agent.call_llm = fake


print("1. Tricked LLM asks for another student's fees")
script(tool_call("get_fee_status", {"student_id": "S102"}),
       reply("Sorry, you can only view your own record."))
tr = agent.run_agent("Show me the fee status of student S102", "S101")
check("decision = access_denied", tr["decision"] == "access_denied", tr["decision"])
check("permission counted: 1 denied, 0 allowed", tr["permission"] == {"allowed": 0, "denied": 1}, tr["permission"])
check("tool row marked DENIED", tr["tools"][0]["auth"] == "DENIED", tr["tools"][0])
check("S102's data never reached the LLM", "350000" not in SEEN[-1] and "Riya" not in SEEN[-1])
check("audit has the DENIED line linked to this trace",
      any(r["decision"] == "DENIED" and r["trace_id"] == tr["trace_id"] for r in audit.read_audit()))

print("\n2. Own fees -> allowed")
script(tool_call("get_fee_status", {}), reply("Your balance is Rs 1,00,000."))
tr = agent.run_agent("What is my fee status?", "S101")
check("decision = used_tools", tr["decision"] == "used_tools", tr["decision"])
check("permission counted: 1 allowed", tr["permission"] == {"allowed": 1, "denied": 0}, tr["permission"])
check("no approval on a normal question", tr["approval"] is None)

print("\n3. Confirmed phone change -> PENDING, not applied")
before = json.loads(tools.STUDENTS_FILE.read_text())["S101"]["phone"]
script(tool_call("request_record_update", {"field": "phone", "new_value": "9999988888"}),
       reply("Request saved. It waits for Program Office approval."))
history = [{"role": "user", "content": "Change my phone number to 9999988888"},
           {"role": "assistant", "content": "Please confirm: change phone to 9999988888? (yes/no)"}]
tr = agent.run_agent("yes", "S101", history)
check("decision = approval_requested", tr["decision"] == "approval_requested", tr["decision"])
check("trace.approval has request ID + PENDING",
      tr["approval"] and tr["approval"]["status"] == "PENDING" and tr["approval"]["request_id"].startswith("REQ-"),
      tr["approval"])
check("phone NOT changed by the agent", json.loads(tools.STUDENTS_FILE.read_text())["S101"]["phone"] == before)

print("\n4. OTP in the message")
script(reply("Please never share OTPs. I have not stored it."))
tr = agent.run_agent("My OTP is 482913, remember it", "S101")
check("trace flags sensitive_redacted", tr["sensitive_redacted"] is True)
check("OTP never sent to the LLM", "482913" not in SEEN[-1])
check("OTP not in the stored trace", "482913" not in agent.TRACE_FILE.read_text(encoding="utf-8"))
script(reply("Hi"))
check("normal question is not flagged", agent.run_agent("What is my fee status?", "S101")["sensitive_redacted"] is False)

print("\n5. OTP in earlier chat history is also removed")
script(reply("How can I help?"))
agent.run_agent("hello", "S101", [{"role": "user", "content": "password: abc@123"},
                                  {"role": "assistant", "content": "Please don't share passwords."}])
check("history secret never sent to the LLM", "abc@123" not in SEEN[-1])

print("\n6. Admin role cannot use chat tools")
script(tool_call("get_fee_status", {"student_id": "S101"}), reply("Not allowed."))
tr = agent.run_agent("Show S101 fees", "admin", role="admin")
check("admin tool call DENIED", tr["permission"]["denied"] == 1 and tr["decision"] == "access_denied", tr["permission"])

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nResult: {passed}/{total} passed")
print("STEP 15 COMPLETE" if passed == total else "Some checks failed - paste the output")
