"""
test_audit.py - checks the audit log (no LLM, no API key).
Run from anywhere:  python test_files/test_audit.py
Uses a temporary file, so the real data/audit_log.jsonl is not touched.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import audit

audit.AUDIT_FILE = Path(tempfile.mkdtemp()) / "audit_log.jsonl"     # isolated test file
passed = total = 0


def check(name, cond):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


print("1. Writing records")
r1 = audit.log_audit("S101", "get_fee_status", "ALLOWED", "Returned fee status", target="S101")
r2 = audit.log_audit("S101", "get_fee_status", "DENIED", "Blocked: not own record", target="S102")
r3 = audit.log_audit("S101", "request_record_update", "PENDING_APPROVAL", "REQ-1 created, not executed",
                     target="S101", details={"field": "phone", "new_value": "9999988888"}, request_id="REQ-1")
r4 = audit.log_audit("S101", "approval_decision", "REJECTED", "REQ-1 not executed", target="S101",
                     actor_role="student", approver="admin", request_id="REQ-1")
check("each record gets a unique audit ID", len({r1["audit_id"], r2["audit_id"], r3["audit_id"]}) == 3)
check("record answers WHO (actor)", r2["actor"] == "S101")
check("record answers WHAT (action + target)", r2["action"] == "get_fee_status" and r2["target"] == "S102")
check("record answers ALLOWED/APPROVED? (decision)", r2["decision"] == "DENIED")
check("record answers FINAL RESULT", r2["result"] == "Blocked: not own record")
check("approval links approver + request ID", r4["approver"] == "admin" and r4["request_id"] == "REQ-1")
check("time is recorded", r1["time"][:4].isdigit())

print("\n2. Invalid input")
try:
    audit.log_audit("S101", "x", "MAYBE", "y")
    check("unknown decision is rejected", False)
except ValueError:
    check("unknown decision is rejected", True)

print("\n3. Redaction")
r5 = audit.log_audit("S101", "chat", "ALLOWED", "done", details={"message": "my OTP is 482913, password: abc@123"})
r6 = audit.log_audit("S101", "chat", "ALLOWED", "card 4111111111111111 used")
text = audit.AUDIT_FILE.read_text(encoding="utf-8")
check("OTP value not written", "482913" not in text)
check("password value not written", "abc@123" not in text)
check("card number not written", "4111111111111111" not in text)
check("non-secret details kept", "9999988888" in text)

print("\n4. Reading")
rows = audit.read_audit()
check("newest first", rows[0]["audit_id"] == r6["audit_id"])
check("filter by decision", [r["audit_id"] for r in audit.read_audit(decision="DENIED")] == [r2["audit_id"]])
check("limit works", len(audit.read_audit(limit=2)) == 2)
with audit.AUDIT_FILE.open("a", encoding="utf-8") as f:
    f.write("not json\n")
check("damaged line is skipped, not a crash", len(audit.read_audit()) == 6)
counts = audit.audit_summary()
check("summary counts decisions", counts["DENIED"] == 1 and counts["ALLOWED"] == 3 and counts["REJECTED"] == 1)

print("\n5. Append-only file format")
lines = [l for l in text.splitlines() if l.strip()]
check("one JSON object per line", all(json.loads(l)["audit_id"] for l in lines))

print(f"\nResult: {passed}/{total} passed")
print("STEP 12 COMPLETE" if passed == total else "Some checks failed - paste the output")
