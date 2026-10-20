"""Imports every model so Alembic and tests see the complete metadata."""

from app.core.models import Base
from app.modules.billing import models as _billing  # noqa: F401
from app.modules.collab import models as _collab  # noqa: F401
from app.modules.crm import models as _crm  # noqa: F401
from app.modules.files import models as _files  # noqa: F401
from app.modules.identity import models as _identity  # noqa: F401
from app.modules.projects import models as _projects  # noqa: F401
from app.modules.proposals import models as _proposals  # noqa: F401
from app.modules.time import models as _time  # noqa: F401
from app.platform import audit as _audit  # noqa: F401
from app.platform import flags as _flags  # noqa: F401
from app.platform import idempotency as _idempotency  # noqa: F401
from app.platform import notifications as _notifications  # noqa: F401
from app.platform import webhooks as _webhooks  # noqa: F401

__all__ = ["Base"]
