# Kora notes — provisional (Day 2)

**Status:** provisional. Live Kora sandbox credentials and webhook access were **not** available during this implementation. Everything below marked `[VERIFY]` must be confirmed against `sk_test_…` before the Day-2 staging exit (demo steps 3–6 with real sandbox money).

Recorded: 21 Nov 2026.

## Answers to K-1…K-8

| # | Check | Current position |
| --- | --- | --- |
| K-1 | Naira in / naira out and ×100 conversion | `[VERIFY]`. Code sends `str(kobo_to_naira(amount_kobo))` at initialize and compares `naira_to_kobo(verify.data.amount)` strictly against the requested kobo (`app/integrations/kora/provider.py:45`, `app/modules/payments/service.py:284`). No real sandbox response captured. |
| K-2 | `amount` accepts int and string | `[VERIFY]`. We send a decimal **string**; a captured sandbox response is still needed. |
| K-3 | Webhook HMAC canonicalisation | `[VERIFY]` against a real body. Both candidate strategies are implemented and unit-tested (`app/integrations/kora/signature.py`): compact canonical `data` JSON, and a JSON-decoder-based raw slice. The matched strategy is returned as `applied:raw` / `applied:canon` in `kora_webhook_events.outcome`. Malformed bodies (no `data`, invalid JSON) now return `400 VALIDATION_ERROR` instead of a 500. |
| K-4 | `charge.failed` fields | `[VERIFY]`. We map any `charge.failed` to `failure_reason='provider_declined'`; only the event name, reference and status are read. |
| K-5 | Per-charge `notification_url` override | `[VERIFY]`. `KORA_NOTIFICATION_URL` takes precedence over the route-supplied value when set. |
| K-6 | Failed/abandoned verify shape | `[VERIFY]`. The client reads only `data.status`; anything other than `success` becomes a failed payment, and missing `amount` becomes `amount_mismatch`. |
| K-7 | Fee bearer | **Retired by D-11**: the payer bears Kora's fee, the verified gross amount is credited, `data.fee` is retained in `raw_webhook` only and never enters arithmetic. |
| K-8 | Sandbox fake-success mechanism | `[VERIFY]`. Until confirmed, the local `DemoKoraProvider` simulates a signed `charge.success` webhook for development and integration tests. It is selected automatically when `KORA_SECRET_KEY` is empty and is refused in production unless `DEMO_MODE=true`. |

## Locally verified without Kora

- Demo provider initialize → checkout URL, signed webhook → server-side verify → gross amount credited, balance recomputed, settlement flag/event exactly once (`tests/integration/test_payment_webhook.py`, 9 tests against PostgreSQL at migration head).
- Webhook dedupe via `ON CONFLICT … DO NOTHING` with `RETURNING` (psycopg 3 reports no usable rowcount without `RETURNING` — fixed).
- Bad signature rows are recorded with `signature_ok=false` and `outcome='rejected'`; unknown references record `unknown_reference`, return 200 and move no money.
- Replay / overpayment / verified payment on a cancelled transaction are recorded with `review_reason` and never discarded or used to reopen a transaction.
- Reconciliation increments `payments.attempt_count` for still-pending charges and applies successful ones through the same idempotent `apply_verified_charge` path.

## Captured payloads

No live Kora payloads were captured. Once credentials are available, capture and paste here:

1. Initialize request + response for ₦1,500 (K-1, K-2, K-5).
2. Verify response for a successful charge (K-1, K-6).
3. Raw webhook body + `x-korapay-signature` header (K-3); note which strategy matched.
4. `charge.failed` webhook and verify response (K-4, K-6).
5. Screenshot or recording of the sandbox "simulate success" control (K-8).

## Implementation deviations from the architecture document

| Item | Position |
| --- | --- |
| `integrations/kora/client.py` | Contains only `get_kora_provider()`; initialize/verify live in `provider.py` behind a `KoraProvider` protocol (real + demo implementations). |
| `integrations/kora/schemas.py`, `modules/payments/schemas.py` | Not created; provider payloads are typed as `dict[str, Any]` at the boundary and validated by the payment service. |
| Demo webhook signing secret | Falls back to a dedicated fixed constant (`DEMO_WEBHOOK_FALLBACK_SECRET`), **not** `JWT_SECRET_KEY`. Set `KORA_DEMO_WEBHOOK_SECRET` explicitly to override. |
| `KORA_DEMO_MODE` vs `DEMO_MODE` | `KORA_DEMO_MODE` selects the simulated provider. `DEMO_MODE` is the separate production sandbox exception (§13.3). `.env.example` sets both explicitly to avoid accidental demo mode. |
| Startup checks | `SELECT 1` now runs in every environment with a "Cannot reach database" failure; `APP_URL` is validated as a strict https origin outside development. `/health/ready` was pulled forward into `app/main.py` (200/503) with unit tests. |
| Public rate limiting | Keyed by client IP via `core/rate_limit.py`, not per public token as §6.7.4 suggests. MVP deviation. |
| `attempt_count` | Added in migration `0010_payment_attempt_count`; the Day-1 payments migration omitted it. |
| PDF receipts | Implemented ahead of Day 3/4; gated by `RECEIPT_PDF_ENABLED`. |
| Reconciliation scope | Internal `references` filter added so an operational run can target selected payments; default behaviour is unchanged. |
