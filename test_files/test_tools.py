import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)   # find agent.py, tools.py, memory.py ... in the project root
os.chdir(ROOT)             # so data/... and app.py paths work too


"""test_tools.py - tests every tool directly (no LLM involved)."""
import json
import tools
from tools import execute_tool, TOOLS_SCHEMA, TOOL_FUNCTIONS
from memory import clear_memory

passed = total = 0
def check(name, condition, result=None):
    global passed, total
    total += 1; passed += bool(condition)
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition and result is not None:
        print("       got:", json.dumps(result)[:200])

print("1. Fee status")
r = execute_tool("get_fee_status", {}, "S101")
check("S101 balance = 100000 (default = logged-in student)", r.get("balance") == 100000, r)
r = execute_tool("get_fee_status", {"student_id": "s102"}, "S102")
check("S102 fully paid (lowercase ID accepted)", r.get("payment_status") == "Fully paid", r)
r = execute_tool("get_fee_status", {}, "S104")
check("S104 overdue with late fee", r.get("payment_status") == "Overdue" and r.get("late_fee_so_far", 0) > 0, r)

print("\n2. Missing information")
r = execute_tool("get_fee_status", {}, "S103")
check("S103 fee data missing -> missing_data", r.get("status") == "missing_data", r)
r = execute_tool("get_fee_status", {"student_id": "S999"}, "S999")
check("Unknown student -> clean error", r.get("status") == "error" and "S999" in r["error"], r)

print("\n3. Tool error (simulated outage)")
tools.SIMULATE_OUTAGE["on"] = True
r = execute_tool("get_fee_status", {}, "S101")
check("Outage -> error returned, no crash", r.get("status") == "error" and "unavailable" in r["error"], r)
tools.SIMULATE_OUTAGE["on"] = False

print("\n4. Scholarship")
r = execute_tool("get_scholarship_status", {}, "S101")
check("S101 merit approved", "Merit" in r.get("scholarship", ""), r)

print("\n5. Policy search")
r = execute_tool("search_policy", {"query": "payment portal failed, pay next working day?"}, "S101")
check("Portal question -> payment-portal-failure chunk",
      r.get("status") == "ok" and r["chunks"][0]["id"] == "payment-portal-failure", r)
check("Keywords line not sent to LLM", "Keywords" not in r["chunks"][0]["text"], r)
r = execute_tool("search_policy", {"query": "hostel curfew timings"}, "S101")
check("Hostel -> no_match", r.get("status") == "no_match", r)
r = execute_tool("search_policy", {}, "S101")
check("Empty query -> clean error", r.get("status") == "error", r)

print("\n6. Support ticket")
r = execute_tool("create_support_ticket", {"issue": "ID card not received", "category": "academic"}, "S101")
check("Ticket created with TKT- id", r.get("ticket_id", "").startswith("TKT-"), r)
check("Ticket saved to tickets.json", tools.TICKETS_FILE.exists())
r = execute_tool("create_support_ticket", {"issue": "hi"}, "S101")
check("Too-short issue rejected", r.get("status") == "error", r)

print("\n7. Memory tool")
clear_memory("S101")
r = execute_tool("save_memory", {"fact": "Prefers short answers", "category": "preference"}, "S101")
check("Useful fact saved", r.get("saved") is True, r)
r = execute_tool("save_memory", {"fact": "My OTP is 482913"}, "S101")
check("OTP rejected by code", r.get("saved") is False, r)
clear_memory("S101")

print("\n8. Robustness")
check("Unknown tool -> error", execute_tool("delete_all", {}, "S101").get("status") == "error")
check("Bad args (None) -> no crash", "status" in execute_tool("get_fee_status", None, "S101"))

print("\n9. Schemas")
names = [t["function"]["name"] for t in TOOLS_SCHEMA]
check("7 tools in schema (5 from A1 + 2 from A2)", len(names) == 7)
check("Every schema has a matching function", set(names) == set(TOOL_FUNCTIONS))

if tools.TICKETS_FILE.exists():
    tools.TICKETS_FILE.unlink()          # clean up test tickets
print(f"\nResult: {passed}/{total} passed")
print("STEP 5 COMPLETE" if passed == total else "Some tests failed - check above")
