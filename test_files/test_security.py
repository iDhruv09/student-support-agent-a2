"""
test_security.py - proves authorization, approval and audit are enforced IN CODE.

These tests call execute_tool() and decide_approval() DIRECTLY, with no LLM involved.
They simulate the worst case: the LLM has been tricked into calling a tool for another student.

Run from anywhere:  python test_files/test_security.py
Uses temporary copies of the data files, so your real data/ is not changed.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import audit
import tools

# ---- isolated copies of every file the gate touches
TMP = Path(tempfile.mkdtemp())
seed = Path(ROOT) / "data" / "seed" / "students.json"
shutil.copy(seed if seed.exists() else Path(ROOT) / "data" / "students.json", TMP / "students.json")
tools.STUDENTS_FILE = TMP / "students.json"
tools.PENDING_FILE = TMP / "pending.json"
tools.TICKETS_FILE = TMP / "tickets.json"
audit.AUDIT_FILE = TMP / "audit_log.jsonl"

passed = total = 0


def check(name, cond, got=None):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond and got is not None:
        print("       got:", json.dumps(got, ensure_ascii=False)[:220])


def students():
    return json.loads(tools.STUDENTS_FILE.read_text(encoding="utf-8"))


def last_audit():
    return audit.read_audit(limit=1)[0]


ORIGINAL_S101_PHONE = students()["S101"]["phone"]
ORIGINAL_S102_PHONE = students()["S102"]["phone"]

print("1. Own record -> ALLOWED")
r = tools.execute_tool("get_fee_status", {}, "S101")
check("S101 reads own fees (no student_id given)", r.get("auth") == "ALLOWED" and r.get("balance") == 100000, r)
check("audit: ALLOWED, actor S101, target S101",
      last_audit()["decision"] == "ALLOWED" and last_audit()["actor"] == "S101" and last_audit()["target"] == "S101")
r = tools.execute_tool("get_scholarship_status", {"student_id": "s101"}, "S101")
check("S101 reads own scholarship (lower-case ID)", r.get("auth") == "ALLOWED" and "Merit" in r.get("scholarship", ""), r)

print("\n2. Another student's record -> DENIED (LLM tricked into asking)")
r = tools.execute_tool("get_fee_status", {"student_id": "S102"}, "S101")
check("S101 cannot READ S102 fees", r.get("auth") == "DENIED" and "balance" not in r, r)
check("no S102 data leaks in the denial", "350000" not in json.dumps(r) and "Riya" not in json.dumps(r), r)
a = last_audit()
check("audit: DENIED, who=S101, what=get_fee_status, target=S102",
      a["decision"] == "DENIED" and a["actor"] == "S101" and a["action"] == "get_fee_status" and a["target"] == "S102", a)
r = tools.execute_tool("get_scholarship_status", {"student_id": "S102"}, "S101")
check("S101 cannot READ S102 scholarship", r.get("auth") == "DENIED", r)
r = tools.execute_tool("request_record_update",
                       {"student_id": "S102", "field": "phone", "new_value": "9111111111"}, "S101")
check("S101 cannot MODIFY S102 record", r.get("auth") == "DENIED", r)
check("S102 phone unchanged", students()["S102"]["phone"] == ORIGINAL_S102_PHONE)
check("no pending request created for S102",
      all(p["target"] != "S102" for p in tools.load_pending().values()))
r = tools.execute_tool("get_fee_status", {"student_id": "S102"}, "admin", role="admin")
check("admin cannot read student data through chat tools", r.get("auth") == "DENIED", r)

print("\n3. Sensitive change -> PENDING, not executed")
r = tools.execute_tool("request_record_update", {"field": "phone", "new_value": "99999 88888"}, "S101")
check("request accepted as pending_approval", r.get("status") == "pending_approval" and r.get("request_id"), r)
rid_reject = r.get("request_id")
check("phone NOT changed yet", students()["S101"]["phone"] == ORIGINAL_S101_PHONE)
check("audit: PENDING_APPROVAL with request ID",
      last_audit()["decision"] == "PENDING_APPROVAL" and last_audit()["request_id"] == rid_reject, last_audit())
r = tools.execute_tool("request_record_update", {"field": "phone", "new_value": "9999988888"}, "S101")
check("duplicate request returns the same ID", r.get("request_id") == rid_reject, r)
r = tools.execute_tool("check_request_status", {}, "S101")
check("student sees own request as PENDING",
      any(q["request_id"] == rid_reject and q["status"] == "PENDING" for q in r["requests"]), r)
r = tools.execute_tool("check_request_status", {}, "S102")
check("S102 does not see S101's requests", r["requests"] == [], r)

print("\n4. Input validation")
for args, why in [({"field": "phone", "new_value": "12345"}, "short phone"),
                  ({"field": "phone", "new_value": "1234567890"}, "phone not starting 6-9"),
                  ({"field": "fee_paid", "new_value": "350000"}, "field not allowed (fees)"),
                  ({"field": "programme", "new_value": "MBA"}, "unknown programme"),
                  ({"field": "programme", "new_value": "PGDM AI&DS"}, "same as current value")]:
    r = tools.execute_tool("request_record_update", args, "S101")
    check(f"rejected: {why}", r.get("status") == "error", r)

print("\n5. Approval REJECTED -> must not execute")
try:
    tools.decide_approval(rid_reject, "S101", approve=True, approver_role="student")
    check("a student cannot approve their own request", False)
except PermissionError:
    check("a student cannot approve their own request", True)
check("phone still unchanged after failed self-approval", students()["S101"]["phone"] == ORIGINAL_S101_PHONE)
status = tools.decide_approval(rid_reject, "admin", approve=False)
check("admin rejects -> REJECTED_NOT_EXECUTED", status == "REJECTED_NOT_EXECUTED", status)
check("phone STILL unchanged after rejection", students()["S101"]["phone"] == ORIGINAL_S101_PHONE)
a = last_audit()
check("audit: REJECTED, approver=admin, request ID linked",
      a["decision"] == "REJECTED" and a["approver"] == "admin" and a["request_id"] == rid_reject, a)
try:
    tools.decide_approval(rid_reject, "admin", approve=True)
    check("a decided request cannot be decided again", False)
except ValueError:
    check("a decided request cannot be decided again", True)
check("phone unchanged after re-decision attempt", students()["S101"]["phone"] == ORIGINAL_S101_PHONE)

print("\n6. Approval APPROVED -> executes")
rid_ok = tools.execute_tool("request_record_update", {"field": "phone", "new_value": "9999988888"}, "S101")["request_id"]
status = tools.decide_approval(rid_ok, "admin", approve=True)
check("admin approves -> APPROVED_EXECUTED", status == "APPROVED_EXECUTED", status)
check("phone NOW changed to 9999988888", students()["S101"]["phone"] == "9999988888")
check("audit: APPROVED with result", last_audit()["decision"] == "APPROVED" and "9999988888" in last_audit()["result"])

print("\n7. Errors are audited, not crashes")
tools.SIMULATE_OUTAGE["on"] = True
r = tools.execute_tool("get_fee_status", {}, "S101")
tools.SIMULATE_OUTAGE["on"] = False
check("outage -> error, still ALLOWED, audited as ERROR",
      r.get("status") == "error" and r.get("auth") == "ALLOWED" and last_audit()["decision"] == "ERROR", r)
check("unknown tool -> DENIED", tools.execute_tool("delete_all", {}, "S101").get("auth") == "DENIED")

print("\n8. Schema")
names = [t["function"]["name"] for t in tools.TOOLS_SCHEMA]
check("7 tools exposed to the LLM", len(names) == 7 and set(names) == set(tools.TOOL_FUNCTIONS))
check("decide_approval is NOT exposed to the LLM", "decide_approval" not in names)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nResult: {passed}/{total} passed")
print("STEP 14 COMPLETE" if passed == total else "Some checks failed - paste the output")
