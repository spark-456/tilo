"""FR-MEM-05 (BQ-109, BQ-AGT02-T4-1, ADR-0018 T4): tilo-api's redactor seam returns the shared redactor, and dev mode
runs the same code as production.

Decision: `deps.get_redactor()` returns `tilo_redact.redact` itself (`is`), no longer `NotImplementedError`. Dev mode's
`dev_run.dev_redact` keeps its name and its `_refuse()` guard but delegates: its output must equal `redact`'s on every
kind of secret. A weaker dev stand-in would let dev and CI pass against a redactor production does not run, and the
store's AR-07 / MF-06 refusals ("the redactor would change this") would then differ between dev and production. A run
still does not start in production: `get_artifact_store` and `get_run_archive` keep refusing until ADR-0018 T8.
"""

from __future__ import annotations

import pytest
from _redact_samples_lib import FIXED_TAIL, KINDS, build
from tilo_api import deps, dev_run
from tilo_redact import redact


def test_FR_MEM_05_get_redactor_returns_the_shared_redactor_in_production():
    assert deps.get_redactor() is redact


def test_FR_MEM_05_the_artifact_store_seam_still_refuses_until_its_backend_exists():
    with pytest.raises(NotImplementedError):
        deps.get_artifact_store()


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_FR_MEM_05_dev_redact_gives_what_the_shared_redactor_gives(kind):
    text = f"note: {build(kind, FIXED_TAIL).text} end"
    assert dev_run.dev_redact(text) == redact(text)
