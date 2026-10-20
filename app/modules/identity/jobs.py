"""Job handlers owned by the identity module, plus their registration.

Importing this module has the side effect of registering its handlers with
app.platform.jobs — see app/main.py, which imports it once at startup so the
worker (or an in-process `run_worker_once` call) can dispatch to it.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.platform import jobs
from app.platform.email import send_email


def _send_invite_email(payload: dict[str, Any], _db: Session) -> None:
    send_email(
        to=payload["email"],
        subject=f"You've been invited to join {payload['org_name']} on AgencyOS",
        body=(
            f"You've been invited to join {payload['org_name']} as a "
            f"{payload['role'].replace('_', ' ')}.\n\n"
            f"Accept your invite: {payload['accept_url']}"
        ),
    )


def _send_password_reset_email(payload: dict[str, Any], _db: Session) -> None:
    send_email(
        to=payload["email"],
        subject="Reset your AgencyOS password",
        body=(
            "A password reset was requested for your AgencyOS account.\n\n"
            f"Reset your password: {payload['reset_url']}\n\n"
            "This link is single-use and expires shortly. If you did not request it, "
            "you can safely ignore this message."
        ),
    )


def register() -> None:
    jobs.register_handler("send_invite_email", _send_invite_email)
    jobs.register_handler("send_password_reset_email", _send_password_reset_email)
