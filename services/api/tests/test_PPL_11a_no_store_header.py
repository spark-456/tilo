"""PPL-11a: a people read is never cached (PE-22: no copy of a quote or a plate outlives the request). Every answer of
the three read routes, refusals included, carries `Cache-Control: no-store`.
"""

from __future__ import annotations

from _ppl11a_lib import PRIYA, fixture_case, own_item


def test_PPL_11a_PE_22_the_three_read_routes_answer_with_no_store_when_they_answer_and_when_they_refuse(people_rig):
    case = fixture_case("transcript", "valid", "assignee_reads_one_quote")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.add("work_items", own_item("wi_own", PRIYA))
    rig.as_user(PRIYA)
    answered = [
        rig.get("/v1/plate"),
        rig.get("/v1/work-items/wi_rate_sheet/quote"),
        rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "u0021"}),  # not hers: a 404
        rig.get("/v1/work-items/wi_nobody/quote"),
    ]
    assert [r.status_code for r in answered] == [200, 200, 404, 404]
    for response in answered:
        assert response.headers["cache-control"] == "no-store", response.request.url
    rig.unwire("people_stores")
    assert rig.get("/v1/plate").headers["cache-control"] == "no-store", "a 503 is not cached either"
