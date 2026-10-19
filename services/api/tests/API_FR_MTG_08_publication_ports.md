# FR-MTG-08 publication guards

The publication ports recheck before each delegation and expose no dispatch method.
They require already scoped inner ports; they do not grant scope or approval.
Firestore cards/stops accept an optional `before_publication` hook, called after
document lookup and immediately before mutation. Source refusals retain their status.
The production factory must pass M2's fresh source/CAS hook into these adapters.
There is no transaction across meeting/card/outbox stores: deletion during an SDK
write still requires retention/erasure integration. These helpers activate no route.
