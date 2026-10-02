# `tilo_channels`: public API pinned by the FR-CHN-04 tests

FR-CHN-04: task-scoped WhatsApp bot with refusal for off-topic requests. Acceptance (PRD 11.6): "Eval set of
30 off-topic messages: 100% redirected"; the set is E-CHN in `evals/cases/E-CHN/` (PRD 19.2), read directly
by the tests. Sources: PRD 11.1 (task scope, one-line reply pointing to the web app, truthful about being
automated), 13.2 (raw archive), 16.1 rule 4 and 16.3 rule 1 (untrusted text is data; secrets never in
prompts, logs or the archive), SEC-06 (T3 PIN), 6.4 / PL-01 (models only through `tilo_providers`), 9.4;
contracts `event.schema.json`, `events/data/channel.message_in.schema.json`, `events/registry.yaml`;
issue #156 (PIN-shaped text on the free-text route). Tests: `test_FR_CHN_04_off_topic.py`; doubles:
`_chn04_lib.py` (plus `_chn_0305_lib.py`, `_channels_lib.py`). Everything not listed here is unchanged from
`API_FR_CHN_03_05.md`.

## `tilo_channels.inbound` (additive)

```python
@dataclass(frozen=True)
class RouteResult:
    route: str   # "opt_in" | "keyword" | "card" | "off_topic" | "failed"   ("unhandled" is gone)

def off_topic_text(web_url: str) -> str
    # The redirect: one line (no newline), contains web_url, says Tilo is automated ("automated", never
    # "not automated"), differs from opt_in_text(web_url).

class InboundRouter:   # constructor unchanged; no new required argument
    def handle(self, message: InboundMessage) -> RouteResult
```

Behaviour, for a sender with a valid binding: the keyword handler first, then the card handler (a result
other than `ignored` is route `card`); every other message, of any kind (text, empty or missing text, image,
document, video, sticker, location, contacts, interactive without a reply-button id), is route `off_topic`:

- exactly one reply, to the sender only, equal to `off_topic_text(web_url)`: the same fixed line for every
  message, so it never echoes the message, the PIN or any number or address in it;
- nothing else: no keyword effect, no card answer, no PIN check, no card send, no event part, no archive
  record, no send to any number or address named in the text, no model, safety, speech or search call
  (nothing reaches `tilo_providers`);
- logs never contain the body or the full number; a failing send is logged by exception type and never
  raises (route stays `off_topic`);
- behind the signed webhook, a redelivered wamid is `duplicate` and gets no second reply (FR-CHN-02).

Unbound senders are unchanged: the opt-in instructions only (FR-CHN-03).

PIN-shaped text (security reviews of #158, #159, #169): after a correct PIN, after the 600 s window (PIN
window 300 s + `pin_late` grace 300 s, BQ-89), during the grace window when not plain ASCII digits (spaced
"12 34 56", dashed, "PIN 123456", trailing dot, full-width digits), after the prompt's one try is spent, or
with no prompt at all: exactly one reply that contains neither the text nor the PIN nor any 4+ digit run of
the PIN; no PIN check, no card answer, no event; the text and the PIN never appear in the archive, an event,
a log or a provider call. The route is not pinned (`off_topic`, or `card` if cards consumes it as late).

## Defaults the PRD leaves open (to log in `docs/open-questions.md`; the test-writer took no BQ id)

1. Off-topic is decided deterministically: whatever no in-scope handler takes. Email-reply instructions
   (FR-CHN-10) and task start or status (PRD 11.1) are not built; when they are, they take their messages
   before this route. No model classifies messages, so no message (and no PIN) reaches a model here.
2. One fixed line for every off-topic message, which also says Tilo is automated: that answers "are you a
   bot?" truthfully (PRD 11.1) without classifying the question.
3. No event and no archive record for an off-topic message: it belongs to no world or run, and event parts
   and `archive_ref` (`r_<run>/<seq>`) are per run. A `channel.message_in` with `option` null from WhatsApp
   is also the shape of an owner's L2 instruction (OB-01), so none is written for chatter. PRD 13.2 says the
   archive holds every inbound channel message; a run-less record would need a contract change.
4. One reply per message (as BQ-89 for the opt-in reply); a per-number limiter, if added later, must be
   optional, as `opt_in_allowed` is. Reactions and audio (FR-CHN-16 voice notes) are not pinned.
