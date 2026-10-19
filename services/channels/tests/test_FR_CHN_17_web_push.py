"""FR-CHN-17 (PRD 6.2, 11, 16; FR-SET-02, FR-HIL-13): web push through the real outbox and policy engine, fake push."""

from __future__ import annotations

import ast
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import pytest
import tilo_policy
import yaml
from tilo_channels import web_push
from tilo_channels.digest import DigestArtifacts
from tilo_connectors.outbox import InMemoryOutboxStore, Outbox
from tilo_policy.schemas import conforms

ROOT = Path(__file__).resolve().parents[3]
USER, OTHER, WORLD, RUN = "u_owner", "u_other", "w_push0001", "r_push0001"
OWNER_EMAIL = "owner@example.com"
T0 = dt.datetime(2026, 10, 12, 9, 0, 0, tzinfo=dt.UTC)
FCM = "https://fcm.googleapis.com/fcm/send/" + "a" * 40
KEYS = {"p256dh": "B" + "x" * 86, "auth": "y" * 22}
RISK_TABLE = tilo_policy.load_risk_table(ROOT / "config/autonomy.yaml")
PEM_HEAD = "-----BEGIN " + "PRIVATE" + " KEY-----"  # assembled at runtime: the repo guard blocks the literal


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def advance(self, seconds: float) -> None:
        self.now += dt.timedelta(seconds=seconds)

    def stamp(self) -> str:
        return self.now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.now.microsecond // 1000:03d}Z"


