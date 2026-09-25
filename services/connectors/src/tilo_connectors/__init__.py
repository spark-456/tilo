"""tilo_connectors — the outbox: the only path to a side effect (SEC-03, PRD 12.1). Public API:
services/connectors/tests/API.md."""

from .errors import MissingGrant as MissingGrant
from .errors import OutboxRefused as OutboxRefused
from .outbox import Outbox as Outbox
from .store import InMemoryOutboxStore as InMemoryOutboxStore
