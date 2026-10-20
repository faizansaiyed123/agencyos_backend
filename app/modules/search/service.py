"""Search + a keyword 'assistant'.

HONEST SCOPE: this is Postgres full-text search (stemming, ranking, snippets), not
vector/semantic search and not an LLM. The assistant routes a few intents to the
reports and otherwise answers with the best-matching records. It never invents text:
every sentence it returns is built from rows it actually found.
"""

import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import set_org_context
from app.core.permissions import Perm, Role, has_permission
from app.modules.reporting import service as reporting

# type -> (table, id col, title expr, body expr, permission, restricted_ok)
_SOURCES: dict[str, tuple[str, str, str, Perm]] = {
    "client": (
        "clients",
        "name",
        "coalesce(name,'') || ' ' || coalesce(industry,'') || ' ' || coalesce(notes,'')",
        Perm.CLIENT_READ,
    ),
    "deal": (
        "deals",
        "title",
        "coalesce(title,'') || ' ' || coalesce(description,'')",
        Perm.DEAL_READ,
    ),
    "proposal": ("proposals", "title", "coalesce(title,'')", Perm.PROPOSAL_READ),
    "project": (
        "projects",
        "name",
        "coalesce(name,'') || ' ' || coalesce(description,'')",
        Perm.PROJECT_READ,
    ),
    "task": (
        "tasks",
        "title",
        "coalesce(title,'') || ' ' || coalesce(description,'')",
        Perm.PROJECT_READ,
    ),
    "invoice": (
        "invoices",
        "coalesce(number,'draft invoice')",
        "coalesce(number,'') || ' ' || coalesce(notes,'')",
        Perm.INVOICE_READ,
    ),
}


def search(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, role: Role, q: str, limit: int = 20
) -> list[dict[str, Any]]:
    q = q.strip()
    if not q:
        return []
    set_org_context(db, org_id)
    restricted = role == Role.TEAM_MEMBER
    out: list[dict[str, Any]] = []
    for kind, (table, title, body, perm) in _SOURCES.items():
        if not has_permission(role, perm):
            continue
        scope = ""
        if restricted and kind == "project":
            scope = (
                " AND id IN (SELECT project_id FROM project_members WHERE org_id=:o AND user_id=:u)"
            )
        elif restricted and kind == "task":
            scope = " AND project_id IN (SELECT project_id FROM project_members WHERE org_id=:o AND user_id=:u)"
        sql = f"""
            SELECT id, {title} AS title,
                   ts_headline('english', {body}, websearch_to_tsquery('english', :q), 'MaxFragments=1,MaxWords=18,MinWords=6') AS snippet,
                   ts_rank(to_tsvector('english', {body}), websearch_to_tsquery('english', :q)) AS rank
            FROM {table}
            WHERE org_id = :o AND to_tsvector('english', {body}) @@ websearch_to_tsquery('english', :q){scope}
            ORDER BY rank DESC LIMIT :n
        """  # noqa: S608 — table/column expressions come from the fixed _SOURCES map, values are bound
        for r in db.execute(text(sql), {"o": org_id, "u": user_id, "q": q, "n": limit}):
            out.append(
                {
                    "type": kind,
                    "id": str(r.id),
                    "title": r.title,
                    "snippet": r.snippet,
                    "rank": float(r.rank),
                }
            )
    out.sort(key=lambda r: -r["rank"])
    return out[:limit]


_FILLER = frozenset(
    [
        "tell",
        "about",
        "what",
        "who",
        "where",
        "when",
        "how",
        "show",
        "find",
        "the",
        "and",
        "for",
        "with",
        "can",
        "you",
        "please",
        "give",
        "any",
    ]
)

_INTENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"overdue|late invoices|unpaid", re.I), "overdue"),
    (re.compile(r"attention|todo|what should i|needs me|urgent", re.I), "attention"),
    (re.compile(r"pipeline|open deals|forecast", re.I), "pipeline"),
    (re.compile(r"outstanding|receivable|owed", re.I), "outstanding"),
]


def _money(c: int) -> str:
    return f"{c / 100:,.2f}"


def ask(
    db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID, role: Role, question: str
) -> dict[str, Any]:
    can_report = has_permission(role, Perm.REPORT_READ)
    intent = next((name for pat, name in _INTENTS if pat.search(question)), None)
    if intent and can_report:
        if intent in ("overdue", "attention"):
            items = reporting.attention(db, org_id)
            if intent == "overdue":
                items = [i for i in items if i["kind"] == "invoice_overdue"]
            if not items:
                return {
                    "mode": "keyword",
                    "answer": "Nothing needs attention right now."
                    if intent == "attention"
                    else "No invoices are overdue.",
                    "sources": [],
                }
            lines = "\n".join(f"- {i['title']}" for i in items[:8])
            return {
                "mode": "keyword",
                "answer": lines,
                "sources": [
                    {"type": i["entity_type"], "id": i["entity_id"], "title": i["title"]}
                    for i in items[:8]
                ],
            }
        if intent == "pipeline":
            p = reporting.pipeline(db, org_id)
            open_ = [s for s in p["stages"] if s["stage"] not in ("won", "lost")]
            total = sum(s["value_cents"] for s in open_)
            parts = (
                ", ".join(
                    f"{s['stage'].replace('_', ' ')}: {s['deals']} ({_money(s['value_cents'])})"
                    for s in open_
                )
                or "no open deals"
            )
            win = f" Win rate {p['win_rate'] * 100:.0f}%." if p["win_rate"] is not None else ""
            return {
                "mode": "keyword",
                "answer": f"Open pipeline is {_money(total)} across {sum(s['deals'] for s in open_)} deals ({parts}).{win}",
                "sources": [],
            }
        o = reporting.overview(db, org_id)
        return {
            "mode": "keyword",
            "answer": f"{_money(o['outstanding_cents'])} is outstanding, of which {_money(o['overdue_cents'])} is overdue.",
            "sources": [],
        }

    # A question is not a boolean query: "tell me about acme" must match on 'acme' even
    # though no record contains 'tell'. OR the meaningful words; ts_rank orders the result.
    words = [
        w for w in re.findall(r"[\w@.-]+", question) if len(w) > 2 and w.lower() not in _FILLER
    ]
    hits = (
        search(db, org_id=org_id, user_id=user_id, role=role, q=" or ".join(words), limit=5)
        if words
        else []
    )
    if not hits:
        return {
            "mode": "keyword",
            "answer": "I couldn't find anything matching that.",
            "sources": [],
        }
    lines = "\n".join(f"- {h['type'].capitalize()}: {h['title']}" for h in hits)
    return {
        "mode": "keyword",
        "answer": f"Closest matches:\n{lines}",
        "sources": [{"type": h["type"], "id": h["id"], "title": h["title"]} for h in hits],
    }
