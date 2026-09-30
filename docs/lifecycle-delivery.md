# Lifecycle delivery contract (2026-09-30)

- `lifecycle` records the latest verified Assembly observation, including the official stage date.
- `hub_lifecycle_outbox` stores immutable pending event payloads before network delivery.
- `hub_lifecycle_receipts` records an identity/event/version-verified HUB acknowledgment only after durable event intent, queue registration (when eligible), and both sheet projections are confirmed.
- First observation already at committee referral is synchronized. A previous snapshot is not required.
- An unchanged active snapshot is reconciled with HUB once per KST day. New changes and pending retries run every scheduled collection.
- Missing HUB rows are acknowledged as NOT_REGISTERED without manufacturing historical new cards, and checked again the next day. NEW_BILL collection remains responsible for registration.
- HUB accepts repeated event keys idempotently. A lost HTTP response cannot create a second Telegram event. Older snapshots cannot regress a later HUB stage.
- MASTER text, judgments, reasons, judges and initial-card receipts are not overwritten by reconciliation.
- HUB freezes notification eligibility in ASSEMBLY_EVENTS columns H/I. X/unjudged events are recorded only; an interrupted eligible queue write can be retried from its saved intent.
- All Telegram release is through the existing central dispatcher, including initial-card/O+reason/tracking checks and working-day 07:30 cutoff.
- The monitoring workflow executes status collection even after NEW_BILL failure and commits pending state even after partial delivery failure. Failed runs remain visibly failed.
- The one-time reconciliation workflow uses the same production runner and concurrency group, requires the production receipt contract, and stores ordinary receipts. It does not send Telegram directly.

Regression: `python -m unittest test_notification_contract test_lifecycle_delivery`.
