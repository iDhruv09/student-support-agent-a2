"""
admin.py - Program Office screen (Assignment 2): human approval + audit log.

Shown only when the logged-in user has role "admin" (checked in app.py from the session).

Main area
  1. Summary tiles     pending / approved / rejected / access denied
  2. Pending requests  each with Approve and Reject. Approve applies the change;
                       Reject leaves the record untouched. Both are audited (tools.decide_approval).
  3. Decided requests  history of approved / rejected requests
  4. Audit log         filterable table of every audited action (who, what, decision, result)

Left panel (admin)
  Review queue (live counts) · Rules the system enforces (with live numbers) · System info

decide_approval() is NOT a tool the LLM can call; only this screen calls it, with role="admin".
"""
from datetime import datetime

import streamlit as st

import theme
from audit import audit_summary, read_audit
from tools import decide_approval, load_pending, load_students

DECISION_PILL = {"ALLOWED": "ok", "DENIED": "bad", "PENDING_APPROVAL": "warn",
                 "APPROVED": "ok", "REJECTED": "neutral", "ERROR": "bad"}
MAX_AUDIT_ROWS = 200


def _table(headers, rows):
    """Small HTML table in the app's trace style (no pandas / pyarrow needed)."""
    head = "".join(f"<th>{theme.esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<div class="trace admin-table"><table><tr>{head}</tr>{body}</table></div>'


def _pill(text, kind):
    return f'<span class="pill {kind}">{theme.esc(text)}</span>'


def _decide(request_id, admin_id, approve):
    """Button callback: run the decision, keep a short message for the next screen draw."""
    try:
        status = decide_approval(request_id, admin_id, approve, approver_role="admin")
        word = "approved and applied" if approve else "rejected; record unchanged"
        st.session_state.admin_msg = ("success", f"{request_id} {word} ({status}).")
    except (ValueError, PermissionError) as e:
        st.session_state.admin_msg = ("error", str(e))


def _student_name(students, sid):
    return students.get(sid, {}).get("name", sid)


def _ago(iso_time):
    """'2026-10-31T09:00:00' -> '3h ago' (short, for the left panel)."""
    try:
        secs = (datetime.now() - datetime.fromisoformat(iso_time)).total_seconds()
    except (TypeError, ValueError):
        return "-"
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    return f"{int(secs // 86400)} d ago"


# ================================================================ left panel
def render_admin_sidebar(open_reqs, decided, counts, students, audit_rows, model_name):
    """Program Office content for the left panel (the user card and Log out are added by app.py)."""
    with st.sidebar:
        theme.side_title("Review queue")
        st.markdown(theme._kpis([("Pending", len(open_reqs)), ("Approved", counts.get("APPROVED", 0)),
                                 ("Rejected", counts.get("REJECTED", 0)), ("Denied", counts.get("DENIED", 0))],
                                "side-kpis"), unsafe_allow_html=True)
        if open_reqs:
            theme.side_line(f"Oldest waiting: <b>{theme.esc(_ago(open_reqs[0]['created_at']))}</b>")
        elif decided:
            last = decided[0]
            word = "Applied" if last["status"] == "APPROVED_EXECUTED" else "Not applied"
            theme.side_line(f"Last decision: <b>{theme.esc(last['request_id'])}</b> · {word}")
        else:
            theme.side_line("No requests yet.")

        theme.side_title("Rules enforced", ruled=True)
        theme.side_rules([
            ("Own data only", f"{counts.get('DENIED', 0)} denied"),
            ("Approval first", f"{len(open_reqs)} pending"),
            ("Secrets redacted", "on"),
            ("Audit log", f"{len(audit_rows)} lines"),
        ])

        theme.side_title("System", ruled=True)
        theme.side_info([("Students", str(len(students))), ("Model", model_name or "-"),
                         ("Audit file", "append-only")])


# ================================================================ main screen
def render_admin(user, model_name=""):
    theme.header(model_name)
    theme.page_title("Program Office", "Approve or reject record changes, and review every audited action.")

    msg = st.session_state.pop("admin_msg", None)
    if msg:
        (st.success if msg[0] == "success" else st.error)(msg[1])

    try:
        pending_all = load_pending()
        students = load_students()
    except Exception as e:
        st.error(f"Could not load requests: {e}")
        return
    open_reqs = sorted((r for r in pending_all.values() if r["status"] == "PENDING"),
                       key=lambda r: r["created_at"])
    decided = sorted((r for r in pending_all.values() if r["status"] != "PENDING"),
                     key=lambda r: r.get("decided_at") or "", reverse=True)
    counts = audit_summary()
    audit_rows = read_audit()
    e = theme.esc

    render_admin_sidebar(open_reqs, decided, counts, students, audit_rows, model_name)

    st.markdown(theme._kpis([("Pending requests", len(open_reqs)),
                             ("Approved", counts.get("APPROVED", 0)),
                             ("Rejected", counts.get("REJECTED", 0)),
                             ("Access denied", counts.get("DENIED", 0))]), unsafe_allow_html=True)

    tab_req, tab_hist, tab_audit = st.tabs([f"Pending requests ({len(open_reqs)})",
                                            f"Decided ({len(decided)})", "Audit log"])

    # ---------------- pending requests: the human approval step
    with tab_req:
        if not open_reqs:
            st.info("No requests are waiting for approval.")
        for r in open_reqs:
            with st.container(border=True, key=f"req_{r['request_id']}"):
                left, right = st.columns([3, 1.6], vertical_alignment="center")
                with left:
                    st.markdown(
                        f'<div class="req"><code>{e(r["request_id"])}</code> '
                        f'<b>{e(_student_name(students, r["target"]))}</b> '
                        f'<span class="sub">({e(r["target"])}) · {e(r["created_at"])}</span>'
                        f'<div class="chg">{e(r["field"].capitalize())}: '
                        f'<s>{e(r.get("old_value"))}</s> → <b>{e(r["new_value"])}</b></div>'
                        + (f'<div class="sub">Reason: {e(r["reason"])}</div>' if r.get("reason") else "")
                        + '</div>', unsafe_allow_html=True)
                with right:
                    a, b = st.columns(2)
                    a.button("Approve", key=f"ap_{r['request_id']}", type="primary", use_container_width=True,
                             on_click=_decide, args=(r["request_id"], user["id"], True))
                    b.button("Reject", key=f"rj_{r['request_id']}", use_container_width=True,
                             on_click=_decide, args=(r["request_id"], user["id"], False))

    # ---------------- decided requests
    with tab_hist:
        if not decided:
            st.info("No decisions yet.")
        else:
            st.markdown(_table(
                ["Request", "Student", "Change", "Result", "Decided by", "Decided at"],
                [[f"<code>{e(r['request_id'])}</code>", e(r["target"]),
                  f"{e(r['field'])}: {e(r.get('old_value'))} → <b>{e(r['new_value'])}</b>",
                  _pill("Applied", "ok") if r["status"] == "APPROVED_EXECUTED" else _pill("Not applied", "neutral"),
                  e(r.get("decided_by")), e((r.get("decided_at") or "").replace("T", " "))]
                 for r in decided]), unsafe_allow_html=True)

    # ---------------- audit log: who / what / decision / result
    with tab_audit:
        rows = audit_rows
        if not rows:
            st.info("The audit log is empty.")
            return
        f1, f2 = st.columns(2)
        decisions = f1.multiselect("Decision", list(DECISION_PILL), placeholder="All decisions")
        actors = f2.multiselect("Requested by", sorted({r["actor"] for r in rows}), placeholder="All users")
        if decisions:
            rows = [r for r in rows if r["decision"] in decisions]
        if actors:
            rows = [r for r in rows if r["actor"] in actors]
        shown = rows[:MAX_AUDIT_ROWS]
        st.markdown(_table(
            ["Time", "Who", "Action", "Target", "Decision", "Approver", "Result", "Request / Trace"],
            [[e(r["time"].replace("T", " ")), e(r["actor"]), f"<code>{e(r['action'])}</code>",
              e(r.get("target") or "-"), _pill(r["decision"], DECISION_PILL.get(r["decision"], "neutral")),
              e(r.get("approver") or "-"), e(r["result"]),
              f'<span class="sub">{e(r.get("request_id") or r.get("trace_id") or "-")}</span>']
             for r in shown]), unsafe_allow_html=True)
        st.caption(f"Showing {len(shown)} of {len(rows)} records (newest first) · append-only file "
                   f"data/audit_log.jsonl · secrets are redacted before writing")
