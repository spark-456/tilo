"""CL-LIVE-1 security follow-ups: no attribute path from a read-only wrapper leads to the raw adapter (whose `watch`
is a POST), and `is_real_read_only` accepts only what `real_adapters` built. API: API_CL_LIVE_1.md."""

from __future__ import annotations

import pytest
from _cl_live_lib import GOOGLE_CONNECTORS, make_real_env, real
from _cl_live_lib import clean_process_env as clean_process_env  # autouse fixture
from _cl_live_lib import socket_guard as socket_guard  # autouse fixture


def test_CL_LIVE_1_no_attribute_path_leads_from_a_wrapper_to_a_raw_adapter_or_its_post_methods():
    from tilo_connectors.adapters import CalendarAdapter, DriveAdapter, GmailAdapter

    g = make_real_env()
    adapters = g.build()
    assert not hasattr(adapters["gmail"], "_inner")
    for connector_id in GOOGLE_CONNECTORS:
        wrapper = adapters[connector_id]
        for name, member in vars(type(wrapper)).items():
            assert not hasattr(member, "__wrapped__"), name  # a `wraps` of a bound method would carry `__self__`
        assert not any(isinstance(v, GmailAdapter | DriveAdapter | CalendarAdapter) for v in vars(wrapper).values())
        # the only way to the inner adapter is a closure cell, which no attribute path reaches
        for name in dir(wrapper):
            if name.startswith("__"):
                continue
            value = getattr(wrapper, name)
            assert not isinstance(value, GmailAdapter | DriveAdapter | CalendarAdapter), name
            assert not hasattr(value, "__self__") or not isinstance(
                value.__self__, GmailAdapter | DriveAdapter | CalendarAdapter
            ), name
    assert not hasattr(adapters["gmail"], "watch") and not hasattr(adapters["gmail"], "stop_watch")


def test_CL_LIVE_1_reads_still_work_through_the_closure_and_stay_get_only():
    g = make_real_env()
    gmail = g.build()["gmail"]

    from _oauth_lib import OWNER

    assert gmail.list_threads(OWNER, max_results=5)["threads"]
    assert {r.method for r in g.transport.requests} == {"GET"}


def test_CL_LIVE_1_is_real_read_only_accepts_what_real_adapters_built_and_nothing_else():
    from tilo_api import dev_run

    g = make_real_env()
    built = g.build()
    is_real = real().is_real_read_only

    assert is_real(built) is True
    assert is_real(None) is False
    assert is_real({}) is False
    assert is_real(dev_run.mock_adapters()) is False
    assert is_real({k: v for k, v in built.items() if k != "gmail"}) is False
    assert is_real([built]) is False


@pytest.mark.parametrize("connector", GOOGLE_CONNECTORS)
def test_CL_LIVE_1_is_real_read_only_refuses_a_google_id_that_is_a_mock(connector):
    from tilo_api import dev_run

    g = make_real_env()
    mixed = {**g.build(), connector: dev_run.mock_adapters().get(connector) or object()}

    assert real().is_real_read_only(mixed) is False
