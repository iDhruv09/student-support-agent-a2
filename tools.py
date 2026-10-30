"""
tools.py - Tools the Student Support Agent can call (Assignment 2 version).

Assignment 1 tools are unchanged. Assignment 2 adds a SECURITY GATE in execute_tool():

  1. Identity      current_user comes from the logged-in session (app.py), never from the LLM.
  2. Authorization a student may read or change ONLY their own record. Enforced here in Python,
                   so it holds even if the LLM is tricked into asking for another student's data.
  3. Approval      record changes (phone, programme) are saved as PENDING and NOT applied.
                   Only decide_approval(), called from the admin screen, can apply or reject them.
  4. Audit         every private-data access, denial, request and decision is written to the audit log.

The LLM sees TOOLS_SCHEMA and decides WHICH tool to call. Python decides WHETHER it is allowed.
"""
import json
import re
import uuid
from datetime import date, datetime
from pathlib import Path

from audit import log_audit
from memory import save_memory
from privacy import redact
from retriever import retrieve

DATA_DIR = Path(__file__).parent / "data"
STUDENTS_FILE = DATA_DIR / "students.json"
TICKETS_FILE = DATA_DIR / "tickets.json"
PENDING_FILE = DATA_DIR / "pending.json"

LATE_FEE_PER_DAY = 100            # must match the policy handbook
SIMULATE_OUTAGE = {"on": False}   # demo switch for the "tool error" scenario

# Tools that touch one student's PRIVATE record -> must pass the ownership check
PRIVATE_TOOLS = {"get_fee_status", "get_scholarship_status", "request_record_update"}
UPDATABLE_FIELDS = {"phone", "programme"}
PROGRAMMES = {"PGDM AI&DS", "PGDM BDA"}
PHONE_RE = re.compile(r"^[6-9]\d{9}$")            # 10-digit Indian mobile number


class ToolError(Exception):
    """A clean, user-explainable tool failure."""


# ---------------------------------------------------------------- data helpers
def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        raise ToolError(f"{path.name} could not be read.")


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)                                 # atomic: never leaves a half-written file


def load_students():
    data = _read_json(STUDENTS_FILE, None)
    if data is None:
        raise ToolError("Student records are not available right now.")
    return data


def load_pending():
    return _read_json(PENDING_FILE, {})


def _norm_id(student_id):
    return (student_id or "").strip().upper()


def get_student(student_id):
    sid = _norm_id(student_id)
    students = load_students()
    if sid not in students:
        raise ToolError(f"No student record found for ID '{sid}'.")
    return sid, students[sid]


# ---------------------------------------------------------------- A1 tools (unchanged logic)
def get_fee_status(student_id):
    if SIMULATE_OUTAGE["on"]:
        raise ConnectionError("Fee system is temporarily unavailable (timeout).")
    sid, s = get_student(student_id)
    if s.get("fee_total") is None or s.get("fee_paid") is None:
        return {"status": "missing_data", "student_id": sid,
                "message": "Fee details are not available in the record. "
                           "Please raise a support ticket with the Accounts Office."}
    balance = s["fee_total"] - s["fee_paid"]
    result = {"status": "ok", "student_id": sid, "fee_total": s["fee_total"],
              "fee_paid": s["fee_paid"], "balance": balance,
              "due_date": s.get("due_date"), "note": s.get("fee_note")}
    if balance <= 0:
        result["payment_status"] = "Fully paid"
    elif s.get("due_date"):
        days_left = (date.fromisoformat(s["due_date"]) - date.today()).days
        if days_left < 0:
            result.update(payment_status="Overdue", days_overdue=-days_left,
                          late_fee_so_far=-days_left * LATE_FEE_PER_DAY)
        else:
            result.update(payment_status="Pending", days_until_due=days_left)
    return result


