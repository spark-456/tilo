"""Shared builders for the T3 Treasury-ledger tests (FR-MTR-10, BQ-MTR10-4): fake Firestore, entries, the store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from _adr35_l2_fake import OccFirestore
from tilo_metering import LedgerEntry

ORG = "org_tilo"
ROOT = f"orgs/{ORG}/treasury_ledger"
AT = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)
OWNER, OTHER = "u_owner", "u_other"


class Flaky(OccFirestore):
    """The store, with an outage switch: every document and collection call raises while `broken`."""

    broken = False

    def document(self, path: str) -> Any:
        if self.broken:
            raise ConnectionError("firestore is unreachable")
        return super().document(path)

    def collection(self, path: str) -> Any:
        if self.broken:
            raise ConnectionError("firestore is unreachable")
        return super().collection(path)


def entry(run: str = "r_x", user: str = OWNER, credits: float = 4.0, step: str | None = "s1", **kw: Any) -> LedgerEntry:
    return LedgerEntry("commit", run, user, kw.pop("org", ORG), kw.pop("at", AT), step=step, credits=credits, **kw)


def entry_docs(db: Any) -> list[str]:
    """The paths of the entry documents (the audit record), not the rollups kept beside them (BQ-T3-5)."""
    return [p for p in db.docs if p.startswith(ROOT + "/")]


def make(db: Any) -> Any:
    from tilo_api.treasury_firestore import FirestoreTreasuryLedger

    return FirestoreTreasuryLedger(db, org_id=ORG)
