"""
app.py - Streamlit interface for the Student Support Agent (Assignment 2).

Run with:  streamlit run app.py

Assignment 2 changes
  - Login screen: a student or the admin signs in with ID + password (hashed, see auth.py).
  - The student ID used by the agent comes ONLY from the logged-in session,
    never from a dropdown or from text typed in the chat.
  - Admin role: approvals and audit page (completed in Step 16).

Note on the typing effect: the agent returns the full answer first (tools need the complete
result), then the screen types it in. Latency in the trace is the agent's real time only.
"""
import streamlit as st

from privacy import redact
import theme
from admin import render_admin
from agent import MODEL, run_agent
from auth import authenticate
from memory import clear_memory, load_memory
from tools import SIMULATE_OUTAGE

st.set_page_config(page_title="Student Support Agent", page_icon=theme.favicon(),
                   layout="wide", initial_sidebar_state="auto")
theme.apply()

ss = st.session_state
ss.setdefault("messages", [])          # this session's chat: {"role", "content", "trace", "history_sent"}
ss.setdefault("queued", None)          # question chosen from a demo button
ss.setdefault("failed_logins", 0)
MAX_FAILED_LOGINS = 5
DEMO_ACCOUNTS = [("S101", "S101@demo"), ("S102", "S102@demo"), ("admin", "admin@demo")]

# Scenarios from the assignment brief, as one-click questions: (question, what it shows)
SAMPLES = [
    ("What is my current fee status?", "Tool call: fee record"),
    ("The payment portal failed. Can I pay on the next working day?", "Policy retrieval"),
    ("Please remember that I am in PGDM AI&DS and I prefer short answers.", "Saves long-term memory"),
    ("Which programme am I in?", "Memory recall. Click 'New session' first to test across sessions"),
    ("Remember that I am feeling stressed today. My OTP is 482913.", "Temporary and sensitive: must not be stored"),
    ("What are the hostel curfew timings?", "Not in the handbook: should say so"),
]
AGENT_AVATAR = ":material/support_agent:"
USER_AVATAR = ":material/person:"


# ================================================================ login
def login_screen():
    theme.header(MODEL)
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        theme.page_title("Sign in", "Use your student ID, or the admin account for approvals.")
        if ss.failed_logins >= MAX_FAILED_LOGINS:
            st.error("Too many failed attempts. Close this tab and try again later.")
            st.stop()
        with st.form("login"):
            user_id = st.text_input("User ID", placeholder="e.g. S101 or admin")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
        if submitted:
            user = authenticate(user_id, password)
            if user:
                ss.clear()                                   # nothing from a previous user survives
                ss.user = user
                st.rerun()
            ss.failed_logins += 1
            st.error("Invalid ID or password.")              # same message for both cases
        theme.demo_logins(DEMO_ACCOUNTS)
    st.stop()


def logout():
    ss.clear()


if "user" not in ss:
    login_screen()

USER = ss.user                                               # trusted identity for this session
SIMULATE_OUTAGE["on"] = bool(ss.get("outage", False))        # set before the agent runs

with st.sidebar:
    theme.signed_in(USER["name"], USER["id"], USER["role"])
    st.button("Log out", on_click=logout, use_container_width=True, key="logout")

# ================================================================ admin (completed in Step 16)
if USER["role"] == "admin":
    render_admin(USER, MODEL)
    st.stop()


# ================================================================ student chat
STUDENT_ID = USER["id"]


def reset_chat():
    """New session: clears the chat only. Long-term memory is kept."""
    ss.messages = []


def queue_question(text):
    ss.queued = text


def render_trace(msg):
    with st.expander("How this answer was produced"):
        st.markdown(theme.trace_html(msg["trace"], msg.get("history_sent", 0)), unsafe_allow_html=True)


def render_message(msg):
    with st.chat_message(msg["role"], avatar=USER_AVATAR if msg["role"] == "user" else AGENT_AVATAR):
        st.markdown(msg["content"])
        if msg.get("trace"):
            render_trace(msg)


def sample_buttons(prefix):
    cols = st.columns(2)
    for i, (question, shows) in enumerate(SAMPLES):
        cols[i % 2].button(question, key=f"{prefix}_{i}", help=shows, use_container_width=True,
                           on_click=queue_question, args=(question,))


with st.sidebar:
    st.button("New session", on_click=reset_chat, use_container_width=True, key="new_session",
              help="Clears this chat. Remembered facts are kept.")

theme.header(MODEL)
theme.intro()

question = st.chat_input("Type your question") or ss.queued
ss.queued = None

if not ss.messages and not question:
    theme.empty_state()
    sample_buttons("sample")
elif ss.messages:
    with st.expander("Demo questions"):
        sample_buttons("more")

for msg in ss.messages:
    render_message(msg)

if question:
    raw_question = question 
    history = [{"role": m["role"], "content": m["content"]} for m in ss.messages]
    user_msg = {"role": "user", "content": raw_question}
    render_message(user_msg)

    with st.chat_message("assistant", avatar=AGENT_AVATAR):
        slot = st.empty()
        slot.markdown(theme.working_html(), unsafe_allow_html=True)         # animated "working" dots
        trace = run_agent(raw_question, STUDENT_ID, history)                    # identity from the session only
        theme.type_out(slot, trace["answer"])                               # answer types itself in

    ss.messages.append(user_msg)
    ss.messages.append({"role": "assistant", "content": trace["answer"], "trace": trace,
                        "history_sent": min(len(history), 4)})
    st.rerun()          # redraw from saved state: adds the trace, memory and session numbers

# ---------------------------------------------------------------- session panel (rest)
traces = [m["trace"] for m in ss.messages if m.get("trace")]
stats = {"questions": len(traces),
         "avg_latency": sum(t["latency_s"] for t in traces) / len(traces) if traces else 0,
         "in_tokens": sum(t["input_tokens"] for t in traces),
         "out_tokens": sum(t["output_tokens"] for t in traces)}

with st.sidebar:
    memory_items = load_memory(STUDENT_ID)
    theme.side_title("What I remember", ruled=True)
    theme.memory_chips(memory_items)
    if memory_items:
        if st.button("Clear remembered facts", use_container_width=True, key="clear_mem",
                     help="Programme and preferences are kept between sessions. "
                          "OTPs, passwords and temporary feelings are never stored."):
            clear_memory(STUDENT_ID)
            st.rerun()

    theme.side_title("This session", ruled=True)
    theme.stats_grid(stats)

    theme.side_title("Demo controls", ruled=True)
    st.toggle("Simulate fee system outage", key="outage",
              help="Makes the fee tool fail so you can show how the agent handles a tool error.")
