"""Domain-event emission. Services call `emit()` inside their business transaction
(before commit) so that webhooks and real-time notifications are produced if and
only if the change commits. Implemented in full once webhooks exist; see
app.platform.webhooks."""

import uuid
from typing import Any

from sqlalchemy.orm import Session


def emit(db: Session, *, org_id: uuid.UUID, event_type: str, data: dict[str, Any]) -> None:
    from app.platform import webhooks  # local import: webhooks imports jobs, not services

    webhooks.fan_out(db, org_id=org_id, event_type=event_type, data=data)
