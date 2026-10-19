"""CL-LIVE-2 property: whatever the approval attempts are, no real write (draft, send or save) reaches Google unless a
person typed `yes` at an interactive terminal for exactly that payload. Fakes only; API pinned in API_CL_LIVE_2.md."""

from __future__ import annotations

from _cl_live2_lib import clean_process_env, make_write_env, socket_guard  # noqa: F401
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ATTEMPTS = st.lists(
    st.tuples(st.sampled_from(["", "y", "n", "no", "yes ", "YES", "yes", "ok", "Yes!"]), st.booleans()), max_size=4
)


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture]
)
@given(action=st.sampled_from(["create_draft", "send_email", "save_file"]), attempts=ATTEMPTS, other=st.booleans())
def test_CL_LIVE_2_no_write_runs_without_a_typed_yes_at_a_terminal(action, attempts, other):
    g = make_write_env(send=True)
    g.build(allow_send=True)
    case = g.drive_case() if action == "save_file" else g.mail_case(action)
    elsewhere = g.mail_case("create_draft", recipients=("else@example.net",))
    typed = False
    for said, interactive in attempts:
        # an approval of ANOTHER payload (when `other`) must never cover this one
        target = elsewhere if other else case
        typed |= g.approve(target, said=said, interactive=interactive) and not other
    g.run(case)

    wrote = bool(g.apis.writes())
    if typed:
        assert g.state(case) == "sent" and len(g.apis.writes()) >= 1
    else:
        assert not wrote and g.state(case) == "failed" and g.apis.requests == []
