"""
audit.py - Audit log for the Student Support Agent (Assignment 2).

Every important action writes ONE line to data/audit_log.jsonl answering the brief's four questions:
  who requested it        -> actor, actor_role
  what was attempted      -> action, target, details
  allowed or approved?    -> decision  (ALLOWED / DENIED / PENDING_APPROVAL / APPROVED / REJECTED)
  final result            -> result

Append-only: the app never edits or deletes audit lines. Sensitive values are redacted
before writing with privacy.redact_deep(), so the log itself is safe to show.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from privacy import redact_deep

AUDIT_FILE = Path(__file__).parent / "data" / "audit_log.jsonl"
DECISIONS = ("ALLOWED", "DENIED", "PENDING_APPROVAL", "APPROVED", "REJECTED", "ERROR")


def log_audit(actor, action, decision, result, target=None, details=None,
              actor_role="student", approver=None, request_id=None, trace_id=None):
    """Append one audit record and return it."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    record = {
        "audit_id": "AU-" + uuid.uuid4().hex[:8].upper(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "actor": actor, "actor_role": actor_role,          # who requested
        "action": action, "target": target,                # what was attempted, on whose record
        "details": redact_deep(details or {}),
        "decision": decision,                              # allowed / denied / pending / approved / rejected
        "approver": approver,
        "result": redact_deep(result),                      # final result
        "request_id": request_id, "trace_id": trace_id,    # links to pending.json and traces.jsonl
    }
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_audit(actor=None, decision=None, limit=None):
    """Newest first. Optional filters by actor and decision. Skips damaged lines."""
    if not AUDIT_FILE.exists():
        return []
    rows = []
    for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    rows.reverse()
    if actor:
        rows = [r for r in rows if r.get("actor") == actor]
    if decision:
        rows = [r for r in rows if r.get("decision") == decision]
    return rows[:limit] if limit else rows


def audit_summary():
    """Counts per decision, for the admin dashboard."""
    counts = {d: 0 for d in DECISIONS}
    for r in read_audit():
        counts[r.get("decision")] = counts.get(r.get("decision"), 0) + 1
    return counts