def get_scholarship_status(student_id):
    sid, s = get_student(student_id)
    if not s.get("scholarship"):
        return {"status": "missing_data", "student_id": sid,
                "message": "Scholarship information is not available in the record."}
    return {"status": "ok", "student_id": sid, "scholarship": s["scholarship"]}


def search_policy(query):
    if not query or not query.strip():
        raise ToolError("Search query is empty.")
    chunks = retrieve(query)
    if not chunks:
        return {"status": "no_match", "chunks": [],
                "message": "The student handbook does not contain information on this topic."}
    return {"status": "ok", "chunks": [{"id": c["id"], "title": c["title"], "score": c["score"],
                                        "text": c["text"]} for c in chunks]}


VALID_CATEGORIES = ("fee", "scholarship", "academic", "technical", "record", "other")


def create_support_ticket(student_id, issue, category="other"):
    issue = redact((issue or "").strip())
    if len(issue) < 5:
        raise ToolError("Please describe the issue in a few words.")
    if category not in VALID_CATEGORIES:
        category = "other"
    sid, _ = get_student(student_id)
    tickets = _read_json(TICKETS_FILE, [])
    ticket = {"ticket_id": "TKT-" + uuid.uuid4().hex[:6].upper(), "student_id": sid,
              "category": category, "issue": issue[:300], "status": "Open",
              "created_at": datetime.now().isoformat(timespec="seconds"),
              "expected_response": "within 2 working days"}
    tickets.append(ticket)
    _write_json(TICKETS_FILE, tickets)
    return {"status": "ok", **ticket}


def remember_fact(student_id, fact, category="other"):
    result = save_memory(student_id, fact, category)
    return {"status": "ok" if result["saved"] else "not_saved", **result}


# ---------------------------------------------------------------- A2 tools
def request_record_update(student_id, field, new_value, reason=""):
    """Create a PENDING change request. The record is NOT changed here."""
    sid, s = get_student(student_id)
    field = (field or "").strip().lower()
    value = str(new_value or "").strip()
    if field not in UPDATABLE_FIELDS:
        raise ToolError("Only phone number or programme can be changed through this request.")
    if field == "phone":
        value = re.sub(r"[\s-]", "", value)
        if value.startswith("+91"):
            value = value[3:]
        if not PHONE_RE.match(value):
            raise ToolError("Phone number must be a valid 10-digit Indian mobile number.")
    if field == "programme":
        match = next((p for p in PROGRAMMES if p.replace(" ", "").lower() == value.replace(" ", "").lower()), None)
        if not match:
            raise ToolError(f"Programme must be one of: {', '.join(sorted(PROGRAMMES))}.")
        value = match
    if str(s.get(field)) == value:
        raise ToolError(f"Your {field} is already {value}. No change is needed.")

    pending = load_pending()
    for rid, r in pending.items():                    # no duplicate open request for the same change
        if r["target"] == sid and r["field"] == field and r["new_value"] == value and r["status"] == "PENDING":
            return {"status": "pending_approval", "request_id": rid, "field": field, "new_value": value,
                    "message": "This change is already waiting for approval."}

    rid = "REQ-" + uuid.uuid4().hex[:6].upper()
    pending[rid] = {"request_id": rid, "requested_by": sid, "target": sid, "field": field,
                    "old_value": s.get(field), "new_value": value, "reason": redact(reason)[:200],
                    "status": "PENDING", "created_at": datetime.now().isoformat(timespec="seconds"),
                    "decided_by": None, "decided_at": None}
    _write_json(PENDING_FILE, pending)
    return {"status": "pending_approval", "request_id": rid, "field": field, "new_value": value,
            "message": "Request saved. The change will be applied only after the Program Office approves it."}


def check_request_status(student_id):
    """The logged-in student's OWN requests only."""
    sid = _norm_id(student_id)
    mine = [{k: r[k] for k in ("request_id", "field", "new_value", "status", "created_at", "decided_at")}
            for r in load_pending().values() if r["target"] == sid]
    if not mine:
        return {"status": "ok", "requests": [], "message": "You have no change requests."}
    return {"status": "ok", "requests": sorted(mine, key=lambda r: r["created_at"], reverse=True)}


