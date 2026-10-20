"""Minimal email abstraction. Dev/test use a console/memory backend; a real
provider (Postgres-backed job + provider API) is added when billing/notifications
need it. Kept separate from the job queue so identity doesn't depend on platform.jobs
before that module exists.
"""

from app.core.config import get_settings

_sent: list[dict[str, str]] = []  # memory backend, tests inspect this


def send_email(*, to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_backend == "memory":
        _sent.append({"to": to, "subject": subject, "body": body})
        return
    print(f"[email:console] to={to} subject={subject!r}\n{body}")  # noqa: T201


def sent_emails() -> list[dict[str, str]]:
    return list(_sent)


def clear_sent_emails() -> None:
    _sent.clear()
