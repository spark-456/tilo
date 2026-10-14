"""A queued task retains one job through an answer burst and starts with the latest brief."""

import threading
from concurrent.futures import ThreadPoolExecutor

from test_FR_INT_06_approach_speed_prefetch import WAIT_S, _answered, _approach_calls
from tilo_api import tasks


def test_PREFETCH_BOUND_queued_edits_keep_one_job_and_skip_superseded_versions(flow, monkeypatch):
    started, release = threading.Event(), threading.Event()
    inner = flow.provider.generate

    def blocked(request):
        if "approaches" in (request.response_schema or {}).get("properties", {}):
            started.set()
            assert release.wait(WAIT_S)
        return inner(request)

    flow.provider.generate = blocked
    with ThreadPoolExecutor(max_workers=1) as executor:
        monkeypatch.setattr(tasks, "_PREFETCH", executor)
        first = _answered(flow)
        assert started.wait(WAIT_S)
        try:
            second = _answered(flow)
            for i in range(20):
                assert (
                    flow.answers(second, [], brief_edits={"goal": f"Compare supplier number {i}."}).status_code == 200
                )
            assert executor._work_queue.qsize() == 1
            assert _approach_calls(flow) == []
        finally:
            release.set()
        assert flow.approaches(first).status_code == 200
        assert flow.approaches(second).status_code == 200
    calls = _approach_calls(flow)
    assert len(calls) == 2
    assert "Compare supplier number 19." in calls[-1].prompt