# ---------------------------------------------------------------- dispatcher + SECURITY GATE
TOOL_FUNCTIONS = {
    "get_fee_status": lambda a, uid, t: get_fee_status(t),
    "get_scholarship_status": lambda a, uid, t: get_scholarship_status(t),
    "search_policy": lambda a, uid, t: search_policy(a.get("query", "")),
    "create_support_ticket": lambda a, uid, t: create_support_ticket(uid, a.get("issue", ""), a.get("category", "other")),
    "save_memory": lambda a, uid, t: remember_fact(uid, a.get("fact", ""), a.get("category", "other")),
    "request_record_update": lambda a, uid, t: request_record_update(t, a.get("field"), a.get("new_value"), a.get("reason", "")),
    "check_request_status": lambda a, uid, t: check_request_status(uid),
}
AUDITED_TOOLS = PRIVATE_TOOLS | {"create_support_ticket"}


def authorize(name, args, current_user, role="student"):
    """
    The permission check, in plain Python (not an LLM instruction).
    Returns (allowed, target, reason). target = whose record the call is about.
    """
    user = _norm_id(current_user)
    target = _norm_id(args.get("student_id")) or user          # default: the logged-in student
    if name not in PRIVATE_TOOLS:
        return True, user, "not a private-record tool"
    if role != "student":
        return False, target, "only students use the chat tools; admins act through the approval screen"
    if target != user:
        return False, target, f"{user} may only access their own record, not {target}"
    return True, target, "own record"


def execute_tool(name, args, current_user, role="student", trace_id=None):
    """
    Run a tool chosen by the LLM, behind the security gate. Never raises: always returns a dict.
    Every result carries "auth": ALLOWED / DENIED for the trace.
    """
    if name not in TOOL_FUNCTIONS:
        return {"status": "error", "auth": "DENIED", "error": f"Unknown tool '{name}'."}
    if not isinstance(args, dict):
        args = {}
    user = _norm_id(current_user)

    allowed, target, reason = authorize(name, args, user, role)
    if not allowed:
        log_audit(user, name, "DENIED", f"Blocked: {reason}", target=target, details=args,
                  actor_role=role, trace_id=trace_id)
        return {"status": "denied", "auth": "DENIED", "target": target,
                "error": "ACCESS DENIED: you can only view or change your own record."}

    try:
        result = TOOL_FUNCTIONS[name](args, user, target)
    except ToolError as e:
        result = {"status": "error", "error": str(e)}
    except Exception as e:                                       # outage, bad data, anything unexpected
        result = {"status": "error", "error": f"Tool failed: {e}",
                  "suggestion": "Try again later or raise a support ticket."}
    result["auth"] = "ALLOWED"

    if name in AUDITED_TOOLS:
        status = result.get("status")
        if status == "pending_approval":
            log_audit(user, name, "PENDING_APPROVAL", f"{result['request_id']} created; record NOT changed",
                      target=target, details={k: args.get(k) for k in ("field", "new_value")},
                      actor_role=role, request_id=result["request_id"], trace_id=trace_id)
        elif status == "error":
            log_audit(user, name, "ERROR", result.get("error"), target=target, details=args,
                      actor_role=role, trace_id=trace_id)
        else:
            summary = {"get_fee_status": "Returned fee status", "get_scholarship_status": "Returned scholarship status",
                       "create_support_ticket": f"Created {result.get('ticket_id')}"}.get(name, status)
            log_audit(user, name, "ALLOWED", summary, target=target, actor_role=role, trace_id=trace_id)
    return result


