"""Read-only reporting. Plain SQL aggregates executed under the caller's RLS context
(and with an explicit org_id filter as defence in depth). Money is integer cents."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.db import set_org_context


def _num(v: Any) -> Any:
    """SUM() over bigint yields numeric (Decimal), which JSON would render as a string.
    Money must stay a JSON number, so integral Decimals become int."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _one(db: Session, sql: str, **p: Any) -> Any:
    return _num(db.execute(text(sql), p).scalar_one())


def _rows(db: Session, sql: str, **p: Any) -> list[dict[str, Any]]:
    return [{k: _num(v) for k, v in r._mapping.items()} for r in db.execute(text(sql), p)]


def overview(db: Session, org_id: uuid.UUID) -> dict[str, Any]:
    set_org_context(db, org_id)
    today = utcnow().date()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    o = {"o": org_id}
    return {
        "open_pipeline_cents": _one(
            db,
            "SELECT COALESCE(SUM(value_amount),0) FROM deals WHERE org_id=:o AND stage NOT IN ('won','lost')",
            **o,
        ),
        "won_this_month_cents": _one(
            db,
            "SELECT COALESCE(SUM(value_amount),0) FROM deals WHERE org_id=:o AND stage='won' AND closed_at >= :d",
            d=month_start,
            **o,
        ),
        "won_ytd_cents": _one(
            db,
            "SELECT COALESCE(SUM(value_amount),0) FROM deals WHERE org_id=:o AND stage='won' AND closed_at >= :d",
            d=year_start,
            **o,
        ),
        "outstanding_cents": _one(
            db,
            "SELECT COALESCE(SUM(total_cents-amount_paid_cents),0) FROM invoices WHERE org_id=:o AND status IN ('sent','partially_paid')",
            **o,
        ),
        "overdue_cents": _one(
            db,
            "SELECT COALESCE(SUM(total_cents-amount_paid_cents),0) FROM invoices WHERE org_id=:o AND status IN ('sent','partially_paid') AND due_date < :t",
            t=today,
            **o,
        ),
        "collected_this_month_cents": _one(
            db,
            "SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE org_id=:o AND paid_on >= :d",
            d=month_start,
            **o,
        ),
        "active_projects": _one(
            db, "SELECT COUNT(*) FROM projects WHERE org_id=:o AND status='active'", **o
        ),
        "unbilled_time_cents": _one(
            db,
            "SELECT COALESCE(SUM((minutes*COALESCE(rate_cents,0)+30)/60),0) FROM time_entries "
            "WHERE org_id=:o AND status='approved' AND billable AND invoice_id IS NULL",
            **o,
        ),
        "pending_time_approvals": _one(
            db,
            "SELECT COUNT(*) FROM time_entries WHERE org_id=:o AND status='draft' AND ended_at IS NOT NULL",
            **o,
        ),
    }


def attention(db: Session, org_id: uuid.UUID) -> list[dict[str, Any]]:
    """The 'what needs me today' feed, most urgent first."""
    set_org_context(db, org_id)
    t = utcnow().date()
    o = {"o": org_id}
    items: list[dict[str, Any]] = []
    for r in _rows(
        db,
        "SELECT id, number, client_id, total_cents-amount_paid_cents AS bal, due_date FROM invoices "
        "WHERE org_id=:o AND status IN ('sent','partially_paid') AND due_date < :t ORDER BY due_date",
        t=t,
        **o,
    ):
        days = (t - r["due_date"]).days
        items.append(
            {
                "kind": "invoice_overdue",
                "severity": "high" if days > 14 else "medium",
                "entity_type": "invoice",
                "entity_id": str(r["id"]),
                "title": f"Invoice {r['number']} is {days} day(s) overdue",
                "detail": f"{r['bal']} cents outstanding",
                "sort": 100 + days,
            }
        )
    for r in _rows(
        db,
        "SELECT id, title, valid_until FROM proposals WHERE org_id=:o AND status='sent' AND valid_until BETWEEN :t AND :e ORDER BY valid_until",
        e=t + timedelta(days=7),
        t=t,
        **o,
    ):
        items.append(
            {
                "kind": "proposal_expiring",
                "severity": "medium",
                "entity_type": "proposal",
                "entity_id": str(r["id"]),
                "title": f"Proposal '{r['title']}' expires {r['valid_until']}",
                "detail": "No reply from the client yet",
                "sort": 60,
            }
        )
    for r in _rows(
        db,
        "SELECT id, title, due_date FROM tasks WHERE org_id=:o AND status != 'done' AND due_date < :t ORDER BY due_date LIMIT 50",
        t=t,
        **o,
    ):
        items.append(
            {
                "kind": "task_overdue",
                "severity": "medium",
                "entity_type": "task",
                "entity_id": str(r["id"]),
                "title": f"Task '{r['title']}' was due {r['due_date']}",
                "detail": "",
                "sort": 50,
            }
        )
    for r in _rows(
        db,
        "SELECT id, name, due_date FROM projects WHERE org_id=:o AND status IN ('planning','active') AND due_date < :t",
        t=t,
        **o,
    ):
        items.append(
            {
                "kind": "project_late",
                "severity": "high",
                "entity_type": "project",
                "entity_id": str(r["id"]),
                "title": f"Project '{r['name']}' is past its due date",
                "detail": str(r["due_date"]),
                "sort": 90,
            }
        )
    for r in _rows(
        db,
        "SELECT d.id, d.title FROM deals d WHERE d.org_id=:o AND d.stage NOT IN ('won','lost') "
        "AND COALESCE((SELECT MAX(created_at) FROM deal_stage_history h WHERE h.org_id=d.org_id AND h.deal_id=d.id), d.created_at) < now() - interval '30 days'",
        **o,
    ):
        items.append(
            {
                "kind": "deal_stale",
                "severity": "low",
                "entity_type": "deal",
                "entity_id": str(r["id"]),
                "title": f"Deal '{r['title']}' has not moved in 30 days",
                "detail": "",
                "sort": 30,
            }
        )
    n = _one(
        db,
        "SELECT COUNT(*) FROM time_entries WHERE org_id=:o AND status='draft' AND ended_at IS NOT NULL AND created_at < now() - interval '7 days'",
        **o,
    )
    if n:
        items.append(
            {
                "kind": "time_unapproved",
                "severity": "low",
                "entity_type": "time",
                "entity_id": None,
                "title": f"{n} time entries waiting for approval for over a week",
                "detail": "",
                "sort": 40,
            }
        )
    items.sort(key=lambda i: -i["sort"])
    for i in items:
        del i["sort"]
    return items


