"""Job handlers owned by the proposals module.

Design note on how a 'sent' proposal expires: rather than a periodic
cross-tenant sweep (which would need to bypass Row-Level Security to see
every org's data at once — a real tension, see the discussion this avoided
in queries.py's history), each proposal that gets a `valid_until` date
enqueues its OWN delayed expiry job at send time, scheduled via `run_after`.
The job carries its own `org_id`, so the handler sets RLS context exactly
the way every other service function does — no privilege escalation, no
special cross-tenant code path needed anywhere.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import set_org_context
from app.modules.proposals import queries
from app.modules.proposals.proposal_states import is_terminal
from app.platform import jobs


def _expire_proposal_if_overdue(payload: dict[str, Any], db: Session) -> None:
    org_id = uuid.UUID(payload["org_id"])
    proposal_id = uuid.UUID(payload["proposal_id"])
    set_org_context(db, org_id)

    proposal = queries.get_proposal(db, org_id, proposal_id)
    if proposal is None or proposal.status != "sent" or is_terminal(proposal.status):
        # Already accepted/rejected (or deleted, though proposals are never
        # hard-deleted) since this job was scheduled — nothing to do. This is
        # the normal, expected case for most of these jobs, not an error.
        return

    proposal.status = "expired"
    db.commit()


def register() -> None:
    jobs.register_handler("expire_proposal_if_overdue", _expire_proposal_if_overdue)
