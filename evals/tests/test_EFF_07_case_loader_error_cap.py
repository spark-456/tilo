"""Loader error-count cap (EFF-07; PR #35 note): the loader consumes and reports at most 20 schema errors."""

import jsonschema
import pytest
from conftest import write_case
from tilo_evals import CaseError, load_cases

_MANY = 2_000  # far beyond the 20-error cap


def test_EFF_07_load_cases_caps_schema_errors_reported_to_20(tmp_path, monkeypatch):
    write_case(
        tmp_path / "cases",
        case_id="E-PLAN-01",
        group="E-PLAN",
        ground_truth={"ok": True},
        scripted_answers=[0] * _MANY,  # each item is a schema error: "0 is not of type 'object'"
    )
    consumed = []
    real_iter_errors = jsonschema.Draft202012Validator.iter_errors

    def counting_iter_errors(self, *args, **kwargs):
        for error in real_iter_errors(self, *args, **kwargs):
            consumed.append(error)
            yield error

    monkeypatch.setattr(jsonschema.Draft202012Validator, "iter_errors", counting_iter_errors)
    with pytest.raises(CaseError) as info:
        load_cases(root=str(tmp_path / "cases"))
    assert str(info.value).count("is not of type") <= 20
    # deterministic, not timed: the loader must stop pulling errors once it has 20 (islice before sort)
    assert len(consumed) <= 21, f"loader consumed {len(consumed)} of {_MANY} schema errors"