# ---------------------------------------------------------------- HUMAN APPROVAL (admin screen only)
def decide_approval(request_id, approver, approve, approver_role="admin"):
    """
    Apply or reject a PENDING request. Never exposed to the LLM (not in TOOLS_SCHEMA).
    Returns the final status string.
    """
    if approver_role != "admin":
        log_audit(approver, "approval_decision", "DENIED", "Only the Program Office can decide requests",
                  actor_role=approver_role, request_id=request_id)
        raise PermissionError("Only an admin can approve or reject requests.")

    pending = load_pending()
    req = pending.get(request_id)
    if not req:
        raise ValueError(f"Request {request_id} not found.")
    if req["status"] != "PENDING":
        raise ValueError(f"Request {request_id} was already decided ({req['status']}).")

    if approve:
        students = load_students()
        students[req["target"]][req["field"]] = req["new_value"]
        _write_json(STUDENTS_FILE, students)
        req["status"] = "APPROVED_EXECUTED"
        decision, result = "APPROVED", f"{req['field']} changed to {req['new_value']}"
    else:
        req["status"] = "REJECTED_NOT_EXECUTED"                   # the record is NOT touched
        decision, result = "REJECTED", "Change not applied; record unchanged"

    req["decided_by"] = approver
    req["decided_at"] = datetime.now().isoformat(timespec="seconds")
    _write_json(PENDING_FILE, pending)
    log_audit(req["requested_by"], "approval_decision", decision, result, target=req["target"],
              details={"field": req["field"], "new_value": req["new_value"]},
              actor_role="student", approver=approver, request_id=request_id)
    return req["status"]


# ---------------------------------------------------------------- schemas sent to the LLM
def _fn(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}


_STUDENT_ID = {"student_id": {"type": "string",
               "description": "Student ID like S101. Omit to use the logged-in student."}}

TOOLS_SCHEMA = [
    _fn("get_fee_status",
        "Get a student's PERSONAL fee record: total fee, amount paid, balance, due date, "
        "and whether payment is pending, overdue or fully paid. Use for 'my fees', 'fee balance', "
        "'how much do I owe'.", _STUDENT_ID),
    _fn("get_scholarship_status",
        "Get a student's PERSONAL scholarship status (approved, pending, rejected, withdrawn...). "
        "Use for 'my scholarship'.", _STUDENT_ID),
    _fn("search_policy",
        "Search the official student policy handbook for GENERAL rules: late fee, payment portal "
        "failure, installments, refunds, scholarship eligibility, elective/programme change, "
        "attendance, exams, support. Use for 'can I...', 'what is the rule...', 'how do I...'.",
        {"query": {"type": "string", "description": "Short search query about the rule, in English."}},
        ["query"]),
    _fn("create_support_ticket",
        "Create a support ticket for the logged-in student when they report a specific problem, ask to "
        "raise a complaint, or agree to your offer of a ticket.",
        {"issue": {"type": "string", "description": "Clear one-line description of the issue."},
         "category": {"type": "string", "enum": list(VALID_CATEGORIES)}},
        ["issue"]),
    _fn("save_memory",
        "Save a USEFUL LONG-TERM fact about the logged-in student, such as their programme or "
        "answer preferences. Never use for OTPs, passwords, temporary feelings or one-time events.",
        {"fact": {"type": "string", "description": "Short fact, e.g. 'Prefers short answers'."},
         "category": {"type": "string", "enum": ["programme", "preference", "other"]}},
        ["fact"]),
    _fn("request_record_update",
        "SENSITIVE ACTION. Request a change to the student's official record (phone number or programme). "
        "Call ONLY after the student has explicitly confirmed the exact change with 'yes'. "
        "The change is NOT applied: it waits for Program Office approval.",
        {**_STUDENT_ID,
         "field": {"type": "string", "enum": sorted(UPDATABLE_FIELDS)},
         "new_value": {"type": "string", "description": "New phone number (10 digits) or programme name."},
         "reason": {"type": "string", "description": "Optional short reason given by the student."}},
        ["field", "new_value"]),
    _fn("check_request_status",
        "Check the status (pending, approved, rejected) of the logged-in student's own change requests.",
        {}),
]
