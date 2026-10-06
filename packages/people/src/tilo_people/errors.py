"""Errors of `tilo_people` (API.md "Errors").

`str(e)` names a kind, a record id and versions, nothing else: never record text (titles, names, aliases,
emails, due phrases). Callers pass ids and counts only.
"""

from __future__ import annotations


class PeopleError(Exception):
    """Base class of every error this package raises on purpose."""


class PeopleInputError(PeopleError, ValueError):
    """A malformed argument to a store, an adapter or `resolve_due`."""


class AlreadyExists(PeopleError):
    """create: `(org_id, id)` is taken."""


class NotFound(PeopleError):
    """replace or delete: there is no such `(org_id, id)`."""


class VersionConflict(PeopleError):
    """replace or delete: `expected_version` is not the current version."""
