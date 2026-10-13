import hashlib

import pytest
from _ppl11a_lib import PRIYA, SAM
from _ppl11c_fs2_fake import FakeFirestore2
from _ppl11c_fs2_lib import ScriptedWriter, all_stamped_events, firestore_rig, fresh_token, new_instance
from _ppl11c_lib import WORK_ITEM_BODY
from pydantic import BaseModel
from test_PPL_11c_FS_2_event import _records, _same_part, _scripted
from tilo_api.people_limits_store import DurableLimits


def test_PPL_11c_FS_2_fingerprint_is_bound_to_principal_route_and_key():
    class Body(BaseModel):
        title: str

    body = Body(title="one identical body")
    fake = FakeFirestore2()
    limits = DurableLimits(fake, {})
    for user, route, key in [
        (PRIYA, "/v1/work-items", "one"),
        (SAM, "/v1/work-items", "one"),
        (PRIYA, "/v1/meetings", "one"),
        (PRIYA, "/v1/work-items", "two"),
    ]:
        limits.once(user, route, key, body, lambda: {"id": "wi_fp"}, now=1_000_000.0)
    fingerprints = [doc["fp"] for doc in fake.limiter_docs().values()]
    assert len(fingerprints) == len(set(fingerprints)) == 4
    assert hashlib.sha256(body.model_dump_json().encode()).hexdigest() not in fingerprints
    assert all(len(fp) == 64 for fp in fingerprints)


def test_PPL_11c_FS_2_replay_keeps_identical_bytes_when_firestore_reorders_maps(people_rig):
    def reverse_maps(value):
        if isinstance(value, dict):
            return {key: reverse_maps(item) for key, item in reversed(tuple(value.items()))}
        if isinstance(value, list):
            return [reverse_maps(item) for item in value]
        return value

    rig = firestore_rig(people_rig)
    key = fresh_token()
    first = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    for path, doc in rig.fake.docs.items():
        rig.fake.docs[path] = reverse_maps(doc)
    new_instance(rig)
    again = rig.client.post("/v1/work-items", json=WORK_ITEM_BODY, headers={"Idempotency-Key": key})
    assert again.status_code == 201 and again.content == first.content


@pytest.mark.parametrize("busy,reopen_error", [(True, False), (True, True), (False, False)])
def test_PPL_11c_FS_2_writer_reopens_only_busy_leases_and_keeps_retry_and_part_bounds(people_rig, busy, reopen_error):
    class WriterBusy(RuntimeError):
        pass

    class LeaseWriter(ScriptedWriter):
        held = True
        reopen_calls = 0

        def append(self, world_id, part):
            if self.held:
                self.attempts.append(dict(part))
                raise (WriterBusy if busy else RuntimeError)("unavailable")
            return super().append(world_id, part)

        def reopen(self):
            self.reopen_calls += 1
            if reopen_error:
                raise RuntimeError("unavailable")
            self.held = False

    rig, send = _scripted(people_rig, "create", [])
    rig.events = LeaseWriter(rig.event_store)
    before = _records(rig)
    response = send()
    _same_part(rig.events.attempts)
    if busy and not reopen_error:
        assert response.status_code == 201
        assert len(rig.events.attempts) == 2 and rig.events.reopen_calls == 1
        assert len(all_stamped_events(rig)) == 1
    else:
        assert response.status_code == 503 and response.json() == {"detail": "unavailable"}
        assert len(rig.events.attempts) == 3
        assert rig.events.reopen_calls == (3 if busy else 0)
        assert _records(rig) == before and all_stamped_events(rig) == []
