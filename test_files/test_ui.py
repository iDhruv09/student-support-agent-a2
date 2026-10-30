"""
test_ui.py - checks the Streamlit screen WITHOUT calling Groq (no API key needed).

It replaces run_agent with a fake that returns a ready-made trace, then drives the
real app.py with Streamlit's AppTest and checks the screen behaves as designed.

Run from anywhere:  python test_files/test_ui.py
Needs data/users.json (run: python create_users.py).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # find agent.py, tools.py, memory.py ... in the project root
os.chdir(ROOT)             # so data/... and app.py paths work too

import agent
import theme
from auth import authenticate
from streamlit.testing.v1 import AppTest

passed = total = 0


def check(name, cond):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def fake_run_agent(question, student_id, history=None, save_trace=True):
    return {"trace_id": "TR-TEST", "student_id": student_id, "question": question, "status": "ok",
            "decision": "used_tools", "tools": [{"step": 1, "tool": "get_fee_status", "args": {},
            "status": "ok", "latency_ms": 0.4, "result": {}}], "tools_used": ["get_fee_status"],
            "evidence": {"policy_chunks": [{"id": "payment-portal-failure", "score": 0.41}], "memory": []},
            "context_memory": [], "llm_calls": 2, "input_tokens": 2400, "output_tokens": 150,
            "total_tokens": 2550, "latency_s": 1.2,
            "answer": f"Fake answer for {student_id}: {question}. Your **balance** is Rs 1,00,000."}


agent.run_agent = fake_run_agent          # app.py does "from agent import run_agent", so it gets the fake


def login(at, user_id, password):
    at.text_input[0].set_value(user_id)
    at.text_input[1].set_value(password)
    at.button[0].click().run()
    return at


print("1. Password hashing (auth.py)")
check("correct password accepted", (authenticate("S101", "S101@demo") or {}).get("id") == "S101")
check("lower-case ID accepted", (authenticate("s101", "S101@demo") or {}).get("id") == "S101")
check("wrong password rejected", authenticate("S101", "wrong") is None)
check("unknown ID rejected", authenticate("S999", "S999@demo") is None)
check("empty password rejected", authenticate("S101", "") is None)
users_text = open("data/users.json", encoding="utf-8").read()
check("users.json holds hashes only (no plain password)", "S101@demo" not in users_text and "pbkdf2_sha256$" in users_text)

print("\n2. Login screen")
at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30).run()
check("login screen shown first (no chat)", len(at.text_input) == 2 and len(at.chat_input) == 0)
login(at, "S101", "wrong")
check("wrong password -> error, not logged in", "user" not in at.session_state and len(at.error) > 0)
error_wrong_pw = at.error[0].value
login(at, "S999", "anything")
check("unknown ID gives the SAME error message", at.error[0].value == error_wrong_pw)
login(at, "S101", "S101@demo")
check("correct password logs in as S101", at.session_state["user"]["id"] == "S101")
check("no exception after login", not at.exception)
check("chat input visible after login", len(at.chat_input) == 1)
check("no student dropdown any more", len(at.sidebar.selectbox) == 0)
check("empty state shows the 6 demo question buttons", len(at.main.button) >= 6)

print("\n3. Asking a question")
at.chat_input[0].set_value("What is my current fee status?").run()
check("no exception after a question", not at.exception)
check("user and assistant messages appear", len(at.chat_message) == 2)
check("agent received the SESSION identity (S101)", "Fake answer for S101" in at.chat_message[1].markdown[0].value)
check("trace expander is present", any("How this answer was produced" in e.label for e in at.expander))
check("no raw JSON viewer under answers", len(at.json) == 0)

print("\n4. New session")
next(b for b in at.sidebar.button if b.label == "New session").click().run()
check("chat is cleared", len(at.chat_message) == 0)
check("still logged in", at.session_state["user"]["id"] == "S101")

print("\n5. Log out and switch user")
next(b for b in at.sidebar.button if b.label == "Log out").click().run()
check("log out returns to the login screen", "user" not in at.session_state and len(at.text_input) == 2)
login(at, "S102", "S102@demo")
check("S102 can log in", at.session_state["user"]["id"] == "S102")
at.chat_input[0].set_value("What is my fee status?").run()
check("agent now receives S102", "Fake answer for S102" in at.chat_message[1].markdown[0].value)

print("\n6. Admin")
next(b for b in at.sidebar.button if b.label == "Log out").click().run()
login(at, "admin", "admin@demo")
check("admin logs in", at.session_state["user"]["role"] == "admin")
check("admin sees no student chat", len(at.chat_input) == 0)

print("\n7. Typing effect")


class Slot:
    def __init__(self):
        self.frames = []

    def markdown(self, text, **_):
        self.frames.append(text)


slot = Slot()
theme.type_out(slot, "Your **balance** is Rs 1,00,000 and it is due on 15 Nov.", target_s=0.05)
check("answer is shown in several steps", len(slot.frames) > 3)
check("last frame is the exact answer", slot.frames[-1] == "Your **balance** is Rs 1,00,000 and it is due on 15 Nov.")
check("bold text never appears half-written", all(f.count("**") % 2 == 0 for f in slot.frames))

print("\n8. Trace component")
html = theme.trace_html(fake_run_agent("q", "S101"), history_sent=2)
check("trace shows tool name", "get_fee_status" in html)
check("trace shows policy chunk and score", "payment-portal-failure" in html and "0.41" in html)
check("trace shows tokens", "2,400" in html)
check("tool details shown as a table", "Tool call details" in html and "<th>Result</th>" in html)
check("trace escapes HTML", "&lt;b&gt;" in theme.trace_html({"decision": "<b>x</b>"}))
check("trace copes with an empty trace", "trace" in theme.trace_html({}))

print(f"\nResult: {passed}/{total} passed")
print("UI TEST COMPLETE" if passed == total else "Some checks failed - paste the output")
