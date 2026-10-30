"""
test_admin.py - checks the Program Office screen (no LLM, no API key).

Creates two real PENDING requests through the security gate, then clicks Reject and Approve
on the admin screen and checks the student record + audit log.

Run from anywhere:  python test_files/test_admin.py
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
from streamlit.testing.v1 import AppTest

TMP = Path(tempfile.mkdtemp())
seed = Path(ROOT) / "data" / "seed" / "students.json"
shutil.copy(seed if seed.exists() else Path(ROOT) / "data" / "students.json", TMP / "students.json")
tools.STUDENTS_FILE = TMP / "students.json"
tools.PENDING_FILE = TMP / "pending.json"
tools.TICKETS_FILE = TMP / "tickets.json"
audit.AUDIT_FILE = TMP / "audit_log.jsonl"

SCRIPT = TMP / "admin_app.py"
SCRIPT.write_text(
    "import sys; sys.path.insert(0, r'%s')\n"
    "from admin import render_admin\n"
    "render_admin({'id': 'admin', 'role': 'admin', 'name': 'Program Office'})\n" % ROOT, encoding="utf-8")

passed = total = 0


def check(name, cond, got=None):
    global passed, total
    total += 1
    passed += bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond and got is not None:
        print("       got:", got)


def student(sid):
    return json.loads(tools.STUDENTS_FILE.read_text(encoding="utf-8"))[sid]


old_phone = student("S101")["phone"]
rid_reject = tools.execute_tool("request_record_update", {"field": "phone", "new_value": "9999988888"}, "S101")["request_id"]
rid_ok = tools.execute_tool("request_record_update", {"field": "programme", "new_value": "PGDM BDA"}, "S101")["request_id"]

print("1. Screen")
at = AppTest.from_file(str(SCRIPT), default_timeout=30).run()
check("no exception", not at.exception, at.exception)
keys = [b.key for b in at.button]
check("Approve + Reject shown for both pending requests",
      {f"ap_{rid_reject}", f"rj_{rid_reject}", f"ap_{rid_ok}", f"rj_{rid_ok}"} <= set(keys), keys)
check("record unchanged while pending", student("S101")["phone"] == old_phone)

print("\n2. Reject -> not executed")
next(b for b in at.button if b.key == f"rj_{rid_reject}").click().run()
check("no exception", not at.exception, at.exception)
check("request REJECTED_NOT_EXECUTED", tools.load_pending()[rid_reject]["status"] == "REJECTED_NOT_EXECUTED")
check("phone still unchanged", student("S101")["phone"] == old_phone)
check("success message shown", any("rejected" in s.value for s in at.success))
a = audit.read_audit(limit=1)[0]
check("audit: REJECTED by admin, request linked",
      a["decision"] == "REJECTED" and a["approver"] == "admin" and a["request_id"] == rid_reject, a)

print("\n3. Approve -> executed")
next(b for b in at.button if b.key == f"ap_{rid_ok}").click().run()
check("request APPROVED_EXECUTED", tools.load_pending()[rid_ok]["status"] == "APPROVED_EXECUTED")
check("programme changed to PGDM BDA", student("S101")["programme"] == "PGDM BDA")
check("audit: APPROVED by admin", audit.read_audit(limit=1)[0]["decision"] == "APPROVED")

print("\n4. After decisions")
check("no pending buttons left", not any(b.key.startswith(("ap_", "rj_")) for b in at.button))
html = "".join(m.value for m in at.markdown)
check("decided list shows Applied and Not applied", "Applied" in html and "Not applied" in html)
check("audit table shows PENDING_APPROVAL, REJECTED, APPROVED",
      all(d in html for d in ("PENDING_APPROVAL", "REJECTED", "APPROVED")))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nResult: {passed}/{total} passed")
print("STEP 16 COMPLETE" if passed == total else "Some checks failed - paste the output")
