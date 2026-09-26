"""Property tests for FR-INT-01 (limits are enforced atomically) and FR-INT-02 (the safety
screen's flag decision is deterministic in the extracted text), per the test-writer brief
("property tests for invariants"). See conftest.py's module docstring for the interface and
resolved ambiguities.
"""

from __future__ import annotations

from _planning_contracts_lib import INJECTION_PHRASE, make_docx_bytes, make_png_bytes
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_planning.intake import MAX_FILES, IntakeFile, IntakeRejected, IntakeRequest, submit_intake

settings.register_profile("fr_int", deadline=None)
settings.load_profile("fr_int")

_SAFE_TEXT = st.text(alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd", "Zs")), max_size=30)


@given(text_len=st.integers(min_value=1, max_value=4000), n_files=st.integers(min_value=0, max_value=10))
@settings(max_examples=15)
def test_FR_INT_01_within_limits_always_returns_one_status_per_file(safety_provider, text_len, n_files):
    files = [IntakeFile(filename=f"f{i}.png", content=make_png_bytes(size=16)) for i in range(n_files)]
    store = InMemoryArtifactStore()
    request = IntakeRequest(text="a" * text_len, files=files)

    result = submit_intake(request, safety=safety_provider, store=store)

    assert len(result.files) == n_files
    assert all(f.artifact["version"] == 1 for f in result.files)
    assert len(store.list_ids()) == n_files


@given(extra_files=st.integers(min_value=1, max_value=5))
@settings(max_examples=10)
def test_FR_INT_01_over_file_limit_always_rejected_nothing_stored(safety_provider, extra_files):
    n = MAX_FILES + extra_files
    files = [IntakeFile(filename=f"f{i}.png", content=make_png_bytes(size=16)) for i in range(n)]
    store = InMemoryArtifactStore()
    request = IntakeRequest(text="a task", files=files)

    try:
        submit_intake(request, safety=safety_provider, store=store)
        raised = False
    except IntakeRejected:
        raised = True

    assert raised, f"submitting {n} files (limit {MAX_FILES}) must always raise IntakeRejected"
    assert store.list_ids() == [], "a rejected submission must store nothing"


@given(prefix=_SAFE_TEXT, suffix=_SAFE_TEXT, inject=st.booleans())
@settings(max_examples=20)
def test_FR_INT_02_safety_flag_matches_injection_presence(safety_provider, prefix, suffix, inject):
    hidden = f"{prefix} {INJECTION_PHRASE} {suffix}" if inject else (f"{prefix} {suffix}".strip() or "nothing here")
    content = make_docx_bytes("cover text", hidden_text=hidden)
    store = InMemoryArtifactStore()
    request = IntakeRequest(text="a task", files=[IntakeFile(filename="f.docx", content=content)])

    result = submit_intake(request, safety=safety_provider, store=store)

    assert result.files[0].safety_flagged is inject