def revenue_by_month(db: Session, org_id: uuid.UUID, months: int) -> list[dict[str, Any]]:
    set_org_context(db, org_id)
    return _rows(
        db,
        """
        WITH m AS (SELECT generate_series(date_trunc('month', now()) - make_interval(months => :n - 1), date_trunc('month', now()), interval '1 month')::date AS month)
        SELECT m.month,
               COALESCE((SELECT SUM(total_cents) FROM invoices i WHERE i.org_id=:o AND i.status != 'draft' AND i.status != 'void' AND date_trunc('month', i.issue_date) = m.month), 0) AS invoiced_cents,
               COALESCE((SELECT SUM(amount_cents) FROM payments p WHERE p.org_id=:o AND date_trunc('month', p.paid_on) = m.month), 0) AS collected_cents
        FROM m ORDER BY m.month
        """,
        o=org_id,
        n=months,
    )


def pipeline(db: Session, org_id: uuid.UUID) -> dict[str, Any]:
    set_org_context(db, org_id)
    o = {"o": org_id}
    stages = _rows(
        db,
        "SELECT stage, COUNT(*) AS deals, COALESCE(SUM(value_amount),0) AS value_cents FROM deals WHERE org_id=:o GROUP BY stage",
        **o,
    )
    won = _one(db, "SELECT COUNT(*) FROM deals WHERE org_id=:o AND stage='won'", **o)
    lost = _one(db, "SELECT COUNT(*) FROM deals WHERE org_id=:o AND stage='lost'", **o)
    avg_days = _one(
        db,
        "SELECT COALESCE(ROUND(AVG(EXTRACT(EPOCH FROM (closed_at - created_at))/86400)::numeric, 1), 0) FROM deals WHERE org_id=:o AND stage='won' AND closed_at IS NOT NULL",
        **o,
    )
    return {
        "stages": stages,
        "win_rate": round(won / (won + lost), 3) if (won + lost) else None,
        "avg_days_to_win": float(avg_days),
    }


def utilization(
    db: Session, org_id: uuid.UUID, date_from: date, date_to: date
) -> list[dict[str, Any]]:
    set_org_context(db, org_id)
    return _rows(
        db,
        """
        SELECT u.id AS user_id, u.full_name,
               COALESCE(SUM(t.minutes), 0) AS minutes,
               COALESCE(SUM(t.minutes) FILTER (WHERE t.billable), 0) AS billable_minutes,
               CASE WHEN COALESCE(SUM(t.minutes),0) = 0 THEN NULL
                    ELSE ROUND(100.0 * SUM(t.minutes) FILTER (WHERE t.billable) / SUM(t.minutes), 1) END AS billable_pct
        FROM users u LEFT JOIN time_entries t
          ON t.org_id = u.org_id AND t.user_id = u.id AND t.entry_date BETWEEN :f AND :t
        WHERE u.org_id = :o AND u.is_active
        GROUP BY u.id, u.full_name ORDER BY minutes DESC
        """,
        o=org_id,
        f=date_from,
        t=date_to,
    )


def project_health(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any] | None:
    set_org_context(db, org_id)
    rows = _rows(
        db,
        """
        SELECT p.id, p.name, p.status, p.budget_amount AS budget_cents, p.due_date,
          COALESCE((SELECT SUM(total_cents) FROM invoices i WHERE i.org_id=p.org_id AND i.project_id=p.id AND i.status NOT IN ('draft','void')), 0) AS invoiced_cents,
          COALESCE((SELECT SUM(amount_paid_cents) FROM invoices i WHERE i.org_id=p.org_id AND i.project_id=p.id AND i.status NOT IN ('draft','void')), 0) AS paid_cents,
          COALESCE((SELECT SUM((minutes*COALESCE(rate_cents,0)+30)/60) FROM time_entries t WHERE t.org_id=p.org_id AND t.project_id=p.id AND t.billable), 0) AS time_value_cents,
          COALESCE((SELECT SUM(minutes) FROM time_entries t WHERE t.org_id=p.org_id AND t.project_id=p.id), 0) AS minutes_logged,
          (SELECT COUNT(*) FROM tasks k WHERE k.org_id=p.org_id AND k.project_id=p.id) AS tasks_total,
          (SELECT COUNT(*) FROM tasks k WHERE k.org_id=p.org_id AND k.project_id=p.id AND k.status='done') AS tasks_done
        FROM projects p WHERE p.org_id=:o AND p.id=:p
        """,
        o=org_id,
        p=project_id,
    )
    if not rows:
        return None
    r = rows[0]
    b = r["budget_cents"]
    r["budget_used_pct"] = round(100 * r["time_value_cents"] / b, 1) if b else None
    r["id"] = str(r["id"])
    return r
