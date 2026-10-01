"""FR-CON-07 property tests (PRD 12.3, SEC-09): invariants of the egress allowlist for ANY host
label, not just the hand-picked ones in test_FR_CON_07_egress_policy.py.

Invariants: a host is allowed only if it is the exact entry or lies below an explicit "*.parent"
rule; no prefix or suffix glued onto an allowlisted name ever passes; any userinfo blocks; the
decision log has exactly one entry per check, and blocked implies logged; checks are
deterministic.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

LABEL = (
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12)
    .filter(lambda s: not s.startswith("-") and not s.endswith("-") and "--" not in s)
    .filter(lambda s: not s.startswith("xn"))
)
USERINFO = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=10)


def policy():
    from tilo_browser.egress import EgressPolicy

    return EgressPolicy(allow=["example.com", "*.cdn.example.org"])


@given(prefix=LABEL)
@settings(max_examples=60, deadline=None)
def test_FR_CON_07_no_prefix_glued_onto_an_allowlisted_host_passes(prefix):
    p = policy()
    assert p.check(f"https://{prefix}example.com/").allowed is False
    assert p.check(f"https://{prefix}cdn.example.org/").allowed is False
    assert p.check(f"https://{prefix}.example.com/").allowed is False  # exact entries have no subdomains


@given(suffix=LABEL, tld=LABEL)
@settings(max_examples=60, deadline=None)
def test_FR_CON_07_no_suffix_glued_after_an_allowlisted_host_passes(suffix, tld):
    p = policy()
    assert p.check(f"https://example.com.{suffix}/").allowed is False
    assert p.check(f"https://example.com.{suffix}.{tld}/").allowed is False
    assert p.check(f"https://a.cdn.example.org.{suffix}/").allowed is False


@given(sub=LABEL, sub2=LABEL)
@settings(max_examples=60, deadline=None)
def test_FR_CON_07_an_explicit_subdomain_rule_matches_any_depth_below_its_parent_only(sub, sub2):
    p = policy()
    assert p.check(f"https://{sub}.cdn.example.org/x").allowed is True
    assert p.check(f"https://{sub}.{sub2}.cdn.example.org/x").allowed is True
    assert p.check("https://cdn.example.org/x").allowed is False


@given(user=USERINFO, password=USERINFO)
@settings(max_examples=60, deadline=None)
def test_FR_CON_07_any_userinfo_blocks_even_an_allowlisted_host(user, password):
    p = policy()
    assert p.check(f"https://{user}@example.com/").allowed is False
    assert p.check(f"https://{user}:{password}@example.com/").allowed is False
    assert p.check(f"https://example.com@{user}.net/").allowed is False


@given(labels=st.lists(LABEL, min_size=1, max_size=4), allowed_first=st.booleans())
@settings(max_examples=60, deadline=None)
def test_FR_CON_07_every_check_logs_exactly_one_decision_and_blocked_implies_logged(labels, allowed_first):
    p = policy()
    urls = [f"https://{'.'.join(labels)}.net/"] + (["https://example.com/"] if allowed_first else [])
    for i, u in enumerate(urls, start=1):
        p.check(u)
        assert len(p.decisions) == i
    assert p.blocked == [d for d in p.decisions if not d.allowed]
    assert all(d.reason != "allowed" for d in p.blocked)


@given(host=st.lists(LABEL, min_size=1, max_size=4).map(".".join))
@settings(max_examples=60, deadline=None)
def test_FR_CON_07_the_decision_is_deterministic(host):
    url = f"https://{host}.example.org/p"
    a, b = policy().check(url), policy().check(url)
    assert (a.allowed, a.reason, a.host) == (b.allowed, b.reason, b.host)