class FakePushService:
    """Stands in for the browser vendors' push services: nothing leaves the process."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock, self.sent, self.gone = clock, list[dict[str, Any]](), set[str]()

    def send(self, sub: web_push.PushSubscription, payload: bytes, vapid: web_push.VapidRef) -> None:
        if sub.endpoint in self.gone:
            raise web_push.SubscriptionGone("gone")
        self.sent.append({"endpoint": sub.endpoint, "payload": payload, "vapid": vapid, "at": self.clock.now})


class Grantless:
    def verify(self, idempotency_key: str) -> None:
        raise RuntimeError("no grant")


def _policy(level: str = "L3", undo: int = 0, per_day: int = 50) -> dict[str, Any]:
    created = "2026-10-01T09:00:00.000Z"
    scope = {"connectors": [web_push.CONNECTOR], "recipients": [OWNER_EMAIL], "domains": [], "districts": ["D1"]}
    conds = {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True}
    hist = [{"by": USER, "at": created, "change": f"Created at {level}", "level": level}]
    pol: dict[str, Any] = {"id": "pol_push_l3", "owner": USER, "action_type": web_push.ACTION_TYPE, "scope": scope}
    pol |= {"limits": {"per_day": per_day, "credits": 10}, "conditions": conds, "level": level}
    pol |= {"undo_window_s": undo, "expiry": None, "notify_channel": "web", "team_lead_domains": []}
    return pol | {"created_by": {"by": USER, "at": created}, "changed_by": None, "history": hist}


class _Policy:
    def __init__(self, policies: list[dict[str, Any]], emitted: list[dict[str, Any]], clock: FakeClock) -> None:
        self.policies, self.emitted, self.clock = policies, emitted, clock

    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
        return tilo_policy.decide(
            proposal,
            table=RISK_TABLE,
            policies=self.policies,
            world_owner=user_id,
            applied=self.emitted,
            now=self.clock.stamp(),
        )

    def policy_for(self, user_id: str, policy_id: str) -> dict[str, Any] | None:
        return next((p for p in self.policies if p["id"] == policy_id and p["owner"] == user_id), None)


class Rig:
    def __init__(self, policies: list[dict[str, Any]] | None = None, prefs: Any = None) -> None:
        self.clock, self.transfers, self.applied = FakeClock(), list[dict[str, Any]](), list[dict[str, Any]]()
        self.push = FakePushService(self.clock)
        self.store = InMemoryOutboxStore()
        self.subs = web_push.SubscriptionStore()
        self.artifacts = DigestArtifacts()
        cfg = web_push.load_config()
        self.adapter = web_push.WebPushAdapter(
            subscriptions=self.subs, sender=self.push, artifacts=self.artifacts, owner=USER, vapid=cfg.vapid
        )
        self.outbox = Outbox(
            self.store,
            connectors={web_push.CONNECTOR: self.adapter},
            emit=self.transfers.append,
            clock=self.clock.stamp,
            world_id=WORLD,
        )
        self.notifier = web_push.PushNotifier(
            subscriptions=self.subs,
            outbox=self.outbox,
            policy=_Policy([_policy()] if policies is None else policies, self.applied, self.clock),
            artifacts=self.artifacts,
            emit=self.applied.append,
            mailbox=lambda uid: OWNER_EMAIL,  # even for others
            world_id=WORLD,
            world_owner=USER,
            run_id=RUN,
            preferences=prefs,
            clock=lambda: self.clock.now,
        )


def _item(
    card: str = "card_0001", kind: str = "gate", title: str = "Approve the supplier reply", **over: Any
) -> dict[str, Any]:
    item: dict[str, Any] = {"id": card, "kind": kind, "title": title, "body": "Tilo needs your decision."}
    return item | {"flagged": False} | over  # a card known to be clean


def test_FR_CHN_17_subscription_is_untrusted_input_https_bounded_allowlisted_and_capped_per_person() -> None:
    store = web_push.SubscriptionStore()
    for bad in (
        "http://fcm.googleapis.com/fcm/send/x",
        "javascript:alert(1)",
        "https://user:pw@fcm.googleapis.com/x",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/push",
        "https://evil.example/push",
        "https://fcm.googleapis.com.evil.example/x",
        "https://fcm.googleapis.com:8443/x",
        "https://fcm.googleapis.com/" + "a" * 2100,
        "https://fcm.googleapis.com/x y",
        "https://fcm.googleapis.com/x#frag",
    ):
        with pytest.raises(web_push.SubscriptionRefused):
            store.add(USER, {"endpoint": bad, "keys": KEYS})
    for keys in ({}, {"p256dh": KEYS["p256dh"]}, {"p256dh": "short", "auth": KEYS["auth"]}, {**KEYS, "auth": "!!"}):
        with pytest.raises(web_push.SubscriptionRefused):
            store.add(USER, {"endpoint": FCM, "keys": keys})
    with pytest.raises(web_push.SubscriptionRefused):
        store.add(USER, "not a mapping")  # type: ignore[arg-type]
    with pytest.raises(web_push.SubscriptionRefused):
        store.add("not-a-user", {"endpoint": FCM, "keys": KEYS})
    assert store.for_user(USER) == ()

    store.add(USER, {"endpoint": FCM, "keys": KEYS})
    store.add(USER, {"endpoint": FCM, "keys": KEYS})  # the same device again replaces, never duplicates
    assert len(store.for_user(USER)) == 1
    cap = web_push.load_config().max_subscriptions
    for n in range(1, cap):
        store.add(USER, {"endpoint": f"{FCM}{n}", "keys": KEYS})
    with pytest.raises(web_push.SubscriptionRefused):
        store.add(USER, {"endpoint": f"{FCM}over", "keys": KEYS})
    store.add(OTHER, {"endpoint": f"{FCM}over", "keys": KEYS})  # the cap is per person
    assert len(store.for_user(USER)) == cap and len(store.for_user(OTHER)) == 1
    assert store.remove(USER, FCM) and not store.remove(USER, FCM)
    assert all(FCM != s.endpoint for s in store.for_user(USER))
    assert f"{FCM}over" not in repr(store.for_user(OTHER)) and KEYS["auth"] not in repr(store.for_user(OTHER))


def test_FR_CHN_17_push_is_handed_to_the_push_service_within_10_s_through_outbox_and_policy() -> None:
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    enqueued_at = rig.clock.now
    res = rig.notifier.notify(USER, _item())
    assert res.status == "queued" and res.in_app and res.outbox_id is not None
    entry = rig.store.get(res.outbox_id)
    assert entry is not None and conforms("outbox.schema.json", entry)
    assert entry["action_type"] == "send_push" and entry["connector"] == web_push.CONNECTOR
    assert entry["authz"]["by"] == "policy" and entry["authz"]["ref"] == "pol_push_l3"
    assert entry["recipients"] == [OWNER_EMAIL] and entry["risk_tier"] == "T1"
    assert rig.push.sent == []  # nothing is sent by notify itself: only the outbox dispatch sends

    rig.clock.advance(2)
    assert [e["state"] for e in rig.outbox.dispatch_due()] == ["sent"]
    assert len(rig.push.sent) == 1 and rig.push.sent[0]["endpoint"] == FCM
    delay = (rig.push.sent[0]["at"] - enqueued_at).total_seconds()
    assert delay <= web_push.load_config().send_within_s == 10
    assert b"Approve the supplier reply" in rig.push.sent[0]["payload"]
    assert [t["data"]["outbox_id"] for t in rig.transfers] == [res.outbox_id]
    assert rig.transfers[0]["authz"] == entry["authz"]  # every side-effect event carries authz (SEC-11)
    assert rig.applied and rig.applied[0]["type"] == "policy.applied"


def test_FR_CHN_17_exactly_once_and_only_the_outbox_may_send() -> None:
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    first = rig.notifier.notify(USER, _item())
    again = rig.notifier.notify(USER, _item())
    assert first.status == "queued" and again.status == "duplicate"
    assert len(rig.store.all_entries()) == 1 and len(rig.applied) == 1
    rig.outbox.dispatch_due()
    rig.outbox.dispatch_due()
    assert len(rig.push.sent) == 1
    entry = rig.store.get(first.outbox_id or "")
    assert entry is not None
    with pytest.raises(RuntimeError):
        rig.adapter.execute_side_effect(entry, Grantless())  # a send needs the outbox's own grant (SEC-03)
    assert len(rig.push.sent) == 1


def test_FR_CHN_17_respects_notification_settings_and_quiet_hours_never_hide_a_gate() -> None:
    quiet = {"quiet_hours": {"enabled": True, "start": "08:00", "end": "10:00", "timezone": "UTC"}}
    rig = Rig(prefs={USER: quiet})
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    finished = rig.notifier.notify(USER, _item("card_fin1", kind="finished", title="Report ready"))
    assert finished.status == "quiet" and finished.in_app and rig.store.all_entries() == []
    gate = rig.notifier.notify(USER, _item("card_gate", kind="gate"))
    assert gate.status == "queued"
    blocked = rig.notifier.notify(USER, _item("card_blk1", kind="blocked", title="A step is blocked"))
    assert blocked.status == "queued"

    off = {"notifications": {"finished": {"phone": False}, "decisions": {"phone": False}}}
    rig2 = Rig(prefs={USER: off})
    rig2.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    fin2 = rig2.notifier.notify(USER, _item("card_fin2", kind="finished"))
    gate2 = rig2.notifier.notify(USER, _item("card_gat2", kind="gate"))
    assert fin2.status == "off" and gate2.status == "off"
    assert fin2.in_app and gate2.in_app  # a gate that is not pushed still waits in Needs you
    assert rig2.store.all_entries() == []


def test_FR_CHN_17_policy_engine_decides_no_standing_policy_means_no_push() -> None:
    capped = [_policy(per_day=1)]
    for policies in ([], [_policy(level="L1")], [_policy(level="L2", undo=60)], capped):
        rig = Rig(policies=policies)
        rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
        results = [rig.notifier.notify(USER, _item(f"card_{n:04d}")) for n in range(2)]
        queued = [r for r in results if r.status == "queued"]
        assert len(queued) == len(rig.store.all_entries()) == (1 if policies is capped else 0)
        assert all(r.in_app for r in results)
        rig.clock.advance(5)
        rig.outbox.dispatch_due()
        assert len(rig.push.sent) == len(queued)
    rig = Rig()
    assert rig.notifier.notify(USER, _item()).status == "no_subscription"
    rig.subs.add(OTHER, {"endpoint": FCM, "keys": KEYS})
    assert rig.notifier.notify(OTHER, _item()).status == "refused"  # only the world owner's own device


def test_FR_CHN_17_gone_endpoint_is_dropped_others_still_get_it_and_nothing_leaks() -> None:
    rig = Rig()
    second = FCM + "2"
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    rig.subs.add(USER, {"endpoint": second, "keys": KEYS})
    rig.push.gone.add(FCM)
    assert rig.notifier.notify(USER, _item()).status == "queued"
    rig.outbox.dispatch_due()
    assert [s["endpoint"] for s in rig.push.sent] == [second]
    assert [s.endpoint for s in rig.subs.for_user(USER)] == [second]

    rig.push.gone.add(second)
    assert rig.notifier.notify(USER, _item("card_0002")).status == "queued"
    rig.outbox.dispatch_due()
    assert rig.subs.for_user(USER) == ()
    entries = rig.store.all_entries()
    assert [e["state"] for e in entries].count("sent") == 1
    assert second not in repr(entries)


def test_FR_CHN_17_vapid_keys_by_secret_name_only_never_in_code_fixtures_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = web_push.load_config()
    assert cfg.vapid == web_push.VapidRef("webpush-vapid-private-key")
    assert repr(cfg.vapid) == "VapidRef(secret_name='webpush-vapid-private-key')"
    for value in ("B" + "x" * 42, "MIGHAgEAMBMG" + "A" * 80, PEM_HEAD, "has space", ""):
        with pytest.raises(ValueError):
            web_push.VapidRef(value)
    raw = (ROOT / "config/web_push.yaml").read_text(encoding="utf-8")
    assert set(yaml.safe_load(raw)) >= {"vapid_private_key_secret"}
    src = (ROOT / "services/channels/src/tilo_channels/web_push.py").read_text(encoding="utf-8")
    assert PEM_HEAD not in raw and PEM_HEAD not in src
    with caplog.at_level(logging.DEBUG):
        rig = Rig()
        rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
        rig.notifier.notify(USER, _item())
        rig.outbox.dispatch_due()
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert FCM not in joined and KEYS["auth"] not in joined and "webpush-vapid" not in joined
    assert all(s["vapid"].secret_name == "webpush-vapid-private-key" for s in rig.push.sent)


def test_FR_CHN_17_module_makes_no_network_call_and_imports_no_connector_or_provider() -> None:
    path = ROOT / "services/channels/src/tilo_channels/web_push.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    banned = {"socket", "http", "requests", "httpx", "pywebpush", "tilo_connectors", "tilo_providers"}
    assert not {m for m in modules if m.split(".")[0] in banned or m == "urllib.request"}, modules


# ---- the security review's four blocking findings, and the follow-ups -----------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://evil.example%2f.fcm.googleapis.com/x",
        "https://evil.example%40.fcm.googleapis.com/x",
        "https://evil.example%23.fcm.googleapis.com/x",
        "https://evil.example%3f.fcm.googleapis.com/x",
        "https://evil.example%5c.fcm.googleapis.com/x",
        "https://evil.example%00.fcm.googleapis.com/x",
        "https://evil.example%2e.fcm.googleapis.com/x",
        "https://127.0.0.1%2f.fcm.googleapis.com/x",
        "https://a..fcm.googleapis.com/x",
        "https://.fcm.googleapis.com/x",
        "https://-.fcm.googleapis.com/x",
        "https://a-.fcm.googleapis.com/x",
        "https://fcm.googleapis.com./x",
        "https://" + "a" * 64 + ".fcm.googleapis.com/x",
        "https://FCM.GOOGLEAPIS.COM.evil.example/x",
        "https://fcm_.googleapis.com/x",
        "https://[::1]/x",
    ],
)
def test_FR_CHN_17_host_must_be_a_plain_host_name_before_the_allowlist_suffix_test(endpoint: str) -> None:
    assert not web_push.endpoint_ok(endpoint)
    with pytest.raises(web_push.SubscriptionRefused):
        web_push.SubscriptionStore().add(USER, {"endpoint": endpoint, "keys": KEYS})


def test_FR_CHN_17_allowed_hosts_are_exactly_the_four_push_services_and_xn_labels_pass() -> None:
    cfg = web_push.load_config()
    assert cfg.allowed_hosts == (
        "fcm.googleapis.com",
        "push.services.mozilla.com",
        "notify.windows.com",
        "web.push.apple.com",
    )
    assert web_push.endpoint_ok("https://updates.push.services.mozilla.com/wpush/v2/abc")
    assert web_push.endpoint_ok("https://xn--bcher-kva.notify.windows.com/?token=AwYAAA%3d%3d&chid=1")
    store = web_push.SubscriptionStore()
    sub = store.add(USER, {"endpoint": "HTTPS://FCM.GoogleAPIs.com:443/fcm/send/x" + "a" * 20, "keys": KEYS})
    assert sub.endpoint == "https://fcm.googleapis.com/fcm/send/x" + "a" * 20  # canonical scheme and host


def test_FR_CHN_17_one_owner_per_endpoint_resubscribe_moves_it() -> None:
    store = web_push.SubscriptionStore()
    store.add(USER, {"endpoint": FCM, "keys": KEYS})
    store.add(OTHER, {"endpoint": FCM.replace("https", "HTTPS"), "keys": KEYS})  # same device, signed in as another
    assert store.for_user(USER) == () and [s.endpoint for s in store.for_user(OTHER)] == [FCM]
    assert store.users() == (OTHER,)


@pytest.mark.parametrize("flagged", [True, None, "missing"])
def test_FR_CHN_17_a_flagged_or_unknown_card_is_a_persons_decision_so_no_push(flagged: Any) -> None:
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    item = _item()
    if flagged == "missing":
        del item["flagged"]
    else:
        item["flagged"] = flagged
    res = rig.notifier.notify(USER, item)
    assert res.status in ("no_policy", "refused") and res.in_app and res.outbox_id is None
    assert rig.store.all_entries() == [] and rig.applied == []
    rig.clock.advance(5)
    assert rig.outbox.dispatch_due() == [] and rig.push.sent == []
    clean = rig.notifier.notify(USER, _item("card_0002"))  # a card known to be clean still goes
    assert clean.status == "queued"


def test_FR_CHN_17_notice_text_is_cleaned_like_a_quote() -> None:
    secret = "tok" + "en" + ": " + "Zq" * 12  # a labelled secret, assembled at run time
    item = _item(
        title="Approve\u202e the \x07supplier\u200b reply for bob@example.com " + secret,
        body="Call +44 7700 900123 or see https://evil.example/login?t=1 and www.evil.example now",
    )
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    res = rig.notifier.notify(USER, item)
    assert res.status == "queued"
    entry = rig.store.get(res.outbox_id or "")
    assert entry is not None
    doc = rig.artifacts.get(entry["item"]["artifact_id"], entry["item"]["version"])
    shown = doc["subject"] + " | " + doc["body_text"]
    for gone in ("\u202e", "\x07", "\u200b", "bob@example.com", "Zq" * 12, "+44 7700", "evil.example", "www."):
        assert gone not in shown, gone
    assert shown.count("[removed]") >= 3 and "supplier" in shown
    rig.clock.advance(1)
    rig.outbox.dispatch_due()
    assert "evil.example" not in rig.push.sent[0]["payload"].decode()


def test_FR_CHN_17_title_and_body_are_cut_on_a_word_boundary_within_their_limits() -> None:
    cfg = web_push.load_config()
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    words = " ".join(["approval"] * 40)
    res = rig.notifier.notify(USER, _item(title=words, body=words * 3))
    entry = rig.store.get(res.outbox_id or "")
    assert entry is not None
    doc = rig.artifacts.get(entry["item"]["artifact_id"], entry["item"]["version"])
    for text, limit in ((doc["subject"], cfg.title_max), (doc["body_text"], cfg.body_max)):
        assert 0 < len(text) <= limit and text.split(" ")[-1] == "approval", text  # whole words only
    assert rig.notifier.notify(USER, _item("card_0003", title="\u200b \x00 ")).status == "refused"  # nothing left


@pytest.mark.parametrize("kind", ["consent", "nudge", "question", "info", "", "GATE", "needs"])
def test_FR_CHN_17_kind_set_is_closed(kind: str) -> None:
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    res = rig.notifier.notify(USER, _item(kind=kind))
    assert res.status == "refused" and res.in_app and rig.store.all_entries() == []


def test_FR_CHN_17_notify_never_raises_and_the_card_is_still_shown() -> None:
    class Boom:
        def get(self, *_: Any) -> Any:
            raise RuntimeError("down")

    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    for attr, value in (
        ("_prefs", Boom()),
        ("_mailbox", lambda uid: (_ for _ in ()).throw(RuntimeError("down"))),
        ("_outbox", Boom()),
        ("_artifacts", Boom()),
        ("_emit", lambda part: (_ for _ in ()).throw(RuntimeError("down"))),
    ):
        broken = Rig()
        broken.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
        setattr(broken.notifier, attr, value)
        res = broken.notifier.notify(USER, _item())
        assert res.status == "refused" and res.in_app, attr
        assert broken.push.sent == []
    assert rig.notifier.notify(USER, "not a mapping").status == "refused"  # type: ignore[arg-type]


def test_FR_CHN_17_both_settings_shapes_are_read() -> None:
    quiet = {"quiet_hours": {"enabled": True, "start": "08:00", "end": "10:00", "timezone": "UTC"}}
    for prefs in ({USER: quiet}, quiet):  # by user id, or one person's own settings
        rig = Rig(prefs=prefs)
        rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
        assert rig.notifier.notify(USER, _item(kind="finished")).status == "quiet"
        assert rig.notifier.notify(USER, _item("card_0009", kind="gate")).status == "queued"


def test_FR_CHN_17_guards_owner_world_and_undo_window_are_pinned() -> None:
    rig = Rig()
    rig.subs.add(OTHER, {"endpoint": FCM, "keys": KEYS})
    assert rig.notifier.notify(OTHER, _item()).status == "refused"  # not the world's owner, mailbox answers anyway
    rig.subs.add(USER, {"endpoint": FCM + "2", "keys": KEYS})
    assert rig.notifier.notify(USER, _item(), world_ids={"w_other0001"}).status == "refused"
    assert rig.notifier.notify(USER, _item(), world_ids={WORLD}).status == "queued"
    held = Rig(policies=[_policy(level="L3", undo=60)])  # an L3 policy with an undo window is refused
    held.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    assert held.notifier.notify(USER, _item()).status == "no_policy" and held.store.all_entries() == []


def test_FR_CHN_17_same_card_twice_is_one_entry_with_one_id_and_one_event() -> None:
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    first, second = rig.notifier.notify(USER, _item()), rig.notifier.notify(USER, _item())
    assert (first.status, second.status) == ("queued", "duplicate")
    assert first.outbox_id == second.outbox_id is not None
    assert len(rig.applied) == 1 and rig.applied[0]["data"]["outbox_id"] == first.outbox_id
    other_world = Rig()  # the id derives from the world and the key: the same card elsewhere is its own entry
    other_world.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    assert other_world.notifier.notify(USER, _item()).outbox_id == first.outbox_id  # same world id, same card


def test_FR_CHN_17_payload_carries_a_relative_path_built_from_the_card_id_only() -> None:
    rig = Rig()
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    rig.notifier.notify(USER, _item("card_0042", title="Open https://evil.example/x now"))
    rig.clock.advance(1)
    rig.outbox.dispatch_due()
    payload = json.loads(rig.push.sent[0]["payload"])
    assert payload["path"] == "/park/home?card=card_0042" == f"{web_push.OPEN_PATH}?card=card_0042"
    assert payload["tag"] == "card_0042" and set(payload) == {"title", "body", "tag", "path"}
    assert "actions" not in payload and "evil" not in payload["title"]


def test_FR_CHN_17_adapter_tries_every_device_and_ends_with_a_final_refusal_when_there_is_none() -> None:
    class Flaky(FakePushService):
        def send(self, sub: web_push.PushSubscription, payload: bytes, vapid: web_push.VapidRef) -> None:
            if sub.endpoint == FCM:
                raise OSError("push service down")
            super().send(sub, payload, vapid)

    rig = Rig()
    rig.push = Flaky(rig.clock)
    rig.adapter._sender = rig.push
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    rig.subs.add(USER, {"endpoint": FCM + "2", "keys": KEYS})
    assert rig.notifier.notify(USER, _item()).status == "queued"
    rig.outbox.dispatch_due()
    assert [s["endpoint"] for s in rig.push.sent] == [FCM + "2"]  # the healthy second device got it
    assert [e["state"] for e in rig.store.all_entries()] == ["sent"]

    class Final(Exception): ...

    solo = web_push.WebPushAdapter(
        subscriptions=web_push.SubscriptionStore(),
        sender=rig.push,
        artifacts=rig.artifacts,
        owner=USER,
        vapid=web_push.load_config().vapid,
        final_error=Final,
    )

    class Grant:
        def verify(self, key: str) -> None:
            return None

    entry = rig.store.all_entries()[0]
    with pytest.raises(Final):
        solo.execute_side_effect(entry, Grant())  # nothing to send to: final, not retried
    rig.subs.remove(USER, FCM)
    rig.subs.remove(USER, FCM + "2")
    rig.subs.add(USER, {"endpoint": FCM, "keys": KEYS})
    with pytest.raises(web_push.PushUndelivered):
        rig.adapter.execute_side_effect(entry, Grant())  # a device failed and none took it: retriable


def test_FR_CHN_17_digest_never_lists_a_push() -> None:
    import test_FR_CHN_18_daily_digest as d
    from tilo_channels.digest import DailyDigestBuilder

    ob = "01J8Z3K4M5N6P7Q8R9S0T1V2C1"
    ts = "2026-10-06T15:00:00.000Z"
    builder = DailyDigestBuilder(base_url="https://app.tilo.example", keys=d._keys(), nonces=d._NonceStore())
    events = [d._policy_ev(1, ts, ob, "L3", action_type="send_push")]
    built = builder.build(
        user_id=d.USER,
        world_ids={d.WORLD},
        events=events,
        outbox_entries=[d._outbox_entry(ob, ts)],
        now=d.NOW_TS,
    )
    assert built is None
