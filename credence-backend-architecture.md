# Credence MVP — Backend Architecture & Technical Design

**Status:** Revised (v2) for final review — no implementation code written yet
**Owner:** Backend engineering
**Audience:** Backend engineer(s) implementing Credence MVP, reviewer approving the design
**Source of truth:** *Credence MVP Product Requirements Document (v2)*, 17 Nov 2026
**Existing codebase:** `fola-exe/credence-back-end` @ `master` (FastAPI, SQLAlchemy 2.x, Alembic, PostgreSQL)
**Prepared:** 17 Nov 2026

---

## How to read this document

The PRD is authoritative. Where this document goes beyond it, the addition is labelled:

| Marker | Meaning |
| --- | --- |
| **[PRD]** | Stated in the PRD. Not open for redesign. |
| **[REC]** | My technical recommendation where the PRD is silent or leaves a technical choice open. **Requires your review/approval.** |
| **[CONFLICT]** | The PRD's assumption does not match the existing codebase. Resolved with a proposal; flagged in §2.4 and §16. |
| **[VERIFY]** | Must be confirmed against a live system (Kora sandbox, Resend, hosted DB) before relying on it. |
| **[DECIDED v2]** | A point you decided while reviewing v1. The design follows the decision and it is no longer open. |

Sections 1–16 map one-to-one to your requested output structure. Diagrams are Mermaid and are placed next to the specification they describe, not in an appendix.

---

## Revision log — v2

**What changed and why.** v1 was a complete design with twelve open questions. You reviewed it, approved eleven decisions and identified three technical inconsistencies — reminder scheduling for already-overdue transactions, concurrent-payment/overpayment safety, and business-level traceability. This version folds all of that in. **Nothing was redesigned.** Section numbering, the route list, the table list and the ADR numbers are unchanged, so every cross-reference you read in v1 still resolves; the schema changes are additive columns and one index.

### Approved decisions

| # | Your decision | Implemented in | v1 state |
| --- | --- | --- | --- |
| **D-1** | Keep `created_by_business_id`; the authenticated business comes from the JWT | §5.3.3, ADR-15, Q-1 closed | recommended, pending |
| **D-2** | Plaintext public token, fenced by HTTPS, log redaction, `no-store`, `no-referrer`, single-transaction scope; rotation/revocation documented as future work | §11.4, §6.7.0, §11.10, ADR-7 | recommended, pending |
| **D-3** | A successful payment on a `cancelled` transaction is recorded, the status stays `cancelled`, and the payment is flagged for investigation/refund | §8.6, §8.9.4, `payments.review_reason`, ADR-18, Q-7 closed | open question |
| **D-4** | Idempotency keys on payment attempts | §5.3.4, §6.7.3, §8.8, ADR-16, Q-9 closed | recommended, pending |
| **D-5** | Receipt balance computed when the receipt is opened, and labelled as the balance *now*, not at payment time | §8.10.2, §8.10.3, ADR-12 | chosen, now explicit |
| **D-6** | Score Option A: promises alone never produce a number; `No history yet` with promise facts beside it | §10.4, §10.6, Q-8 closed | recommended, pending |
| **D-7** | No logo upload in the MVP; keep the `logo_url` column only | §2.2, §4.4, §5.3.1, §15.6, Q-3 closed | open question |
| **D-8** | Unknown Kora reference: record the event, return 200, change no money | §6.8.1, §8.14, Q-11 closed | recommended, pending |
| **D-9** | Business-level activity (credit-limit changes) stays out of `transaction_events`; no new table in the MVP | §11.9, §6.3.2, ADR-21, Q-5 closed | open question |
| **D-10** | Sandbox Kora credentials allowed in the deployed demo only, fenced and visibly marked | §13.2, §13.3, §13.7, §11.10, ADR-20 | unsafe single flag in v1 |
| **D-11** | Credit the verified **gross** amount; Kora's fee is borne by the payer and never deducted | §2.4, §8.1, §8.4, §8.6, ADR-17 | unresolved (K-7/Q-12) |

### Technical corrections

| # | Correction | Sections touched |
| --- | --- | --- |
| **C-A** | An already-overdue transaction receives exactly one reminder at **09:00 WAT on the next day**, from one function used by creation, rebuild, dispute resolution, promise expiry and the tick | §9.3.1, §9.3.2, §9.3.3, §9.5.2, §9.9, §12.10 |
| **C-B** | Concurrent payments: fixed lock order, single-application guard, verified-sum recompute inside the lock, one settlement side-effect set, deterministic two-winner overpayment, flag-never-discard | §5.7.5, §8.6, §8.6.2, §8.9.3, §11.11, §12.11 |
| **C-C** | Business-level changes are traceable through a structured durable audit log line plus `businesses.updated_at`; a dedicated table is documented as deferred | §11.9, ADR-21, §16.3 |

---

## Table of contents

1. [Executive Summary](#1-executive-summary)
2. [Requirements and Scope Analysis](#2-requirements-and-scope-analysis)
3. [System Architecture](#3-system-architecture)
4. [Backend Project Structure](#4-backend-project-structure)
5. [Database Architecture](#5-database-architecture)
6. [API Specifications](#6-api-specifications)
7. [Service Layer Design](#7-service-layer-design)
8. [Payment Integration](#8-payment-integration)
9. [Background Jobs and Notifications](#9-background-jobs-and-notifications)
10. [Repayment Score Engine](#10-repayment-score-engine)
11. [Security and Reliability](#11-security-and-reliability)
12. [Testing Strategy](#12-testing-strategy)
13. [Deployment and Environment Configuration](#13-deployment-and-environment-configuration)
14. [Architecture Decision Records](#14-architecture-decision-records)
15. [MVP Implementation Roadmap](#15-mvp-implementation-roadmap)
16. [Risks, Dependencies, and Open Questions](#16-risks-dependencies-and-open-questions)

---

# 1. Executive Summary

## 1.1 What is being built

A **modular monolith** HTTP API that turns a credit sale into a collectable, evidenced, scored debt. Everything the demo story in PRD §2 needs is served by one deployable unit (`api`) plus one small companion process (`worker`) that runs scheduled jobs. Both share one codebase, one configuration surface and one PostgreSQL database.

Three data flows define the system:

1. **Recording debt** — a creditor records a credit transaction; the server re-checks capacity, issues a human reference (`CRD-000123`) and a public bearer token, writes the reminder schedule, and notifies the debtor.
2. **Recovering debt** — the debtor opens an authenticated-by-token page, acknowledges, promises, disputes, or pays through Kora. **Only a server-verified Kora charge reduces the balance.** Webhooks are hints; the verify call is the authority.
3. **Explaining debt** — every material action appends to `transaction_events`. That table is simultaneously the UI timeline and the audit trail, and the repayment score is derived from it plus verified payments.

## 1.2 The five load-bearing design decisions

| # | Decision | Why it matters here |
| --- | --- | --- |
| 1 | **Balances, capacity, display status and score are computed on read** from `payments` + `credit_transactions`. Nothing denormalises money. | Impossible to have a "stale balance" incident. Reversals/overpayments/duplicates are self-correcting on the next read. Cost is a cheap aggregate query, not a correctness risk. |
| 2 | **`payments` is the single source of monetary truth; webhooks only trigger a verification.** | A forged or replayed webhook, a frontend redirect, or a Kora console retry cannot move a balance. The only writer of `successful` is the verify path, and it credits the provider's verified **gross** amount (the payer bears Kora's fee — §8.4). |
| 3 | **`reminders` is a durable, introspectable schedule table, drained by a 15-minute job using `FOR UPDATE SKIP LOCKED`.** | Reminders survive restarts, are visible in the API ("next reminder"), reschedule for promises/disputes by row status change, and never double-send across overlapping ticks. |
| 4 | **`transaction_events` is append-only and written inside the same DB transaction as the change it describes.** | The timeline can never disagree with the money. Dispute resolution, cancellation and payment application are all atomic with their evidence. |
| 5 | **One money module owns every kobo calculation** (`app/core/money.py` + `app/modules/transactions/balance.py`). | No two endpoints can disagree about what "outstanding" means. Integer kobo in the DB, in the API, and inside the process; naira conversion exists only at the Kora boundary and at HTML rendering. |

## 1.3 Findings from the existing codebase that shape the design

I read the repository before designing. Five findings change the plan compared with a greenfield build:

1. **Authentication is business-scoped, not user-scoped.** `POST /auth/login` issues a JWT whose `sub` is `businesses.id`; `get_current_business()` loads a `Business`. There is **no `users` table**. The PRD's `created_by FK users` therefore cannot be implemented as written — see **[CONFLICT-1]** in §2.4.
2. **`app/models/debtor.py` exists but is not usable and has no migration.** It has no `business_id`, `name`, `contact_person`, `credit_limit_kobo` or `address`; it marks `email` globally unique (PRD requires uniqueness per business); and it contains a broken import (`from mixins import BaseMixin`, which will fail outside the package). No migration creates `debtors`, so the hosted database almost certainly has no such table. This is an asset, not a setback: the real table can be created by migration with no data migration.
3. **The error envelope does not exist yet.** Auth routes raise `HTTPException(detail="...")`. The PRD mandates `{"error": {"code", "message", "fields"}}`. One global exception handler must normalise both, or the frontend will need two parsers.
4. **The DB session is synchronous** (`create_engine` + `SessionLocal`, `psycopg` 3). The design keeps it synchronous — mixing `AsyncSession` into an existing sync codebase is churn for no MVP benefit — and isolates the one place that needs `async` (the webhook, which must read the raw request body) behind `run_in_threadpool`.
5. **CORS is hardcoded to two LAN origins** and the engine has no `pool_pre_ping`. Both are one-line fixes folded into §13.

## 1.4 What is deliberately *not* in this design

No microservices, no message broker, no Kafka/event streaming, no Kubernetes, no repository layer per model, no CQRS, no Redis (unless documented as an optional upgrade at one specific point), no separate read replica, no multi-tenancy beyond `business_id` scoping, no frontend. Every one of those is an ADR in §14 with the reason it was rejected for this MVP.

## 1.5 Effort shape

The critical path is **migration → capacity → transaction creation → public pay → webhook/verify → payment application → receipt + score**, exactly the demo story. Reminders, disputes, dashboard and PDF are parallelisable behind it. §15 breaks this into the PRD's Tue–Fri week with per-file tasks.

---

# 2. Requirements and Scope Analysis

## 2.1 The five questions → backend components

The PRD's acceptance test is that five questions are always answerable. Mapping them to the component that answers each is the cheapest possible requirements check.

| Question | Answering endpoint | Backing computation |
| --- | --- | --- |
| 1. Who owes us money? | `GET /debtors`, `GET /dashboard/summary` | `business_outstanding()` grouped by `debtor_id` |
| 2. How much is outstanding? | `GET /dashboard/summary` | four aggregates over `credit_transactions` + `payments` |
| 3. When should each debtor pay? | `GET /transactions?overdue=`, `GET /dashboard/summary` | `due_date`, `reminders` "next reminder" join |
| 4. What has been done to recover it? | `GET /transactions/:id` | `transaction_events` ordered `created_at DESC` |
| 5. Can we extend credit again? | `GET /debtors`, `GET /debtors/:id`, debtor block on the create form | `repayment_score()` computed on read |

If all five endpoints return correct data for the seeded business, the product's core claim is demonstrated.

## 2.2 MUST / SHOULD / OUT traversal

Every MUST in PRD §3 has a named home in this design. Nothing MUST-level is deferred.

| # | PRD item | Priority | Where it is specified |
| --- | --- | --- | --- |
| 1 | Credit limit on business | MUST | §5.3.1, §6.3 `PATCH /business/credit-limit` |
| 2 | Debtors create/read/update (no delete) | MUST | §5.3.2, §6.4 |
| 3 | Create credit transaction with capacity check | MUST | §5.3.3, §6.5, §7.2, §7.3 |
| 4 | Public debtor page: acknowledge/pay/promise/dispute | MUST | §5.3.4–5, §6.7 |
| 5 | Kora checkout, verification, webhook | MUST | §8 |
| 6 | Emails 1–8 + cron + "send now" | MUST | §9.4–9.7 |
| 7 | Transaction details with timeline | MUST | §5.3.7, §6.5.3, §7.3 |
| 8 | Dashboard summary + transactions list | MUST | §6.3.4, §6.5.2, §7.2.13 |
| 9 | Repayment score + badge + facts | MUST | §10 |
| 10 | Receipt as HTML page | MUST | §8.10, §6.6.1 |
| 11 | Seed data | MUST | §15.5, §12.12 |
| 12 | Full debtor profile page | SHOULD | §6.4.4 |
| 13 | Receipt PDF | SHOULD | §8.10.3 |
| 14 | Business logo upload | SHOULD — **dropped from the MVP (D-7)** | §5.3.1 keeps `logo_url` as a nullable display field. **No upload endpoint, no storage adapter, no `python-multipart`.** Receipt, PDF and email fall back to the initials block |

**Explicitly out of scope** (matching PRD §3, and named here so no reviewer assumes otherwise): WhatsApp/in-app channels; parsing email replies; repayment plans and escalation stages; per-debtor custom schedules; reports/exports; subscriptions/billing; team members and roles; **offline/manual payment recording** (§9.7 explains the "already paid" dispute path instead); per-creditor Kora accounts; payouts to creditors; shared reputation network. No endpoint, table or job in this design exists to serve any of them.

## 2.3 Every business rule from PRD §4, and where it is enforced

A rule is only real if something enforces it. This table is the enforcement map.

| Rule | Enforced by |
| --- | --- |
| Money is integer kobo, no floats | `BIGINT` columns + `CHECK (amount_kobo > 0)`; Pydantic `Annotated[int, Field(gt=0)]`; `app/core/money.py` is the only place that touches `Decimal`; no `float` in any schema |
| Only verified Kora payments reduce a balance | `PaymentService.apply_verified_charge()` is the sole writer of `status='successful'`; it is only reachable from the verify path (§8.6) |
| Balances/capacity/status/score computed on read | No such columns exist; §7.3 computes them; §10.3 computes score in SQL |
| Every important action writes `transaction_events` | Each service method takes the event insert in the same `Session` commit; §7.3 lists the required payloads and rendered text |
| Creditor routes derive `business_id` from JWT | `AuthenticatedBusiness` dependency; all queries scoped by `business.id`; no route reads `business_id` from body/query (§11.3) |
| Public routes use a bearer token | `secrets.token_urlsafe(32)`; unique index; excluded from creditors' serializers; `Referrer-Policy: no-referrer` (§11.5) |
| Disputes pause reminders | `disputed` status + reminders `cancelled` on raise; job additionally skips any `disputed` transaction as a belt-and-braces check (§9.5) |
| Promises delay reminders until after the promised date | Job rewrites `scheduled_for` to 9:00 WAT the day after `promised_date` when an open promise exists (§9.5) |
| Only one open promise per transaction | Partial unique index `WHERE type='promise' AND promise_status='open'` + `superseded` transition in one statement (§5.4.3) |
| Payments and webhooks idempotent | `kora_reference` unique; `kora_webhook_events(reference, event)` unique; success guard; `Idempotency-Key` on pay init (§8.7) |
| Overdue is derived, never stored | `credit_transaction_status` enum contains no `overdue`; `display_status()` adds it (§5.4.1) |
| All timestamps UTC; date logic WAT | `TIMESTAMPTZ` + `app/core/time.py` (`now_utc()`, `today_wat()`, `at_9am_wat()`); naive datetimes are forbidden by a lint check (§9.8) |
| Score uses verified payments and recorded promise outcomes only | §10.2 enumerates the only two inputs; no message text is ever read by the scorer |

## 2.4 PRD ↔ codebase conflicts (require your decision)

### [CONFLICT-1] `created_by FK users` — there is no `users` table

**Reality:** the JWT subject is a business id. `Business` carries `hashed_password`; the account *is* the business. No `users` row, table, or migration exists in the repository.

**Options considered:**

| Option | Cost | Verdict |
| --- | --- | --- |
| A. Create `users` now, backfill one user per business, change JWT `sub` to user id, add `business.users` | New table + migration + auth rewrite + every dependency changes | Rejected. It rewrites the one part of the system the PRD says is already done, on a three-day clock, to support a team-roles feature that is explicitly OUT of scope. |
| B. `created_by_business_id UUID NOT NULL REFERENCES businesses(id)` | One column, zero auth change, still answers "who created this" | **Recommended** |

**Approved in review (D-1).** Ship `created_by_business_id`, document the column's intent, and add the `users` migration when team members land (post-MVP). The API never exposes the distinction. This is the only place the design deviates from a PRD column name, and the deviation is now a decision rather than a proposal.

### [CONFLICT-2] `debtors` model exists with a different shape and no migration

The stub model is unusable (no `business_id`, globally-unique `email`, broken import). No migration creates the table.

**Proposal:** treat the PRD table definition in PRD §6 as authoritative, delete the stub model in the same commit that adds the real one, and create the table in a fresh migration. **[VERIFY]** before writing the migration, run on the hosted database:

```sql
SELECT to_regclass('public.debtors');       -- NULL ⇒ create fresh
SELECT version_num FROM alembic_version;    -- confirm fe6a8d47a7b6 is applied
```

If the table *does* exist (someone ran `create_all`), the migration must `ALTER` instead of `CREATE`; §5.8 gives both paths.

### [CONFLICT-3] Error envelope shape is not the PRD's

Current routes return `{"detail": "..."}`. PRD §9 mandates `{"error": {"code", "message", "fields"}}`.

**Proposal:** add a global handler set (§11.8) that serialises *all* errors into the PRD envelope, including legacy `HTTPException`s (mapping `detail` → `message`, deriving `code` from status: `UNAUTHORIZED`, `VALIDATION_ERROR`, …). Auth routes keep working unchanged; the frontend gets one parser. One additive extension is needed for `DEBTOR_EXISTS` (see §6.4.2): the existing debtor is returned under `error.existing_debtor`, because the PRD requires it and `fields` is the wrong container.

### [CONFLICT-4] The PRD's Kora "amount unit" risk is resolved — and it is not what the PRD guessed

PRD §13 says "Kora has historically taken naira, so convert from kobo and do not assume". Kora's current public docs confirm **naira** at initialize, *and* reveal a second, sharper problem the PRD does not mention: the verify endpoint returns the amount as a **decimal string in naira** (`"amount": "2000.00"`), and webhook payloads carry amount as a **JSON number** in naira (e.g. `150.99`). Details, impact and the exact comparison algorithm are in §8.4 and §16 R-2. Summary: compare in kobo after `Decimal` conversion; never compare provider floats; never `float(amount) * 100`.

**Fee treatment — decided (D-11), no longer a sandbox question.** Kora's transaction fee is **not** deducted from the verified amount: the **payer** bears it. Therefore:

| Rule | Consequence |
| --- | --- |
| The verified amount is **gross** | Credence credits the transaction with `naira_to_kobo(verify.data["amount"])` exactly |
| Kora's `fee` is never subtracted | No "net settlement" branch exists anywhere in the money code |
| `payments.amount_kobo` is both the requested and the credited amount | The equality check in §8.4 stays strict: `actual == expected` |
| Any future "we absorb the fee" model | Would be a new column and a new ADR, not a config flag |

This closes v1's K-7 and Q-12: `data.amount` is authoritative, and `data.fee` is retained only inside `payments.raw_webhook` for reconciliation display — never in arithmetic, never in a balance, never in a receipt total.

### [CONFLICT-5] PRD lists a reminder `channel` enum with one value (`email`)

Harmless, but a single-value native enum buys nothing and costs a migration to extend. §5.3.6 recommends `VARCHAR(16) + CHECK`, documented as an intentional deviation, with the reasoning in ADR-9.

## 2.5 Ambiguities in the PRD resolved by this design

Each is a decision I had to make to produce a buildable spec. All are marked **[REC]** in the body and collected in §16 for review.

| # | Ambiguity | Resolution |
| --- | --- | --- |
| A-1 | Pagination response shape is unspecified ("Lists take `?page=&limit=`") | `{"data": [...], "meta": {"page", "limit", "total", "total_pages"}}` (§6.1) |
| A-2 | Is `received_by`/`actor` name required on events? | `actor` ∈ {creditor, debtor, system} only, exactly as PRD §8.7 |
| A-3 | What is `manual` reminder's `scheduled_for`? | `now_utc()`, so the next tick sends within ≤15 min; `POST /remind` short-circuits and sends immediately (§9.6) |
| A-4 | Does a promise count if placed *after* the due date? | Yes; the window is `promised_date`-anchored, and misses are evaluated from `promised_date` (§8.13, §10.2) |
| A-5 | "Minimum ₦100 (or the balance if lower)" — is it ₦100 or 10000 kobo? | 10 000 kobo. Balance below 10 000 kobo is payable in full (§6.7.3) |
| A-6 | "One manual send per hour" — per transaction or per business? | Per transaction (§6.5.4) |
| A-7 | Partial payments and the score's `on_time_rate` | A transaction counts as on-time only if `settled_at` WAT-date ≤ `due_date` (§10.3) |
| A-8 | Is `avg_days_late` rounded for the score but shown raw? | Same integer is used in both; displayed as-is (§10.3) |
| A-9 | Does a *disputed* transaction's payment still count toward the score? | It is excluded from counted transactions (PRD says non-disputed), so "no" while open, "yes" once resolved and settled on time (§10.2) |
| A-10 | Who is the debtor's `contact_person` for emails? | Emails address the debtor business name; `contact_person` is display-only. No `{{contact_person}}` placeholder is invented |
| A-11 | `notes` column vs `note_added` events | `notes` keeps the latest internal note for convenience; **the events are the record**. Every note creates exactly one `note_added` event (§7.2.5) |
| A-12 | Receipt for a payment on a disputed transaction | Receipt is issued (money was received); the receipt's status line reads "Partially paid" with no dispute language — the debtor-facing page still shows the dispute (§8.10.4) |
| A-13 | `GET /capacity` with neither `debtor_id` nor `debtor_limit_kobo` | Valid; returns the business block only, `debtor: null`, `requires_override` from the business block alone (§6.3.1) |
| A-14 | Is the verified Kora amount gross or net of Kora's fee? | **Gross.** The payer bears the fee, so nothing is subtracted and `payments.amount_kobo` is both requested and credited (D-11, §8.4) |
| A-15 | A transaction created when it is *already* overdue — when is its first reminder? | 09:00 WAT on the **next** day, via `next_overdue_slot()`, used identically by create, rebuild, dispute resolve and promise expiry (§9.3.1) |
| A-16 | A verified payment lands on a `cancelled` transaction | Recorded as `successful`, status stays `cancelled`, `review_reason='paid_cancelled_transaction'`, surfaced as an ops item (D-3, §8.9.4) |
| A-17 | Is an `Idempotency-Key` reusable with a different amount? | No — same key + different body ⇒ `409 IDEMPOTENCY_KEY_REUSED`; same key + same body replays the original attempt (§6.7.3) |

## 2.6 Cross-check: components ↔ PRD sections

| PRD section | Covered in |
| --- | --- |
| §4 rules | §2.3, §11 |
| §5 statuses/transitions | §5.4.1, §7.2.2, §8.9 |
| §6 data model | §5 |
| §7.1 balance/capacity | §7.4, §10 (score), §6.3 |
| §7.2 reminders | §9 |
| §7.3 promises | §6.7.5, §7.2.8, §8.13 |
| §7.4 score | §10 |
| §8.1–8.7 flows | §6, §7, §8 |
| §9 API table (24 routes) | §6 — every route, none omitted (§6.0 index proves it) |
| §11 seed | §15.5 |
| §13 risks | §16 |

**Coverage result:** all 24 routes in PRD §9 are specified; all 8 emails, 14 event types, 6 stored statuses, 7 tables and 5 migrations have owning components. The three gaps v1 flagged are now closed rather than deferred: logo upload is dropped (D-7), `users` is replaced by `created_by_business_id` (D-1, ADR-15), and "next reminder" is defined once by `build_schedule` (§9.3.1).

---

# 3. System Architecture

## 3.1 Deployment topology

Two processes, one image, one database:

| Process | Command | Responsibility |
| --- | --- | --- |
| `api` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` | HTTP traffic: creditor API, public debtor API, receipts, webhooks |
| `worker` | `python -m app.worker` | APScheduler: reminder tick every 15 min, promise check daily at 00:05 WAT. No HTTP port. |

Both run the same code and read the same env. The worker is *only* a scheduler — all durable state is in PostgreSQL, so if the worker is down, reminders are late but never lost, and a restart resumes exactly where the schedule table says.

```mermaid
flowchart LR
    subgraph Client["Clients"]
        CR["Creditor web app<br/>(out of scope: UI only)"]
        DB_C["Debtor phone browser<br/>/pay/:token"]
    end

    subgraph Edge["Edge"]
        PROXY["TLS / reverse proxy<br/>(host platform)"]
    end

    subgraph App["Credence backend (modular monolith)"]
        API["api process<br/>FastAPI + Uvicorn"]
        WK["worker process<br/>APScheduler"]
        subgraph Modules["In-process modules"]
            AUTH["auth (existing JWT)"]
            BIZ["businesses"]
            DEB["debtors"]
            TX["credit transactions"]
            PAY["payments"]
            PUB["public debtor access"]
            REM["reminders"]
            SCO["repayment score"]
            NOT["notifications / events"]
        end
    end

    PG[("PostgreSQL<br/>primary datastore")]
    KORA["Kora API<br/>charges + verify"]
    MAIL["Resend<br/>transactional email"]

    CR -->|"Authorization: Bearer JWT"| PROXY
    DB_C -->|"public_token in URL"| PROXY
    PROXY --> API
    API --> Modules
    WK --> Modules
    Modules -->|"SQLAlchemy 2.0 / psycopg3"| PG
    API -->|"HTTPS out: initialize, verify"| KORA
    KORA -->|"webhook POST<br/>x-korapay-signature"| API
    WK -->|"HTTPS out: send email"| MAIL
    API -->|"HTTPS out: receipt, notice"| MAIL
```

**Why no separate webhook ingress, queue or cache:** the only asynchronous producer of *new money* is Kora's webhook, and it is low-volume (one call per payment attempt). A queue would add a moving part without changing correctness, because correctness already comes from the verify call and the `payment.status` guard. See ADR-2.

## 3.2 Component responsibilities

| Component | Owns | Never does |
| --- | --- | --- |
| `api` routes | HTTP shape, status codes, auth dependency, request parsing, response serialisation | Business rules, money math, multi-step DB writes |
| Service layer | Business rules, transactions, event emission, orchestration | HTTP concepts (`Request`, status codes), SQL string building |
| Models / queries | Persistence mapping, aggregate SQL | Authorisation decisions |
| `worker` | Timing. Calls the same service functions the API calls | Direct table manipulation that bypasses services |
| Integrations (`kora`, `email`) | Wire format, signature crypto, retries, provider error mapping | Decisions about whether a payment is valid |
| `core/money.py` | Kobo ↔ naira `Decimal` conversion, formatting | Any other math |

## 3.3 Creditor request flow (read path)

```mermaid
sequenceDiagram
    autonumber
    participant U as Creditor app
    participant R as FastAPI route
    participant D as Dependency (get_current_business)
    participant S as Service
    participant DB as PostgreSQL

    U->>R: GET /transactions?status=active
    R->>D: Depends(AuthenticatedBusiness)
    D->>D: verify_access_token(token) → sub
    D->>DB: SELECT business WHERE id = :sub
    DB-->>D: Business | none
    alt token invalid / business missing
        D-->>U: 401 UNAUTHORIZED (error envelope)
    else authenticated
        D-->>R: business
        R->>S: list_transactions(business.id, filters)
        S->>DB: SELECT … WHERE business_id = :bid (always scoped)
        S->>DB: aggregate paid_kobo per transaction
        DB-->>S: rows + sums
        S-->>R: domain objects + computed display_status
        R-->>U: 200 {"data":[…],"meta":{…}}
    end
```

Every creditor query carries `business_id = :bid` as its **first** predicate. No route accepts a `business_id` parameter. That is the whole tenant-isolation story, and it is testable in one parametrised test (§12.6).

## 3.4 Write flow with events (the pattern used by every mutation)

```mermaid
sequenceDiagram
    autonumber
    participant R as Route
    participant S as Service
    participant DB as PostgreSQL
    participant X as Integration (email / Kora)

    R->>S: create_transaction(business, payload)
    S->>DB: BEGIN
    S->>DB: SELECT business FOR UPDATE  (serialise capacity)
    S->>DB: compute outstanding (SUM)
    alt over capacity and not overridden
        S->>DB: ROLLBACK
        S-->>R: CapacityExceededError → 422 CAPACITY_EXCEEDED
    end
    S->>DB: nextval(reference_seq) → CRD-000123
    S->>DB: INSERT credit_transactions (status pending_ack)
    S->>DB: INSERT reminders ×N (schedule)
    S->>DB: INSERT transaction_events (transaction_created)
    S->>DB: COMMIT
    Note over S,X: Side effects happen AFTER commit — a dead email<br/>never rolls back a recorded debt
    S->>X: send new-credit notice
    S->>DB: UPDATE reminders SET status='sent'|'failed', provider_message_id / error
    S->>DB: INSERT transaction_events (reminder_sent | reminder_failed)
    S-->>R: transaction + pay_link + reminders
```

This "commit first, notify second, record the notification outcome" rule is what makes the PRD's "a send failure does not roll back" requirement fall out of the structure rather than out of a special case.

## 3.5 Payment processing flow (summary; full spec in §8)

```mermaid
flowchart TD
    A["Debtor clicks Pay<br/>POST /public/tx/{token}/pay"] --> B{"balance > 0<br/>and status payable?"}
    B -- no --> B1["409 TX_NOT_PAYABLE"]
    B -- yes --> C["INSERT payments (initiated)<br/>kora_reference = CRD-000123-P1"]
    C --> D["POST Kora /charges/initialize<br/>amount = kobo ÷ 100 (naira)"]
    D -->|ok| E["store checkout_url<br/>return it to browser"]
    D -->|error| E1["payments.status=failed<br/>failure_reason; 502 PAYMENT_INIT_FAILED"]
    E --> F["Debtor pays on Kora →<br/>redirect to /pay/{token}/result?ref="]
    F --> G["Kora POST /webhooks/kora"]
    G --> H{"HMAC-SHA256 of data<br/>matches x-korapay-signature?"}
    H -- no --> H1["401, log, no state change"]
    H -- yes --> I{"webhook row already<br/>recorded? payment already<br/>successful?"}
    I -- yes --> I1["200, stop (duplicate)"]
    I -- no --> J["Record webhook row, return 200 fast"]
    J --> K["GET Kora /charges/{reference}<br/>(server-side verify)"]
    K --> L{"data.status == success<br/>AND amount == expected kobo<br/>AND currency == NGN?"}
    L -- no --> L1["payments.status=failed<br/>payment_failed event; balance unchanged"]
    L -- yes --> M["PaymentService.apply_verified_charge<br/>lock payment → lock transaction<br/>(one DB transaction)"]
    M --> N["credit the GROSS verified amount (fee never deducted)<br/>status successful, paid_at, receipt_number<br/>recompute balance = amount − Σ verified payments<br/>partially_paid / settled / cancelled unchanged<br/>review_reason if overpaid or paid-cancelled<br/>cancel reminders if settled; promise kept?<br/>payment_received event (+ overpaid_kobo)"]
    N --> O["After commit: email 6 (receipt)<br/>or email 7 (settled) — exactly one"]
```

The redirect the browser follows is **never** trusted: `GET /public/tx/{token}/payments/:ref` reads our own `payments` row, which only the verify path can mark successful.

Two properties of the money path are worth stating here because every later section depends on them:

1. **The credited amount is the verified gross amount.** Kora's fee is borne by the payer, so nothing is subtracted (§8.4).
2. **A genuine successful charge is never discarded.** It is always written as `successful`; if it overpays, or lands on a cancelled transaction, it is additionally *flagged* (`payments.review_reason`) rather than rejected or used to reopen the transaction (§8.9.3–§8.9.4).

## 3.6 Background execution flow

```mermaid
flowchart LR
    subgraph Worker["worker process"]
        SCH["APScheduler<br/>interval 15 min, max_instances=1"]
        DAILY["APScheduler<br/>cron 00:05 Africa/Lagos"]
    end
    SCH --> TICK["run_reminder_tick()"]
    DAILY --> PC["run_promise_check()"]
    TICK -->|"claim batch"| PG[("reminders")]
    TICK --> CALC["load tx, compute balance NOW"]
    CALC --> DEC{"settled / cancelled / disputed /<br/>open promise in future?"}
    DEC -->|terminal| SK["status=skipped (+reason)"]
    DEC -->|promise| MV["scheduled_for = 9:00 WAT<br/>day after promised_date"]
    DEC -->|send| MAIL["Resend send"]
    MAIL --> OK["status=sent + provider_message_id<br/>event reminder_sent"]
    MAIL --> FAIL["status=failed + error<br/>event reminder_failed"]
    OK --> NEXT["if overdue_followup:<br/>INSERT next row +7 days"]
    PC --> PROM[("debtor_responses<br/>promise_status=open")]
```

## 3.7 Authority boundaries (what may write what)

This is the most important table in the security section, placed here because it is an architecture statement, not a checklist.

| Fact | Only writer | Trigger |
| --- | --- | --- |
| `payments.status = 'successful'` | `PaymentService.apply_verified_charge` | Kora verify response |
| `payments.status = 'failed'` | same service | verify says non-success, amount mismatch, or init error |
| `payments.review_reason` | `PaymentService.apply_verified_charge` | overpayment, or a verified payment on a `cancelled` transaction (never un-set silently) |
| `credit_transactions.status` | `CreditTransactionService` (create/cancel/dispute-resolve) and `PaymentService` (payment-driven) | domain events |
| `credit_transactions.settled_at` | `PaymentService` | balance reaches 0 |
| `debtor_responses.promise_status` | `PromiseService` | payment window check, daily check, or supersede |
| `reminders.status` | `ReminderService` / job | send attempt, dispute, settle, cancel |
| `transaction_events` | every service, insert-only | same transaction as the change |
| Balance / capacity / score / `display_status` | **nobody** | computed on read |

If a future engineer adds a route that sets `status='settled'` without a payment, this table is the review checklist that catches it.

---

# 4. Backend Project Structure

## 4.1 Guiding rules

1. **Feature modules, not layer buckets.** `app/modules/transactions/` holds its routes, schemas, model, service and queries. A change to credit transactions touches one directory. Classic `api/ + crud/ + schemas/` splits force four-file edits for one feature and is worse for a small team.
2. **No generic repository layer.** `Session` is already a unit of work; `select()` is already a query DSL. A `BaseRepository` with `get/all/create` would be indirection with no behaviour. Exception: shared *read models* whose SQL is genuinely reused (balance, score) live in explicitly named modules — that is deduplication of a calculation, not ceremony. (ADR-4)
3. **Routes contain no `db.query`.** The dependency injects `Session` for the service, not the route, except for trivial reads.
4. **Integrations are the only place that speaks a vendor's protocol.** Kora JSON keys never leak past `integrations/kora`. Resend HTTP never leaks past `integrations/email`.
5. **Flat until it hurts.** No `__init__.py` re-export gymnastics beyond models; no abstract base services; no dependency-injection framework.

## 4.2 Directory tree

```
credence-back-end/
├── alembic/
│   ├── env.py                      # existing; extend to import all models
│   └── versions/
│       ├── fe6a8d47a7b6_add_business_table.py        # existing
│       ├── 0002_business_credit_limit_logo.py        # [new]
│       ├── 0003_debtors.py                           # [new]
│       ├── 0004_credit_transactions.py               # [new]
│       ├── 0005_payments.py                          # [new]
│       ├── 0006_debtor_responses.py                  # [new]
│       ├── 0007_reminders.py                         # [new]
│       └── 0008_transaction_events.py                # [new]
├── alembic.ini
├── requirements.txt
├── app/
│   ├── main.py                     # app factory, routers, middleware, exception handlers
│   ├── worker.py                   # APScheduler entrypoint (python -m app.worker)
│   ├── core/
│   │   ├── config.py               # Settings (extended)
│   │   ├── database.py             # engine, SessionLocal, Base, get_db (extend pool opts)
│   │   ├── dependencies.py         # AuthenticatedBusiness, DatabaseSession, pagination, PublicTransaction
│   │   ├── security.py             # existing JWT/argon2 + token generation helpers
│   │   ├── money.py                # kobo<->naira, formatting, Decimal helpers  ← single owner
│   │   ├── time.py                 # utcnow(), today_wat(), at_9am_wat(), wat_tz  ← single owner
│   │   ├── errors.py               # AppError hierarchy + error codes
│   │   ├── pagination.py           # page/limit parsing + meta builder
│   │   └── logging.py              # structured logging, request_id, secret redaction
│   ├── db/
│   │   ├── base.py                 # imports every model so Alembic sees metadata
│   │   └── enums.py                # pg enum definitions shared by models + migrations
│   ├── models/
│   │   ├── __init__.py             # exports all models (Alembic depends on this)
│   │   ├── mixins.py               # existing BaseMixin (id, created_at, updated_at)
│   │   ├── business.py             # existing + credit_limit_kobo, logo_url
│   │   ├── debtor.py               # REWRITE of the stub
│   │   ├── credit_transaction.py
│   │   ├── payment.py
│   │   ├── debtor_response.py
│   │   ├── reminder.py
│   │   └── transaction_event.py
│   ├── modules/
│   │   ├── auth/                   # existing; unchanged behaviour
│   │   │   └── service.py
│   │   ├── businesses/
│   │   │   ├── router.py           # GET /business, PATCH /business/credit-limit
│   │   │   ├── schemas.py
│   │   │   ├── service.py          # BusinessService
│   │   │   └── queries.py          # business_outstanding()
│   │   ├── debtors/
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py          # DebtorService
│   │   │   └── queries.py          # outstanding/overdue per debtor
│   │   ├── transactions/
│   │   │   ├── router.py           # creditor transaction routes + notes/remind/cancel/resolve
│   │   │   ├── schemas.py
│   │   │   ├── service.py          # CreditTransactionService
│   │   │   ├── balance.py          # calculate_balance(), display_status()  ← single owner
│   │   │   ├── events.py           # TransactionEventService + event type constants
│   │   │   └── queries.py          # detail assembly, list filters, dashboard aggregates
│   │   ├── capacity/
│   │   │   ├── router.py           # GET /capacity
│   │   │   └── service.py          # CreditCapacityService
│   │   ├── payments/
│   │   │   ├── router.py           # webhook, receipt, payment status
│   │   │   ├── schemas.py
│   │   │   ├── service.py          # PaymentService (apply_verified_charge)
│   │   │   ├── receipts.py         # ReceiptService (HTML + PDF)
│   │   │   └── templates/receipt.html
│   │   ├── public/
│   │   │   ├── router.py           # /public/tx/{token}/* (public, rate-limited)
│   │   │   ├── schemas.py
│   │   │   └── service.py          # PublicTransactionService (safe projection)
│   │   ├── reminders/
│   │   │   ├── service.py          # ReminderService: schedule/build/rebuild/send
│   │   │   ├── job.py              # run_reminder_tick()
│   │   │   └── templates.py        # reminder → email template selection (PRD §7.2)
│   │   ├── promises/
│   │   │   ├── service.py          # PromiseService: make/kept/missed/supersede
│   │   │   └── job.py              # run_promise_check()
│   │   ├── scoring/
│   │   │   ├── service.py          # RepaymentScoreService
│   │   │   ├── queries.py          # the four score aggregates
│   │   │   └── schemas.py          # score + facts
│   │   └── dashboard/
│   │       ├── router.py           # GET /dashboard/summary
│   │       └── service.py          # DashboardService
│   ├── integrations/
│   │   ├── kora/
│   │   │   ├── client.py           # httpx client, initialize/verify, error mapping
│   │   │   ├── signature.py        # HMAC verification (raw-body canonicalisation)
│   │   │   └── schemas.py          # provider DTOs (internal only)
│   │   └── email/
│   │       ├── client.py           # Resend adapter + provider error mapping
│   │       ├── templates.py        # ALL 8 email templates in one file (PRD §8.6)
│   │       └── render.py           # {{placeholder}} substitution, Naira formatting
│   ├── scripts/
│   │   ├── seed_demo.py            # PRD §11 seed
│   │   └── run_reminders_once.py   # manual tick for demo/incident use
│   └── tests/
│       ├── conftest.py             # app, db, client, factories, freeze-time fixtures
│       ├── factories.py
│       ├── unit/                   # money, time, score math, template selection, signature
│       ├── api/                    # route contracts, authz, validation
│       ├── integration/            # service + DB + concurrency
│       └── e2e/                    # the PRD demo story, end to end
├── docs/architecture/
│   └── credence-backend-architecture.md
└── .env.example                    # every variable documented, no values
```

### 4.2.1 Component wiring

```mermaid
flowchart TB
    subgraph Workers["worker process"]
        JOBS["reminders/job.py<br/>promises/job.py"]
    end

    subgraph HTTP["api process — routers"]
        R_AUTH["auth"]
        R_BIZ["businesses"]
        R_DEB["debtors"]
        R_TX["transactions"]
        R_CAP["capacity"]
        R_DASH["dashboard"]
        R_PUB["public"]
        R_PAY["payments"]
    end

    subgraph Services["service layer"]
        S_BIZ["BusinessService"]
        S_DEB["DebtorService"]
        S_CAP["CreditCapacityService"]
        S_TX["CreditTransactionService"]
        S_PAY["PaymentService"]
        S_PRO["PromiseService"]
        S_REM["ReminderService"]
        S_SCORE["RepaymentScoreService"]
        S_RCPT["ReceiptService"]
        S_EVT["TransactionEventService"]
        S_DASH["DashboardService"]
    end

    subgraph Core["core + pure functions"]
        MONEY["core/money.py"]
        TIME["core/time.py"]
        BAL["transactions/balance.py"]
        ERR["core/errors.py"]
    end

    subgraph Integrations["integrations"]
        KORA["kora/client.py<br/>kora/signature.py"]
        EMAIL["email/client.py<br/>email/templates.py"]
    end

    DB[("PostgreSQL")]

    R_BIZ --> S_BIZ
    R_DEB --> S_DEB
    R_TX --> S_TX
    R_CAP --> S_CAP
    R_DASH --> S_DASH
    R_PUB --> S_TX
    R_PUB --> S_PAY
    R_PAY --> S_PAY
    R_PAY --> S_RCPT

    S_TX --> S_CAP
    S_TX --> S_DEB
    S_TX --> S_REM
    S_TX --> S_EVT
    S_PAY --> S_TX
    S_PAY --> S_PRO
    S_PAY --> S_REM
    S_PAY --> S_RCPT
    S_PAY --> KORA
    S_PRO --> S_REM
    S_REM --> EMAIL
    S_DEB --> S_SCORE
    S_DASH --> S_EVT
    JOBS --> S_REM
    JOBS --> S_PRO
    JOBS --> S_PAY

    Services --> BAL
    Services --> MONEY
    Services --> TIME
    Services --> ERR
    Services --> DB
```

Read it as the import rule from §4.1: routers reach services, services reach each other only downward (no arrow returns to a router), and every money or date calculation resolves to a pure function in `core/` or `balance.py` rather than being re-implemented inside a service.

## 4.3 Why each major directory exists (and what must not appear in it)

| Directory | Responsibility | Forbidden |
| --- | --- | --- |
| `core/` | Cross-cutting primitives with no domain knowledge: config, DB session, auth dependency, money, time, errors, pagination, logging | Any import of `app.modules.*` (core must not depend on features) |
| `db/` | The one place that imports all models so `Base.metadata` is complete for Alembic; shared enum definitions | Queries |
| `models/` | Table mapping, relationships, column constraints | Business logic, `@property` calculations that belong in `balance.py` |
| `modules/<feature>/router.py` | HTTP contract only: parse → call service → serialise | `db.query`, `select()`, money math |
| `modules/<feature>/service.py` | Rules, transaction boundaries, event emission, orchestration | `HTTPException` (raise `AppError`; the handler maps it) |
| `modules/<feature>/queries.py` | Reused aggregate SQL (outstanding, dashboard, score) | Writes |
| `integrations/` | Vendor protocol, retries, signature checks | Domain decisions |
| `scripts/` | One-shot operational entrypoints | Being imported by routes |

**Import direction (enforced by review, and cheaply by an import-linter rule if desired):**

```
router → service → queries/model
service → integrations (interface level), core
integrations → core only
core → (nothing from app.modules)
```

A `service` importing a `router` is always a bug; a `router` importing another feature's `service` is allowed (e.g. `public` → `payments`).

## 4.4 Extension of existing files (exact deltas)

| File | Delta | Reason |
| --- | --- | --- |
| `app/core/config.py` | Add `kora_secret_key`, `kora_base_url`, `kora_timeout_seconds`, `app_url`, `environment`, `resend_api_key`, `email_from`, `email_reply_to_fallback`, `public_rate_limit_*`, `receipt_pdf_enabled`, `log_level`; keep existing keys; `model_config` → `SettingsConfigDict` | One config surface |
| `app/core/database.py` | `create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10, pool_recycle=1800)`; keep `get_db` | Managed Postgres drops idle connections; without `pool_pre_ping` the first request after idle 500s |
| `app/core/dependencies.py` | Add `Pagination` dependency, `PublicTransaction` dependency (token → transaction, 404 on bad token) | Public routes need token auth as a dependency, not inline |
| `app/main.py` | Include new routers; register `AppError` + `RequestValidationError` + `HTTPException` handlers; `CORSMiddleware(allow_origins=settings.cors_origins)`; add `Referrer-Policy` middleware for `/public/*`; disable `/docs` outside dev if desired | Error envelope + CORS from env |
| `app/models/__init__.py` | Export every new model | Alembic autogenerate + `db/base.py` |
| `app/models/business.py` | `credit_limit_kobo: Mapped[int \| None]`, `logo_url: Mapped[str \| None]` | PRD §6 |
| `app/models/debtor.py` | **Replace** with the PRD table (see [CONFLICT-2]) | Stub is unusable |
| `alembic/env.py` | No structural change; it already imports `app.models` | Works once `__init__` exports new models |
| `requirements.txt` | Add `apscheduler`, `httpx` (present), `jinja2`, `weasyprint` (PDF, SHOULD), `slowapi`, `respx`+`pytest-cov` (dev). **No `python-multipart`** — logo upload is dropped (D-7). Pin exact versions; keep the UTF-16 encoding or convert to UTF-8 **deliberately** | Reproducible builds |

> **Note on `requirements.txt`:** the file is UTF-16LE with CRLF. `pip install -r` tolerates it, but editors and diffs do not. Convert to UTF-8 in one dedicated commit (no content change) so later dependency diffs are reviewable.

---

# 5. Database Architecture

## 5.1 Conventions applied to every table

| Convention | Rule | Enforcement |
| --- | --- | --- |
| Primary key | `id UUID PRIMARY KEY DEFAULT gen_random_uuid()` | Existing `BaseMixin` sets it from Python (`uuid.uuid4`); `pgcrypto`/`gen_random_uuid()` needs no extension on PG13+. Keep the Python default to match existing style. |
| Timestamps | `created_at`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()` | Existing `BaseMixin`. UTC because the column is `timestamptz`. |
| Money | `BIGINT`, suffixed `_kobo`, `CHECK (… > 0)` where 0 is meaningless | No `NUMERIC`, no `FLOAT`, no `MONEY` (PG `money` type is locale-dependent), no `REAL` |
| Dates | `DATE` for issue/due/promised, interpreted in WAT | Never `timestamp` for a calendar date |
| Enums | Native PG `ENUM` for the six closed status sets; `VARCHAR + CHECK` for event types and reminder `channel` | §5.4 and ADR-9 |
| Foreign keys | Explicit `ON DELETE` behaviour; default `RESTRICT` (never silently cascade financial history) | §5.3 |
| Text | `VARCHAR(n)` where the PRD gives a length (name 120, description 200, registration 20); `TEXT` where it does not | Pydantic mirrors the length |
| Case | Emails stored lowercased; unique indexes are case-insensitive via `lower()` | Service normalises on write; index is the backstop |
| Soft delete | None. No `deleted_at`. PRD has no delete for debtors; cancelled is a transaction status | Absence is deliberate |

**Why `gen_random_uuid()` vs Python UUID:** the codebase already generates UUIDs in Python through `BaseMixin`. Migrations will use `server_default=sa.text("gen_random_uuid()")` **as well**, so raw SQL inserts (seed scripts, emergency fixes) work without an ORM.

## 5.2 Entity–relationship diagram

```mermaid
erDiagram
    businesses ||--o{ debtors : "owns"
    businesses ||--o{ credit_transactions : "owns"
    businesses ||--o{ credit_transactions : "created_by_business"
    debtors ||--o{ credit_transactions : "owes"
    credit_transactions ||--o{ payments : "paid by"
    credit_transactions ||--o{ debtor_responses : "responded"
    credit_transactions ||--o{ reminders : "scheduled"
    credit_transactions ||--o{ transaction_events : "timeline"

    businesses {
        uuid id PK
        string name
        string email UK
        string phone UK
        string hashed_password
        enum category
        string address
        string registration_number
        bigint credit_limit_kobo "nullable = no limit"
        string logo_url "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    debtors {
        uuid id PK
        uuid business_id FK
        string name
        string contact_person "nullable"
        string email
        string phone
        bigint credit_limit_kobo "nullable"
        string address "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    credit_transactions {
        uuid id PK
        uuid business_id FK
        uuid debtor_id FK
        string reference UK "CRD-000123"
        string invoice_number "nullable"
        string description
        bigint amount_kobo
        date issue_date
        date due_date
        text notes "nullable, internal"
        enum status "6 stored values"
        string public_token UK
        bool capacity_override
        text override_reason "nullable"
        timestamptz acknowledged_at "nullable"
        timestamptz settled_at "nullable"
        uuid created_by_business_id FK
        timestamptz created_at
        timestamptz updated_at
    }

    payments {
        uuid id PK
        uuid transaction_id FK
        string kora_reference UK "CRD-000123-P1"
        int attempt_number
        bigint amount_kobo
        enum status
        string checkout_url "nullable"
        timestamptz paid_at "nullable"
        string receipt_number UK "nullable, RCT-000045"
        jsonb raw_webhook "nullable"
        string failure_reason "nullable"
        timestamptz verified_at "nullable"
        bigint overpaid_kobo "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    debtor_responses {
        uuid id PK
        uuid transaction_id FK
        enum type
        date promised_date "nullable"
        bigint promised_amount_kobo "nullable"
        text message "nullable"
        enum promise_status "nullable"
        enum dispute_reason "nullable"
        timestamptz resolved_at "nullable"
        text resolution_note "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    reminders {
        uuid id PK
        uuid transaction_id FK
        enum kind
        string channel "email"
        timestamptz scheduled_for
        enum status
        string skip_reason "nullable"
        timestamptz sent_at "nullable"
        string provider_message_id "nullable"
        text error "nullable"
        int attempt_count
        timestamptz locked_until "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    transaction_events {
        uuid id PK
        uuid transaction_id FK
        string type
        enum actor
        jsonb data
        timestamptz created_at
        timestamptz updated_at
    }
```

## 5.3 Table specifications and DDL

Below is the intended `alembic upgrade` result. Written as SQL for precision; the Alembic revisions in §5.8 produce exactly this.

### 5.3.1 `businesses` (extend existing)

```sql
ALTER TABLE businesses
    ADD COLUMN credit_limit_kobo BIGINT NULL,
    ADD COLUMN logo_url          TEXT   NULL;

ALTER TABLE businesses
    ADD CONSTRAINT ck_businesses_credit_limit_positive
        CHECK (credit_limit_kobo IS NULL OR credit_limit_kobo > 0);
```

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `credit_limit_kobo` | `BIGINT` | yes | `NULL` = no limit (PRD §6, §8.1). Must be `> 0` when set: "0" means "cannot extend credit", which the PRD expresses as `NULL` = unlimited, so `0` is meaningless and rejected |
| `logo_url` | `TEXT` | yes | SHOULD. Fallback is business name/initials, done by the frontend. No upload endpoint exists in PRD §9 → open question Q-3 |

Existing columns unchanged: `name`, `hashed_password`, `category`, `address`, `phone` (unique), `email` (unique), `registration_number`. `category` is a native enum `businesscategory` created by migration `fe6a8d47a7b6`.

> **Existing-schema note:** `registration_number` and `category` are `NOT NULL` in the live schema, while `RegisterSchema` requires them too. The PATCH endpoint in §6.3 touches only `credit_limit_kobo`, so nothing here can trip those constraints.

### 5.3.2 `debtors`

```sql
CREATE TABLE debtors (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id      UUID NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
    name             VARCHAR(120) NOT NULL,
    contact_person   VARCHAR(120) NULL,
    email            VARCHAR(254) NOT NULL,
    phone            VARCHAR(20)  NOT NULL,
    credit_limit_kobo BIGINT NULL,
    address          TEXT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_debtors_name_len      CHECK (char_length(name) >= 2),
    CONSTRAINT ck_debtors_credit_limit  CHECK (credit_limit_kobo IS NULL OR credit_limit_kobo > 0),
    CONSTRAINT ck_debtors_phone_e164    CHECK (phone ~ '^\+[1-9][0-9]{9,14}$')
);

CREATE UNIQUE INDEX uq_debtors_business_email ON debtors (business_id, lower(email));
CREATE INDEX ix_debtors_business_name ON debtors (business_id, lower(name));
```

| Column | Type | Null | Rules |
| --- | --- | --- | --- |
| `business_id` | `UUID` FK | no | Tenant key. Every query filters on it |
| `name` | `VARCHAR(120)` | no | 2–120 chars (PRD §8.2 A) |
| `contact_person` | `VARCHAR(120)` | yes | Display only; emails address the business |
| `email` | `VARCHAR(254)` | no | Validated by Pydantic `EmailStr`; stored lowercased |
| `phone` | `VARCHAR(20)` | no | E.164, normalised to `+234…`; DB CHECK is the last line of defence |
| `credit_limit_kobo` | `BIGINT` | yes | `NULL` = no debtor-level limit |
| `address` | `TEXT` | yes | Free text |

**Uniqueness is `(business_id, lower(email))`, not global.** PRD §6 says unique on `(business_id, email)`; two businesses may both owe the same customer, and the stub model's global unique is precisely the thing that must be dropped. Using `lower(email)` closes the `Accounts@` / `accounts@` duplicate hole that a plain composite unique leaves open.

### 5.3.3 `credit_transactions`

```sql
CREATE TYPE credit_transaction_status AS ENUM
    ('pending_ack','active','partially_paid','disputed','settled','cancelled');

CREATE SEQUENCE credit_transaction_reference_seq START 1 INCREMENT 1;

CREATE TABLE credit_transactions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id           UUID NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
    debtor_id             UUID NOT NULL REFERENCES debtors(id)    ON DELETE RESTRICT,
    reference             VARCHAR(20) NOT NULL,
    invoice_number        VARCHAR(50) NULL,
    description           VARCHAR(200) NOT NULL,
    amount_kobo           BIGINT NOT NULL,
    issue_date            DATE NOT NULL,
    due_date              DATE NOT NULL,
    notes                 TEXT NULL,
    status                credit_transaction_status NOT NULL DEFAULT 'pending_ack',
    public_token          VARCHAR(64) NOT NULL,
    capacity_override     BOOLEAN NOT NULL DEFAULT false,
    override_reason       TEXT NULL,
    acknowledged_at       TIMESTAMPTZ NULL,
    settled_at            TIMESTAMPTZ NULL,
    created_by_business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE RESTRICT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ct_reference     UNIQUE (reference),
    CONSTRAINT uq_ct_public_token  UNIQUE (public_token),
    CONSTRAINT ck_ct_amount        CHECK (amount_kobo > 0),
    CONSTRAINT ck_ct_due_after_issue CHECK (due_date >= issue_date),
    CONSTRAINT ck_ct_override_reason CHECK (
        (capacity_override = false AND override_reason IS NULL)
        OR (capacity_override = true AND override_reason IS NOT NULL
            AND char_length(trim(override_reason)) > 0)
    ),
    CONSTRAINT ck_ct_settled_at CHECK (
        (status = 'settled') = (settled_at IS NOT NULL)
    )
);

CREATE INDEX ix_ct_business_status  ON credit_transactions (business_id, status);
CREATE INDEX ix_ct_business_due     ON credit_transactions (business_id, due_date);
CREATE INDEX ix_ct_debtor           ON credit_transactions (debtor_id);
CREATE INDEX ix_ct_business_created ON credit_transactions (business_id, created_at DESC);
-- supports the "outstanding" aggregate for one business without touching settled/cancelled rows
CREATE INDEX ix_ct_open_by_business ON credit_transactions (business_id)
    WHERE status NOT IN ('settled','cancelled');
```

| Column | Type | Null | Rules / notes |
| --- | --- | --- | --- |
| `reference` | `VARCHAR(20)` | no | `CRD-` + zero-padded `nextval` (min 6 digits, grows naturally past 999999). Generated server-side only |
| `invoice_number` | `VARCHAR(50)` | yes | The creditor's own; never used for identity |
| `description` | `VARCHAR(200)` | no | Required, ≤200 (PRD §8.2 B) |
| `amount_kobo` | `BIGINT` | no | `> 0` |
| `issue_date` / `due_date` | `DATE` | no | `due_date >= issue_date`; `issue_date` not in the future (validated in Pydantic against WAT today) |
| `notes` | `TEXT` | yes | Internal only. Never serialised by any `/public/*` route |
| `status` | enum | no | Six values only. **No `overdue`** (PRD §5) |
| `public_token` | `VARCHAR(64)` | no | `secrets.token_urlsafe(32)` → 43 chars. Unique |
| `capacity_override` + `override_reason` | bool + text | no + yes | Paired by CHECK: override implies a non-empty reason |
| `acknowledged_at` | `TIMESTAMPTZ` | yes | Set on `/acknowledge` and on promise/dispute |
| `settled_at` | `TIMESTAMPTZ` | yes | Set by `PaymentService` when balance hits 0; **remains set** even though the CHECK ties it to `status='settled'` — see invariant below |
| `created_by_business_id` | `UUID` FK | no | [CONFLICT-1]. This is the PRD's `created_by FK users`, mapped to the only account entity that exists |

> **Invariant risk caught during review:** `ck_ct_settled_at` as written forbids `settled_at` from surviving a later status change (e.g. a reversal). The MVP has no reversals, so the constraint holds and *documents* the rule "settled means settled_at is set". If reversals ever land, this is the constraint to relax first. Flagged in §16 R-8.

**Status is never written from a route.** Creation writes `pending_ack`; acknowledgement/promise writes `active`; dispute writes `disputed`; resolve recomputes; cancel writes `cancelled`; payments write `partially_paid`/`settled`. Anything else is a bug (§3.7).

### 5.3.4 `payments`

```sql
CREATE TYPE payment_status AS ENUM ('initiated','pending','successful','failed','reversed');

CREATE SEQUENCE payment_receipt_seq START 1 INCREMENT 1;

CREATE TABLE payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  UUID NOT NULL REFERENCES credit_transactions(id) ON DELETE RESTRICT,
    kora_reference  VARCHAR(80) NOT NULL,
    attempt_number  INTEGER NOT NULL,
    amount_kobo     BIGINT NOT NULL,
    status          payment_status NOT NULL DEFAULT 'initiated',
    checkout_url    TEXT NULL,
    paid_at         TIMESTAMPTZ NULL,
    receipt_number  VARCHAR(20) NULL,
    raw_webhook     JSONB NULL,
    failure_reason  TEXT NULL,
    verified_at     TIMESTAMPTZ NULL,
    overpaid_kobo   BIGINT NULL,
    review_reason   VARCHAR(32) NULL,
    provider_mode   VARCHAR(8) NOT NULL DEFAULT 'sandbox',
    idempotency_key UUID NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_pay_kora_reference UNIQUE (kora_reference),
    CONSTRAINT uq_pay_receipt_number UNIQUE (receipt_number),
    CONSTRAINT uq_pay_attempt        UNIQUE (transaction_id, attempt_number),
    CONSTRAINT ck_pay_amount         CHECK (amount_kobo > 0),
    CONSTRAINT ck_pay_success_fields CHECK (
        (status <> 'successful')
        OR (paid_at IS NOT NULL AND receipt_number IS NOT NULL AND verified_at IS NOT NULL)
    ),
    CONSTRAINT ck_pay_overpaid       CHECK (overpaid_kobo IS NULL OR overpaid_kobo >= 0),
    CONSTRAINT ck_pay_review_reason  CHECK (
        review_reason IS NULL
        OR review_reason IN ('overpaid','paid_cancelled_transaction')
    ),
    CONSTRAINT ck_pay_provider_mode  CHECK (provider_mode IN ('sandbox','live'))
);

CREATE INDEX ix_pay_transaction ON payments (transaction_id, status);
CREATE INDEX ix_pay_received    ON payments (transaction_id, paid_at DESC)
    WHERE status = 'successful';
-- reconciliation: find attempts that never resolved (for a manual/ops query)
CREATE INDEX ix_pay_stale       ON payments (created_at)
    WHERE status IN ('initiated','pending');
-- one checkout per client intent (double-tap protection), see 8.8
CREATE UNIQUE INDEX uq_pay_idempotency ON payments (transaction_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
-- ops queue: every payment a human must look at (overpayment, paid-cancelled invoice)
CREATE INDEX ix_pay_review ON payments (created_at DESC)
    WHERE review_reason IS NOT NULL;
```

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `kora_reference` | `VARCHAR(80)` | no | `CRD-000123-P1`. **Our** reference, sent to Kora, used to find the row on webhook/verify. Unique ⇒ a replayed init cannot charge twice |
| `attempt_number` | `INTEGER` | no | Per-transaction monotonic counter, allocated under a `FOR UPDATE` lock on the transaction row. `UNIQUE(transaction_id, attempt_number)` makes double allocation impossible |
| `amount_kobo` | `BIGINT` | no | What we asked Kora to charge. **The expected amount for verification** |
| `status` | enum | no | `initiated` → `pending` → `successful` \| `failed`. `reversed` exists in the PRD enum but no MVP code path writes it (refunds are out of scope) |
| `checkout_url` | `TEXT` | yes | Returned to the browser. Not a secret, but not indexed |
| `paid_at` | `TIMESTAMPTZ` | yes | Kora's transaction time if parseable, else verify time. Drives scores/receipts |
| `receipt_number` | `VARCHAR(20)` | yes | `RCT-` + padded `nextval`, assigned exactly once on success; `UNIQUE` |
| `raw_webhook` | `JSONB` | yes | The verified webhook payload. Debugging + audit. Excluded from every API response |
| `failure_reason` | `TEXT` | yes | `provider_declined`, `amount_mismatch`, `currency_mismatch`, `init_error`, `verify_error`, … |
| `verified_at` | `TIMESTAMPTZ` | yes | When the server-side verify confirmed success. Ties the CHECK to "only verified rows are successful" |
| `overpaid_kobo` | `BIGINT` | yes | [REC] How much of this payment exceeded the balance when applied. PRD asks for `overpaid_kobo` on the *event*; keeping it on the row too makes a refund list a single query. The event still carries it |
| `review_reason` | `VARCHAR(32)` | yes | **New in v2 (D-3).** Presence means "a human must look at this payment": `overpaid` or `paid_cancelled_transaction`. It is a flag, not a state — the payment stays `successful` and the money stays recorded. Closed set enforced by CHECK |
| `provider_mode` | `VARCHAR(8)` | no | **New in v2 (D-10).** `sandbox` or `live`, stamped from `Settings.kora_mode` at attempt creation. Makes a sandbox payment provably distinguishable from real money months later, and survives a later switch to live keys |
| `idempotency_key` | `UUID` | yes | [REC] Echo of the client's `Idempotency-Key` header on pay initialization. Unique per transaction, so a double-tap returns the same checkout instead of a second charge (§8.8) |

`ck_pay_success_fields` is the anti-forgery constraint at the database level: **a row cannot be `successful` without `verified_at`**. Even a buggy service cannot mark a payment successful from the redirect alone.

`review_reason` deliberately cannot make a row non-`successful`: a flag that could hide money would be worse than no flag. The pair (`status='successful'`, `review_reason IS NOT NULL`) is exactly the ops worklist, served by `ix_pay_review`.

### 5.3.5 `debtor_responses`

```sql
CREATE TYPE debtor_response_type  AS ENUM ('acknowledge','promise','dispute');
CREATE TYPE promise_status        AS ENUM ('open','kept','missed','superseded');
CREATE TYPE dispute_reason_type   AS ENUM
    ('wrong_amount','goods_not_received','already_paid','other');

CREATE TABLE debtor_responses (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id       UUID NOT NULL REFERENCES credit_transactions(id) ON DELETE RESTRICT,
    type                 debtor_response_type NOT NULL,
    promised_date        DATE NULL,
    promised_amount_kobo BIGINT NULL,
    message              TEXT NULL,
    promise_status       promise_status NULL,
    dispute_reason       dispute_reason_type NULL,
    resolved_at          TIMESTAMPTZ NULL,
    resolution_note      TEXT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_dr_promise_fields CHECK (
        (type <> 'promise')
        OR (promised_date IS NOT NULL AND promise_status IS NOT NULL)
    ),
    CONSTRAINT ck_dr_promise_amount CHECK (
        promised_amount_kobo IS NULL OR promised_amount_kobo > 0
    ),
    CONSTRAINT ck_dr_promise_status_scope CHECK (
        (type = 'promise') OR (promise_status IS NULL)
    ),
    CONSTRAINT ck_dr_dispute_fields CHECK (
        (type <> 'dispute')
        OR (dispute_reason IS NOT NULL AND message IS NOT NULL
            AND char_length(trim(message)) > 0)
    ),
    CONSTRAINT ck_dr_dispute_reason_scope CHECK (
        (type = 'dispute') OR (dispute_reason IS NULL)
    )
);

CREATE INDEX ix_dr_transaction ON debtor_responses (transaction_id, created_at DESC);
CREATE INDEX ix_dr_promise_outcome ON debtor_responses (type, promise_status);

-- One open promise per transaction, enforced by the database (PRD §7.3)
CREATE UNIQUE INDEX uq_dr_one_open_promise ON debtor_responses (transaction_id)
    WHERE type = 'promise' AND promise_status = 'open';

-- One unresolved dispute per transaction (a dispute is resolved before another is raised)
CREATE UNIQUE INDEX uq_dr_one_open_dispute ON debtor_responses (transaction_id)
    WHERE type = 'dispute' AND resolved_at IS NULL;
```

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `type` | enum | no | `acknowledge` rows are written for the trail; they carry no promise/dispute fields |
| `promised_date` | `DATE` | promise only | Today (WAT) … today + 60 days (PRD §8.3) |
| `promised_amount_kobo` | `BIGINT` | yes | Optional; when omitted the service stores `NULL` and "the promise" means the full balance at promise time. **The frontend may send the balance explicitly — the demo does** |
| `message` | `TEXT` | yes for promise, required for dispute | Never scraped, parsed, or scored |
| `promise_status` | enum | promise only | `open` → `kept` \| `missed` \| `superseded` |
| `dispute_reason` | enum | dispute only | Four values exactly as PRD §8.3 |
| `resolved_at` / `resolution_note` | | dispute only | Both set together on resolve |

**Why the two partial unique indexes matter:** PRD rules "only one promise can be open" and "resolve before re-disputing". Application code can be raced (two browser tabs, a retry). The index turns a race into an `IntegrityError` the service maps to a clean 409, instead of two open promises corrupting the score denominator.

### 5.3.6 `reminders`

```sql
CREATE TYPE reminder_kind   AS ENUM
    ('new_credit','upcoming','due_today','overdue_1','overdue_followup','manual');
CREATE TYPE reminder_status AS ENUM
    ('scheduled','sent','failed','cancelled','skipped');

CREATE TABLE reminders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id      UUID NOT NULL REFERENCES credit_transactions(id) ON DELETE RESTRICT,
    kind                reminder_kind NOT NULL,
    channel             VARCHAR(16) NOT NULL DEFAULT 'email',
    scheduled_for       TIMESTAMPTZ NOT NULL,
    status              reminder_status NOT NULL DEFAULT 'scheduled',
    skip_reason         VARCHAR(40) NULL,
    sent_at             TIMESTAMPTZ NULL,
    provider_message_id VARCHAR(120) NULL,
    error               TEXT NULL,
    attempt_count       INTEGER NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_rem_channel CHECK (channel IN ('email')),
    CONSTRAINT ck_rem_sent_fields CHECK (
        (status <> 'sent') OR (sent_at IS NOT NULL)
    ),
    CONSTRAINT ck_rem_skip_reason CHECK (
        (status <> 'skipped') OR (skip_reason IS NOT NULL)
    )
);

-- the job's work queue: exactly the predicate it queries
CREATE INDEX ix_rem_due ON reminders (scheduled_for)
    WHERE status = 'scheduled';
CREATE INDEX ix_rem_transaction ON reminders (transaction_id, status, scheduled_for);
```

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `kind` | enum | no | Six kinds, PRD §7.2 |
| `channel` | `VARCHAR(16)` | no | Only `email`. [REC] CHECK instead of a one-value enum (ADR-9) |
| `scheduled_for` | `TIMESTAMPTZ` | no | Always a WAT-9:00 instant expressed in UTC, except `manual` which is "now" |
| `status` | enum | no | Five values, PRD §7.2 |
| `skip_reason` | `VARCHAR(40)` | yes when skipped | `settled`, `cancelled`, `disputed`. **Required** by CHECK when skipped so the UI can explain why |
| `provider_message_id` | `VARCHAR(120)` | yes | Resend message id — the join key for deliverability debugging |
| `error` | `TEXT` | yes | Truncated provider error (≤500 chars) |
| `attempt_count` | `INTEGER` | no | [REC] Operational column for retry limits. PRD's table is a minimum, not a ban on operational columns |
| `locked_until` | `TIMESTAMPTZ` | yes | [REC] Claim marker so a crashed worker's rows become claimable again after 5 minutes |

**Index choice:** the partial index `WHERE status='scheduled'` is the entire job's access path. As transactions settle, the index shrinks; the job never scans history.

### 5.3.7 `transaction_events`

```sql
CREATE TYPE event_actor AS ENUM ('creditor','debtor','system');

CREATE TABLE transaction_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id UUID NOT NULL REFERENCES credit_transactions(id) ON DELETE RESTRICT,
    type           VARCHAR(48) NOT NULL,
    actor          event_actor NOT NULL,
    data           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_te_type CHECK (type IN (
        'transaction_created',
        'reminder_sent','reminder_failed',
        'debtor_acknowledged',
        'promise_made','promise_kept','promise_missed',
        'payment_received','payment_failed',
        'dispute_raised','dispute_resolved',
        'note_added',
        'settled','cancelled'
    ))
);

CREATE INDEX ix_te_transaction ON transaction_events (transaction_id, created_at DESC);
```

| Column | Type | Null | Notes |
| --- | --- | --- | --- |
| `type` | `VARCHAR(48)` | no | The 14 PRD §8.7 types. [REC] `VARCHAR + CHECK` rather than enum (ADR-9): event types are append-only and most likely to grow; adding one is a check-constraint swap with no type rewrite |
| `actor` | enum | no | `creditor`, `debtor`, `system` — exactly PRD §8.7 |
| `data` | `JSONB` | no | Rendered strings + machine fields. Per-type keys in §7.3 |

**Append-only is a discipline, not a trigger:** no service ever issues `UPDATE transaction_events`. A DB trigger `BEFORE UPDATE OR DELETE … RAISE EXCEPTION` is tempting, but it could block a legitimate data fix on demo day. Recommend a review rule now and the trigger post-MVP (ADR-10).

### 5.3.8 `kora_webhook_events` [REC — new table]

The PRD's schema does not include this. It is the cheapest way to satisfy two PRD rules at once — "webhooks must be idempotent" and "complete audit trail" — without relying on `payments.status` alone.

```sql
CREATE TABLE kora_webhook_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kora_reference VARCHAR(80) NOT NULL,
    event          VARCHAR(40) NOT NULL,
    signature_ok   BOOLEAN NOT NULL,
    payload        JSONB NOT NULL,
    processed_at   TIMESTAMPTZ NULL,
    outcome        VARCHAR(40) NULL,     -- applied | duplicate | ignored | rejected | error:<reason>
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_kwe_ref_event UNIQUE (kora_reference, event)
);

CREATE INDEX ix_kwe_created ON kora_webhook_events (created_at DESC);
```

Insert with `ON CONFLICT (kora_reference, event) DO NOTHING`; `rowcount == 0` ⇒ duplicate delivery ⇒ return 200 immediately. `signature_ok=false` rows are recorded (payload + reason) but never processed — that record is what makes a signature incident diagnosable.

`outcome` is a closed vocabulary written by the handler: `applied` · `applied:raw` / `applied:canon` (which signature strategy matched) · `duplicate` · `ignored` · **`unknown_reference`** · `rejected` · `error:<reason>`.

**There is deliberately no FK to `payments`.** A webhook whose reference matches no row must still be recordable — that is the whole point of the `unknown_reference` outcome (D-8): the event is stored, the response is `200`, and no payment or balance is touched. A nullable FK would invite a lookup-then-insert race for no benefit; `kora_reference` is a plain indexed string.

**Trade-off:** one extra write per webhook, one extra table. In exchange, replays are provably idempotent, and "did Kora send it and what did we do with it" is answerable months later. Justified in ADR-11.

## 5.4 Enumerations and derived values

### 5.4.1 Stored status vs display status

```python
# app/modules/transactions/balance.py

class TransactionStatus(StrEnum):
    PENDING_ACK    = "pending_ack"
    ACTIVE         = "active"
    PARTIALLY_PAID = "partially_paid"
    DISPUTED       = "disputed"
    SETTLED        = "settled"
    CANCELLED      = "cancelled"

class DisplayStatus(StrEnum):
    PENDING        = "pending"
    ACTIVE         = "active"
    PARTIALLY_PAID = "partially_paid"
    OVERDUE        = "overdue"
    DISPUTED       = "disputed"
    SETTLED        = "settled"
    CANCELLED      = "cancelled"

def display_status(tx, balance_kobo: int, today: date) -> DisplayStatus:
    # precedence is fixed by PRD §5: cancelled -> settled -> disputed -> overdue -> stored
    if tx.status is TransactionStatus.CANCELLED:  return DisplayStatus.CANCELLED
    if tx.status is TransactionStatus.SETTLED:    return DisplayStatus.SETTLED
    if tx.status is TransactionStatus.DISPUTED:   return DisplayStatus.DISPUTED
    if balance_kobo > 0 and tx.due_date < today:  return DisplayStatus.OVERDUE
    return DisplayStatus(tx.status.value)
```

`pending_ack` is the API's `display_status='pending'` — the PRD's badge list says "Pending (grey)" while the stored value is `pending_ack`. One mapping, one place.

### 5.4.2 Enum inventory

| Enum | Values | Where defined |
| --- | --- | --- |
| `credit_transaction_status` | pending_ack, active, partially_paid, disputed, settled, cancelled | `app/db/enums.py` |
| `payment_status` | initiated, pending, successful, failed, reversed | `app/db/enums.py` |
| `debtor_response_type` | acknowledge, promise, dispute | `app/db/enums.py` |
| `promise_status` | open, kept, missed, superseded | `app/db/enums.py` |
| `dispute_reason_type` | wrong_amount, goods_not_received, already_paid, other | `app/db/enums.py` |
| `reminder_kind` | new_credit, upcoming, due_today, overdue_1, overdue_followup, manual | `app/db/enums.py` |
| `reminder_status` | scheduled, sent, failed, cancelled, skipped | `app/db/enums.py` |
| `event_actor` | creditor, debtor, system | `app/db/enums.py` |
| `transaction_events.type` | 14 values (CHECK) | `app/modules/transactions/events.py` |
| `reminders.channel` | email (CHECK) | migration |

Python mirrors each in a `StrEnum` so `Literal[...]` and Pydantic validation come from one source.

### 5.4.3 The one-open-promise transition, in one statement

```sql
-- inside the promise-creation transaction, after locking the transaction row
UPDATE debtor_responses
   SET promise_status = 'superseded', updated_at = now()
 WHERE transaction_id = :tx_id
   AND type = 'promise'
   AND promise_status = 'open';

INSERT INTO debtor_responses
       (transaction_id, type, promised_date, promised_amount_kobo, message, promise_status)
VALUES (:tx_id, 'promise', :date, :amount, :message, 'open');
```

Superseding is not optional bookkeeping: the score's `promise_rate` denominator counts only `kept` and `missed`, so a superseded promise can neither help nor hurt. PRD §7.3 says exactly this.

## 5.5 Index summary and the query each one serves

| Index | Table | Serves |
| --- | --- | --- |
| `uq_debtors_business_email` | debtors | 409 `DEBTOR_EXISTS` check |
| `ix_debtors_business_name` | debtors | `GET /debtors?q=` search, list ordering |
| `ix_ct_business_status` | credit_transactions | PRD-required; list filters, dashboard status counts |
| `ix_ct_business_due` | credit_transactions | "due in next 7 days", overdue lists, reminder rebuilds |
| `ix_ct_open_by_business` (partial) | credit_transactions | `business_outstanding()` — the hottest aggregate in the product |
| `ix_ct_debtor` | credit_transactions | debtor profile, per-debtor capacity, score |
| `uq_ct_public_token` | credit_transactions | every `/public/tx/{token}` request |
| `ix_pay_transaction` | payments | balance for one transaction; payments list on the details page |
| `ix_pay_received` (partial) | payments | "total paid" and receipt ordering, successful rows only |
| `uq_pay_kora_reference` | payments | webhook/verify lookup — the most latency-sensitive lookup here |
| `ix_pay_review` (partial) | payments | the ops worklist: overpaid and paid-cancelled payments, newest first |
| `ix_dr_transaction` | debtor_responses | timeline, open promise on the details page |
| `ix_rem_due` (partial) | reminders | the 15-minute job |
| `ix_rem_transaction` | reminders | "upcoming reminders" panel, rebuild, dispute cancel |
| `ix_te_transaction` | transaction_events | timeline (newest first) |
| `ix_kwe_created` | kora_webhook_events | incident triage |

**Deliberately absent:** an index on `credit_transactions.status` alone (low selectivity, the composite covers it); any index on `notes` (no search requirement); a GIN index on `transaction_events.data` (nothing queries inside `data`; it is rendered as text).

## 5.6 Invariants the schema guarantees

| Invariant | Mechanism |
| --- | --- |
| No two debtors with the same email in one business | unique index on `(business_id, lower(email))` |
| No two transactions share a reference or a public token | unique constraints |
| No two payments share a Kora reference or receipt number | unique constraints |
| No two payments share an attempt number in a transaction | `UNIQUE(transaction_id, attempt_number)` |
| At most one open promise / one unresolved dispute per transaction | partial unique indexes |
| A successful payment was verified server-side | `ck_pay_success_fields` |
| Override always has a reason | `ck_ct_override_reason` |
| Skipped reminders always explain why | `ck_rem_skip_reason` |
| Dispute always has a reason and a message | `ck_dr_dispute_fields` |
| Money is always positive where it must be | `CHECK (… > 0)` on every amount column |
| A payment needing review always says why, from a closed set | `ck_pay_review_reason` |
| A payment was taken in a known provider mode | `ck_pay_provider_mode`, stamped at creation |
| Financial history is never cascaded away | `ON DELETE RESTRICT` on every FK |

What the schema **cannot** enforce, and the service must: that a payment does not exceed the balance (overpayment is legal and clamped on read), that `status` agrees with payments (only `PaymentService` and `CreditTransactionService` write it), and that reminders after a dispute are consistent (the rebuild function owns that).

## 5.7 Transactions and concurrency control

### 5.7.1 Isolation level

Default **READ COMMITTED** everywhere. That is sufficient because every cross-row invariant is protected by an explicit row lock, not by snapshot isolation:

| Operation | Lock taken | Why |
| --- | --- | --- |
| `POST /transactions` (capacity check) | `SELECT … FROM businesses WHERE id=:bid FOR UPDATE` | Two concurrent creates both reading `outstanding` would both pass the limit. Serialising on the business row costs milliseconds and is correct |
| Payment attempt allocation | `SELECT … FROM credit_transactions WHERE id=:id FOR UPDATE` | Guarantees `max(attempt_number)+1` cannot collide; converts the unique constraint into a friendly retry instead of a 500 |
| `apply_verified_charge` | `SELECT payment … FOR UPDATE`, then `SELECT credit_transactions … FOR UPDATE` — always in that order, and **only after** the Kora verify call has returned | Idempotency (a second webhook sees `successful` and stops) plus a balance recomputed from verified payments while the transaction row is held (§8.6.2) |
| Promise create / dispute create | `SELECT transaction … FOR UPDATE` | Serialises supersede-then-insert so the partial unique index is never hit in normal operation |
| Cancel / resolve dispute | `SELECT transaction … FOR UPDATE` | Prevents a payment landing between "read balance" and "write status" |
| Reminder claim | `UPDATE … SET locked_until = now() + interval '5 minutes' WHERE id IN (SELECT id … FOR UPDATE SKIP LOCKED) RETURNING *` | Two workers, or overlapping ticks, can never send the same reminder |

**Lock ordering is fixed: `payments` → `credit_transactions` → `debtor_responses` → `reminders`.** Taking them in another order is how deadlocks are born; this is a review rule, and §12.11 exercises two concurrent payments.

### 5.7.2 The capacity race, worked through

```
T1: BEGIN; LOCK business B; outstanding = 4,900,000; limit = 5,000,000; amount = 150,000 -> ok
T2: BEGIN; LOCK business B;                                   -- blocks
T1: INSERT tx; outstanding becomes 5,050,000; COMMIT
T2: -- acquires lock; re-reads outstanding = 5,050,000; +150,000 exceeds limit -> 422 CAPACITY_EXCEEDED
```

Without the lock, T2 reads the pre-T1 outstanding, both insert, and the business is silently over its limit — precisely the failure the PRD's "re-run the capacity check, never trusting the frontend" exists to prevent.

**Cost:** transaction creation is serialised *per business*. At MVP volume (tens per day) this is free. At thousands per second, the fix is a single `INSERT … SELECT … WHERE (SELECT sum(…)) <= limit` statement or a maintained counter — explicitly not MVP work (ADR-6).

### 5.7.3 Why not `SERIALIZABLE`

It would force retry loops in the request path for zero MVP benefit, and PostgreSQL serialization failures would surface as 500s without careful handling. Row locks express the actual contention — one business's capacity, one transaction's payments — precisely.

### 5.7.4 Session and transaction discipline

- One `Session` per request via `get_db`. **The service owns `commit()`** — not the route, not the dependency. There is no auto-commit anywhere.
- Services call external systems **after** `commit()` (§3.4), so no HTTP call ever holds a database transaction open.
- `SessionLocal` is configured `autoflush=False` today; keep it and `flush()` explicitly where an INSERT's generated id is needed before the next statement.
- A retry wrapper (max 2 attempts) exists **only** for `IntegrityError` on races that are safe to retry: reference allocation and attempt-number allocation.

### 5.7.5 Two successful payments at once (the overpayment race)

This is the one race in the system where **both** contenders are legitimate money, so it cannot be prevented — only serialised and accounted for. Two tabs (or a phone and a laptop) both show ₦50,000 outstanding and both pay in full; Kora will charge both.

```
P1 and P2 are different `payments` rows for the same transaction, both `pending`,
both with kora_reference CRD-000123-P1 / -P2. Both webhooks verify as success
(gross amount 5,000,000 kobo each, currency NGN).

T1 (P1): BEGIN; LOCK payment(P1);  status != successful -> proceed
T2 (P2): BEGIN; LOCK payment(P2);  status != successful -> proceed   # different row: no contention
T1:      LOCK transaction(T);  Σ successful = 0            -> balance_before = 5,000,000
T2:      LOCK transaction(T)   -- BLOCKS on T1's row lock
T1:      P1 successful; overpaid = 0; balance_after = 0
         tx.status = 'settled'; settled_at = now()
         events: payment_received, settled; reminders cancelled
         COMMIT                       -- releases transaction lock
T2:      -- acquires the lock, re-reads inside it:
         Σ successful = 5,000,000        (P1 is already committed)
         balance_before = max(5,000,000 − 5,000,000, 0) = 0
         overpaid = 5,000,000
         P2 successful; P2.overpaid_kobo = 5,000,000
         P2.review_reason = 'overpaid'
         balance_after = 0               (clamped, structurally)
         tx.status already 'settled' -> NO second settled transition
         events: payment_received (with overpaid_kobo); NO second 'settled' event
         COMMIT
After commit: T1 sends email #7; T2 sends email #6 (receipt for P2). Never two #7s.
```

Four things make this correct, and each has a test in §12.11:

| Requirement | Mechanism |
| --- | --- |
| Both payments are recorded | neither branch can mark a verified success `failed` |
| The balance is computed from verified payments, not decremented | `Σ successful` is read **inside** the transaction-row lock, after the current row is marked successful in step order (§8.6) |
| Settlement side effects fire once | every settlement side effect is gated on the *transition* into `settled`, evaluated against the freshly locked row; a second payment that finds `settled` skips them |
| The overpayment is visible and actionable | `overpaid_kobo` + `review_reason='overpaid'` + `payment_received.data.overpaid_kobo`, listed by `ix_pay_review` |

No deadlock is possible between two payments: each transaction holds exactly one `payments` row lock and then contends for the same `credit_transactions` row, which is the fixed lock order in §5.7.1. The loser simply waits for the winner's commit and then sees the truth.

## 5.8 Required migrations

Eight revisions after the existing `fe6a8d47a7b6`, split by table so each is reviewable in isolation and a failure has one obvious cause.

| Rev | Down-rev | Contents | Reversible |
| --- | --- | --- | --- |
| `fe6a8d47a7b6` | — | existing `businesses` | already applied |
| `0002_business_credit_limit_logo` | fe6a… | `ALTER businesses ADD credit_limit_kobo, logo_url` + CHECK | yes |
| `0003_debtors` | 0002 | create `debtors` + 2 indexes (ALTER path if the table already exists) | yes |
| `0004_credit_transactions` | 0003 | enum, sequence, table, 5 indexes | yes |
| `0005_payments` | 0004 | enum, sequence, table, 3 indexes | yes |
| `0006_debtor_responses` | 0005 | 3 enums, table, 2 indexes + 2 partial uniques | yes |
| `0007_reminders` | 0006 | 2 enums, table, 2 indexes | yes |
| `0008_transaction_events` | 0007 | actor enum, table, 1 index + type CHECK | yes |
| `0009_kora_webhook_events` | 0008 | [REC] table + 2 indexes | yes |

Every revision must pass `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`. Enums/sequences created inside a migration transaction do roll back on PG ≥ 14 (all managed providers here), but `downgrade()` must still `DROP TYPE` / `DROP SEQUENCE` explicitly.

**The `debtors` decision path [CONFLICT-2]:**

```python
def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(sa.text("SELECT to_regclass('public.debtors')")).scalar()
    if exists is None:
        op.create_table("debtors", ...)          # expected path, §5.3.2
    else:
        # defensive: someone ran Base.metadata.create_all()
        op.add_column("debtors", sa.Column("business_id", sa.Uuid(), nullable=True))
        op.add_column("debtors", sa.Column("name", sa.String(120), nullable=True))
        # ... remaining columns
        op.drop_constraint("debtors_email_key", "debtors", type_="unique")
        # then, only if row count == 0, SET NOT NULL; otherwise raise for a human
```

The `else` branch must **refuse** to `SET NOT NULL` if the table has rows: a human must decide where orphan debtors belong. A silent backfill of financial rows is worse than a failed migration.

**Autogenerate caveat:** `alembic revision --autogenerate` orders `CREATE TYPE` incorrectly for multiple enums in one revision and will not emit partial indexes unless they are declared in `__table_args__` with `postgresql_where`. All eight migrations are to be **hand-written and reviewed**, with autogenerate used only as an after-the-fact diff check. This is stated because it is the most common "works locally, fails on the host" migration bug.

## 5.9 Data volume and retention

| Table | MVP growth | Retention |
| --- | --- | --- |
| `credit_transactions` | tens/day | forever (financial record) |
| `payments` | 1–3 per transaction | forever |
| `transaction_events` | 10–20 per transaction | forever; read paths paginate |
| `reminders` | ~5 per transaction + weekly follow-ups | forever; the partial index keeps the job cheap |
| `kora_webhook_events` | 1–3 per payment attempt | 90 days would suffice; no deletion job in MVP (§16 R-9) |

No archival, partitioning or delete jobs are in scope. At demo volume every table is small enough to scan; the indexes exist so the design is not the ceiling later.

---

# 6. API Specifications

## 6.0 Route index — all 24 PRD §9 routes accounted for

| # | Method | Route | Auth | Section |
| --- | --- | --- | --- | --- |
| 1 | GET | `/business` | JWT | §6.3.1 |
| 2 | PATCH | `/business/credit-limit` | JWT | §6.3.2 |
| 3 | GET | `/capacity` | JWT | §6.3.3 |
| 4 | GET | `/dashboard/summary` | JWT | §6.3.4 |
| 5 | GET | `/debtors` | JWT | §6.4.1 |
| 6 | POST | `/debtors` | JWT | §6.4.2 |
| 7 | PATCH | `/debtors/:id` | JWT | §6.4.3 |
| 8 | GET | `/debtors/:id` | JWT | §6.4.4 |
| 9 | POST | `/transactions` | JWT | §6.5.1 |
| 10 | GET | `/transactions` | JWT | §6.5.2 |
| 11 | GET | `/transactions/:id` | JWT | §6.5.3 |
| 12 | POST | `/transactions/:id/remind` | JWT | §6.5.4 |
| 13 | POST | `/transactions/:id/notes` | JWT | §6.5.5 |
| 14 | POST | `/transactions/:id/resolve-dispute` | JWT | §6.5.6 |
| 15 | POST | `/transactions/:id/cancel` | JWT | §6.5.7 |
| 16 | GET | `/transactions/:id/payments/:pid/receipt` | JWT | §6.6.1 |
| 17 | GET | `/public/tx/:token` | token | §6.7.1 |
| 18 | POST | `/public/tx/:token/acknowledge` | token | §6.7.2 |
| 19 | POST | `/public/tx/:token/pay` | token | §6.7.3 |
| 20 | GET | `/public/tx/:token/payments/:ref` | token | §6.7.4 |
| 21 | POST | `/public/tx/:token/promise` | token | §6.7.5 |
| 22 | POST | `/public/tx/:token/dispute` | token | §6.7.6 |
| 23 | GET | `/public/tx/:token/receipts/:receipt_number` | token | §6.7.7 |
| 24 | POST | `/webhooks/kora` | HMAC | §6.8.1 |

Existing routes remain: `POST /auth/register`, `POST /auth/login`, `GET /me`, `GET /health`. Their shapes do not change; only their *error* shape changes (envelope, §11.8).

## 6.1 API conventions

### 6.1.1 Success shape

- Single resource: the object itself, no wrapper. (PRD examples — `/capacity` — show a bare object.)
- Lists: `{"data": [...], "meta": {"page": 1, "limit": 20, "total": 37, "total_pages": 2}}`. **[REC]** — PRD §9 says lists take `?page=&limit=` but does not fix the envelope.
- Creation: `201` with the full resource (plus `pay_link`/`reminders` for transactions).
- Mutations that produce no new resource: `200` with the updated resource.
- Deletions: none exist. Cancellation is a status transition, so it returns `200`.

### 6.1.2 Error envelope

```json
{
  "error": {
    "code": "CAPACITY_EXCEEDED",
    "message": "This transaction exceeds the business credit limit by ₦250,000.00.",
    "fields": { "override": "Send override=true and override_reason to proceed." }
  }
}
```

| Field | Type | Rules |
| --- | --- | --- |
| `code` | `string` | `SCREAMING_SNAKE`, stable, machine-readable. Catalogue in §6.1.4 |
| `message` | `string` | Human-readable, safe to display, no stack traces or SQL |
| `fields` | `object \| null` | Field-name → reason. Populated for validation errors |

`message` may contain formatted naira for UX, but **never** a secret, token, provider credential or raw driver error.

### 6.1.3 Status code map

| Code | When |
| --- | --- |
| `200` | Successful read or mutation |
| `201` | Resource created (`POST /debtors`, `POST /transactions`, public promise/dispute creation) |
| `204` | Not used (HTML/PDF downloads return 200) |
| `400` | Malformed body (unparseable JSON), bad cursor, unsupported `format` |
| `401` | Missing/expired/invalid JWT; invalid webhook signature; bad public token is `404`, not `401` (see §11.2) |
| `403` | Authenticated but not allowed — reserved for future roles; unused in MVP |
| `404` | Resource not found **in this business**; unknown token; unknown receipt number |
| `409` | State conflict: `DEBTOR_EXISTS`, `TX_NOT_PAYABLE`, `TX_ALREADY_DISPUTED`, `TX_ALREADY_RESOLVED`, `PROMISE_ALREADY_OPEN` (only when a conflicting open promise exists and the retry is not identical), `REMINDER_TOO_SOON` |
| `422` | Validation failure, `CAPACITY_EXCEEDED`, business-rule violation with a fixable remedy |
| `429` | Rate limit (public routes) or manual-reminder cooldown |
| `500` | Unhandled. Logged with `request_id`; message is generic |
| `502`/`503` | Kora or email provider failed in a way the caller must retry |

### 6.1.4 Error code catalogue

| Code | HTTP | Raised by |
| --- | --- | --- |
| `UNAUTHORIZED` | 401 | auth dependency |
| `VALIDATION_ERROR` | 422 | `RequestValidationError` handler |
| `NOT_FOUND` | 404 | any `:id` lookup |
| `DEBTOR_EXISTS` | 409 | `POST /debtors`, inline create in `POST /transactions` |
| `CAPACITY_EXCEEDED` | 422 | capacity service |
| `INVALID_DATE_RANGE` | 422 | transaction create (`due_date < issue_date`), promise window |
| `TXN_NOT_PAYABLE` | 409 | public pay |
| `TXN_NOT_FOUND` | 404 | public routes |
| `TXN_SETTLED` / `TXN_CANCELLED` | 409 | public actions on terminal transactions |
| `PROMISE_WINDOW_INVALID` | 422 | promise date beyond 60 days |
| `DISPUTE_ALREADY_OPEN` | 409 | second dispute |
| `DISPUTE_NOT_OPEN` | 409 | resolve with nothing open |
| `REMINDER_TOO_SOON` | 429 | manual remind within 1h |
| `REMINDER_NOT_ALLOWED` | 409 | manual remind on disputed/settled/cancelled |
| `PAYMENT_INIT_FAILED` | 502 | Kora initialize error |
| `IDEMPOTENCY_KEY_REUSED` | 409 | `POST /pay` with an existing key but a different amount, or a key already used by a failed attempt |
| `AMOUNT_OUT_OF_RANGE` | 422 | public pay amount below min / above balance |
| `WEBHOOK_SIGNATURE_INVALID` | 401 | webhook |
| `PAYMENT_NOT_FOUND` | 404 | payment status/receipt with a ref not in this transaction |
| `RATE_LIMITED` | 429 | slowapi |
| `INTERNAL_ERROR` | 500 | last-resort handler |

### 6.1.5 Money, dates, ids in transit

- Every monetary value: JSON **integer** kobo, property suffixed `_kobo`. No strings, no decimals, no naira in the API.
- Dates: `"YYYY-MM-DD"` (date-only). Timestamps: ISO-8601 with `Z` (`"2026-11-20T10:15:00Z"`); never naive.
- Ids: UUID strings.
- Enums: lowercase strings exactly as §5.4.2.

### 6.1.6 Pagination and filtering

`page` ≥ 1 (default 1), `limit` ∈ [1, 100] (default 20). Out-of-range values are clamped, not rejected — a frontend bug should not break a dashboard. `meta.total_pages = ceil(total / limit)`.

## 6.2 Cross-cutting response objects

Defined once here, referenced by name below.

**`TransactionSummary`**

```json
{
  "id": "8f14e45f-ea9c-4f1b-9b7d-1a2b3c4d5e6f",
  "reference": "CRD-000123",
  "invoice_number": "INV-0042",
  "debtor": { "id": "…", "name": "Bright Foods Ltd" },
  "description": "50 bags of rice",
  "amount_kobo": 15000000,
  "paid_kobo": 10000000,
  "outstanding_kobo": 5000000,
  "issue_date": "2026-11-17",
  "due_date": "2026-11-27",
  "status": "partially_paid",
  "display_status": "partially_paid",
  "days_overdue": 0,
  "has_open_promise": true,
  "has_open_dispute": false,
  "next_reminder": { "kind": "upcoming", "scheduled_for": "2026-11-24T08:00:00Z" },
  "created_at": "2026-11-17T09:12:03Z"
}
```

`paid_kobo`/`outstanding_kobo` are always computed. `days_overdue` = `today_wat − due_date` when overdue, else `0`. `next_reminder` is the earliest `scheduled` reminder, or `null`.

**`ScoreBlock`** — see §10.6 for the full shape and how `facts` is built.

**`ReminderSummary`**

```json
{ "id": "…", "kind": "upcoming", "channel": "email", "scheduled_for": "2026-11-24T08:00:00Z",
  "status": "scheduled", "sent_at": null, "skip_reason": null, "error": null }
```

**`PaymentSummary`**

```json
{ "id": "…", "kora_reference": "CRD-000123-P1", "amount_kobo": 10000000,
  "status": "successful", "paid_at": "2026-11-20T11:02:44Z",
  "receipt_number": "RCT-000045", "checkout_url": null,
  "receipt_url": "/transactions/…/payments/…/receipt",
  "public_receipt_url": "/public/tx/…/receipts/RCT-000045" }
```

`raw_webhook` is **never** serialised. `checkout_url` is only present for a payment the caller just created.

## 6.3 Business, capacity, dashboard

### 6.3.1 `GET /business`

| | |
| --- | --- |
| Auth | Bearer JWT |
| Purpose | Business profile including the credit limit and logo (PRD §9) |
| Query | none |

**Response 200**

```json
{
  "id": "…", "name": "Adeyemi Wholesale Ltd", "email": "ops@adeyemi.ng",
  "phone": "+2348012345678", "address": "12 Marina, Lagos",
  "registration_number": "RC-1234567", "category": "wholesale_distribution",
  "credit_limit_kobo": 500000000, "logo_url": null,
  "created_at": "2026-11-07T10:00:00Z"
}
```

**Logic:** the `Business` object from the dependency, projected through `BusinessSchema`. No query.

**Tables:** `businesses` (read; already loaded).

**Errors:** 401.

### 6.3.2 `PATCH /business/credit-limit`

| | |
| --- | --- |
| Auth | JWT |
| Purpose | Set or clear `credit_limit_kobo` (PRD §8.1) |

**Request**

```json
{ "credit_limit_kobo": 500000000 }
```

| Field | Type | Rules |
| --- | --- | --- |
| `credit_limit_kobo` | `int \| null` | Required key. `null` clears the limit. If an integer: `> 0`, `≤ 9_000_000_000_000` (₦90bn sanity ceiling). Naira floats rejected by type |

**Response 200:** the `GET /business` payload.

**Validation**
- `null` ⇒ clear.
- `0` or negative ⇒ `422 VALIDATION_ERROR` with `fields.credit_limit_kobo = "Must be greater than 0, or null to remove the limit."` (PRD §8.1: "Optional, and greater than 0 if set; null clears it.")
- Body with extra keys ⇒ ignored (Pydantic default) or rejected if `extra="forbid"` is set — **[REC]** use `extra="forbid"` on all write schemas so a frontend typo is a visible 422 rather than a silent no-op.

**Business logic:** assign, commit, return. No event row: the limit is a business setting, not transaction activity. (PRD §4 says "every write that matters" writes a `transaction_events` row — events are scoped to a transaction, so a business-level setting has no transaction to attach to. This is a deliberate reading; see §16 Q-5.)

**Tables:** `businesses` (update).

**Errors:** 401, 422.

**Audit trail for a credit-limit change (D-9, ADR-21).** A credit-limit change is a *business-level* fact, not a transaction event, so it writes **no** `transaction_events` row — mixing the two would put "limit changed" into the middle of a debtor's debt timeline, where it does not belong and where the timeline and score readers would have to filter it out. Traceability comes from two signals, both already in the design:

| Signal | What it proves |
| --- | --- |
| `businesses.updated_at` | *that* the row changed, and when |
| one structured audit line per change: `event="business.credit_limit_changed"`, `business_id`, `old_credit_limit_kobo`, `new_credit_limit_kobo`, `actor` (the JWT's business id), `request_id`, `at` | *what* changed, by which authenticated business, in which request |

The line goes to the same structured JSON log stream as every request (§11.9), so it is durable in the platform log drain and greppable by `business_id`. Setting and clearing are both recorded (`new_credit_limit_kobo: null` for a clear). A dedicated `business_activities` table is the correct long-term answer and is recorded as deferred (§15.6, §16.3) — not built now, because no MVP screen reads it.

### 6.3.3 `GET /capacity`

| | |
| --- | --- |
| Auth | JWT |
| Purpose | Live capacity check for the create form and the debounced preview (PRD §7.1, §8.2 C) |

**Query parameters**

| Param | Type | Rules |
| --- | --- | --- |
| `amount_kobo` | int, required | `> 0` |
| `debtor_id` | uuid, optional | Must belong to the business, else `404` |
| `debtor_limit_kobo` | int, optional | Used **instead of** `debtor_id` for a not-yet-created debtor. `> 0` |

`debtor_id` and `debtor_limit_kobo` together ⇒ `422` (`fields.debtor_id = "Send debtor_id or debtor_limit_kobo, not both."`). Neither ⇒ valid (business block only).

**Response 200** (exactly the PRD §7.1 shape, extended with the debt figures that make the bar renderable without a second call)

```json
{
  "business": { "limit": 500000000, "outstanding": 320000000, "available": 180000000 },
  "debtor":   { "limit": 80000000,  "outstanding": 60000000,  "available": 20000000 },
  "after_this": { "business_ok": true, "debtor_ok": false },
  "requires_override": true,
  "over_by_kobo": { "business": 0, "debtor": 5000000 }
}
```

`over_by_kobo` is **[REC]** additive: the PRD's UI copy says "This puts you ₦X over your limit", so the number must come from somewhere authoritative rather than being re-derived by the frontend. `available` is `null` when `limit` is `null`.

**Business logic** (`CreditCapacityService.check`)

1. `business_outstanding = Σ (amount_kobo − paid_kobo)` over transactions where `status NOT IN (settled, cancelled)` — disputed included (PRD §7.1).
2. `business_ok = limit is None or outstanding + amount ≤ limit`.
3. Debtor block if `debtor_id` (use the debtor's stored limit and its own outstanding) or if `debtor_limit_kobo` (limit given, outstanding = 0 for a new debtor). If neither and the debtor has no limit ⇒ `debtor: null`.
4. `requires_override = not business_ok or not debtor_ok`.
5. Debtor must be scoped: `debtor.business_id == business.id` else 404.

**Tables:** `businesses` (read), `credit_transactions` (aggregate), `payments` (aggregate), `debtors` (read).

**Errors:** 401, 404, 422.

**Performance note:** two aggregate queries, both index-covered (`ix_ct_open_by_business`, `ix_pay_received`). At 300ms debounce the create form issues ~3 calls/second worst case, well inside budget.

### 6.3.4 `GET /dashboard/summary`

| | |
| --- | --- |
| Auth | JWT |
| Purpose | Everything the dashboard needs in one call (PRD §9) |

**Response 200**

```json
{
  "totals": {
    "total_extended_kobo": 470000000,
    "total_outstanding_kobo": 320000000,
    "total_collected_kobo": 150000000,
    "overdue_amount_kobo": 45000000
  },
  "capacity": { "limit": 500000000, "outstanding": 320000000, "available": 180000000 },
  "recent_transactions": [ /* TransactionSummary ×5, created_at DESC */ ],
  "overdue": [ /* 5, with days_overdue + next_reminder, most overdue first */ ],
  "upcoming": [ /* all due within today..today+7 WAT, balance > 0 */ ],
  "recent_activity": [ /* 10 newest transaction_events across the business */ ]
}
```

**Definitions (must be exact, or the numbers will not tie to the lists):**

| Field | Definition |
| --- | --- |
| `total_extended_kobo` | `Σ amount_kobo` over `status NOT IN (cancelled)` — cancelled debt was never really extended, but settled debt *was* extended and collected |
| `total_outstanding_kobo` | `Σ max(amount − paid, 0)` over `status NOT IN (settled, cancelled)`, disputed included |
| `total_collected_kobo` | `Σ successful payments` for non-cancelled transactions. Equals extended − outstanding when no overpayment and no cancellation |
| `overdue_amount_kobo` | `Σ outstanding` where `due_date < today_wat` and `status NOT IN (settled, cancelled, disputed)` — **matches `display_status='overdue'` precedence** |
| `capacity.outstanding` | identical to `total_outstanding_kobo` (single helper, no second definition) |

**`recent_activity` item**

```json
{ "id": "…", "transaction_id": "…", "reference": "CRD-000123",
  "debtor_name": "Bright Foods Ltd", "type": "payment_received",
  "actor": "debtor", "text": "Paid ₦100,000.00 via Kora · receipt RCT-000045 · balance ₦50,000.00",
  "created_at": "2026-11-20T11:02:44Z" }
```

`text` is **rendered server-side** from `data` so the dashboard and the details timeline cannot diverge in wording. Rendering rules: §7.3.

**Tables:** `credit_transactions`, `payments`, `reminders`, `transaction_events`, `businesses`.

**Errors:** 401.

**Performance:** 6 queries total (totals, capacity reuse, recent, overdue + next reminder, upcoming, activity). All bounded by `LIMIT`. Acceptable at MVP; a single CTE could merge the four totals later (ADR-14, deferred).

## 6.4 Debtors

### 6.4.1 `GET /debtors`

| | |
| --- | --- |
| Auth | JWT |
| Query | `q` (optional, matches `name` or `email`, case-insensitive substring), `page`, `limit` |

**Response 200**

```json
{
  "data": [
    { "id": "…", "name": "Bright Foods Ltd", "contact_person": "Ada Obi",
      "email": "accounts@brightfoods.ng", "phone": "+2348098765432",
      "credit_limit_kobo": 80000000,
      "outstanding_kobo": 5000000, "overdue_kobo": 0, "open_disputes": 0,
      "has_open_promise": true,
      "score": { "value": 82, "label": "Strong repayment record", "category": "strong" },
      "created_at": "…" }
  ],
  "meta": { "page": 1, "limit": 20, "total": 4, "total_pages": 1 }
}
```

**Business logic**

1. Page debtors scoped to `business.id`, ordered `lower(name)`.
2. One grouped aggregate for `outstanding_kobo` / `overdue_kobo` over that page's debtor ids.
3. One query for open disputes count and open promise existence for that page.
4. **Scores computed for the page only** (19 debtors max), using one batched query set — never one query per debtor.

`score` on the list is the **summary only** (`value`, `label`, `category`); `facts` are omitted here to keep the payload small, and included on the profile and on create-form selection (§10.6).

**Tables:** `debtors`, `credit_transactions`, `payments`, `debtor_responses`.

**Errors:** 401.

### 6.4.2 `POST /debtors`

**Request**

```json
{ "name": "Bright Foods Ltd", "contact_person": "Ada Obi",
  "email": "accounts@brightfoods.ng", "phone": "+2348098765432",
  "credit_limit_kobo": 80000000, "address": "9 Adeola Odeku, VI, Lagos" }
```

| Field | Type | Rules |
| --- | --- | --- |
| `name` | str | 2–120, trimmed, non-blank |
| `contact_person` | str? | ≤120 |
| `email` | EmailStr | Required, valid, ≤254, lowercased |
| `phone` | str | Required. Accepts `08098765432`, `+2348098765432`, `2348098765432`; normalised to `+234…`. Invalid ⇒ 422 |
| `credit_limit_kobo` | int? | `> 0` or `null` |
| `address` | str? | free text |

**Response 201:** the debtor object with `outstanding_kobo: 0`, `overdue_kobo: 0`, `score: {"value": null, "label": "No history yet", "category": "no_history"}`.

**409 `DEBTOR_EXISTS`** — required by PRD §8.2 A so the inline-create UI can select instead of fail:

```json
{
  "error": {
    "code": "DEBTOR_EXISTS",
    "message": "A debtor with this email already exists for your business.",
    "fields": { "email": "Already in use." },
    "existing_debtor": { "id": "…", "name": "Bright Foods Ltd", "email": "accounts@brightfoods.ng" }
  }
}
```

> **Deviation from the PRD error shape**, additive only: `existing_debtor` sits beside `code`/`message`/`fields` because `fields` is a field→reason map and stuffing an object into it would make clients parse two shapes. Same field name is used inside `POST /transactions`' 409 when an inline `new_debtor` email collides.

**Business logic:** normalise email/phone → `INSERT` → catch `UniqueViolation` on `uq_debtors_business_email` → re-read the existing debtor → raise `DEBTOR_EXISTS`.

**Tables:** `debtors` (insert; read on conflict).

**Errors:** 401, 409, 422.

### 6.4.3 `PATCH /debtors/:id`

**Request:** any subset of the create fields; `null` allowed for `credit_limit_kobo`, `contact_person`, `address`. `email`/`phone` may change (still validated and still unique per business).

**Response 200:** the updated debtor object (no `score` recomputation needed, but included if cheap — include it).

**Business logic:** load scoped `(id, business_id)` → 404 if absent → apply → `IntegrityError` on email ⇒ 409 `DEBTOR_EXISTS` → commit.

**Tables:** `debtors` (read, update).

**Errors:** 401, 404, 409, 422.

**Note:** there is deliberately **no `DELETE /debtors/:id`** — PRD §3 item 2 says "create, read, update (no delete)". Deleting a debtor with financial history would orphan debts; that is the reason, and it belongs in the ADR (ADR-8).

### 6.4.4 `GET /debtors/:id` (SHOULD — PRD item 12)

**Response 200**

```json
{
  "debtor": { "id": "…", "name": "Bright Foods Ltd", "contact_person": "Ada Obi",
              "email": "accounts@brightfoods.ng", "phone": "+2348098765432",
              "credit_limit_kobo": 80000000, "address": "…", "created_at": "…" },
  "totals": { "outstanding_kobo": 5000000, "overdue_kobo": 0,
              "total_extended_kobo": 190000000, "total_collected_kobo": 185000000,
              "open_disputes": 0, "open_promise": { "promised_date": "2026-11-20",
              "promised_amount_kobo": 10000000 } },
  "score": { "value": 82, "label": "Strong repayment record", "category": "strong",
             "facts": { "transactions_counted": 4, "paid_on_time": 3, "paid_late": 1,
                        "avg_days_late": 1, "promises_kept": 2, "promises_missed": 1,
                        "partial_payments": 0, "open_disputes": 0 },
             "note": "Based on verified payments and recorded promise outcomes." },
  "capacity": { "limit": 80000000, "outstanding": 5000000, "available": 75000000 },
  "transactions": { "data": [ /* TransactionSummary */ ], "meta": { … } },
  "payments": [ /* PaymentSummary across this debtor's transactions, newest first */ ]
}
```

**Query:** `page`, `limit` apply to `transactions` only (default 20). `payments` is capped at the 50 most recent — the profile is a summary page, not an export.

**Tables:** `debtors`, `credit_transactions`, `payments`, `debtor_responses`.

**Errors:** 401, 404.

## 6.5 Transactions (creditor)

### 6.5.1 `POST /transactions` — create (PRD §8.2)

The most important write in the product. One DB transaction creates the debtor (if new), the transaction, the reminder schedule and the creation event.

**Request**

```json
{ "debtor_id": "9c1f…",
  "new_debtor": { "name": "Bright Foods Ltd", "contact_person": "Ada Obi",
                  "email": "accounts@brightfoods.ng", "phone": "+2348098765432",
                  "credit_limit_kobo": null },
  "description": "50 bags of rice", "amount_kobo": 15000000,
  "issue_date": "2026-11-17", "due_date": "2026-11-27",
  "invoice_number": "INV-0042", "notes": "Delivered by Musa",
  "override": false, "override_reason": null }
```

| Field | Type | Rules |
| --- | --- | --- |
| `debtor_id` | uuid? | Exactly one of `debtor_id` / `new_debtor`. Must belong to the business (404 otherwise) |
| `new_debtor` | object? | Same validation as `POST /debtors`. Duplicate email ⇒ 409 `DEBTOR_EXISTS` **with `existing_debtor`** |
| `description` | str | Required, 1–200 after trim |
| `amount_kobo` | int | Required, `> 0`, `≤ 9_000_000_000_000` |
| `issue_date` | date | Required. Not in the future (WAT). `≥ today_wat − 365d` sanity bound |
| `due_date` | date | Required. `≥ issue_date`. No upper bound (long-dated invoices are legitimate) |
| `invoice_number` | str? | ≤50 |
| `notes` | str? | Internal, ≤2000 |
| `override` | bool | Default `false` |
| `override_reason` | str? | **Required and non-blank when `override=true`** (Pydantic model validator); must be `null`/absent otherwise |

**Response 201**

```json
{
  "transaction": { /* full detail object, same shape as §6.5.3 minus timeline */ },
  "pay_link": "https://app.credence.ng/pay/xJ8k…",
  "reminders": [ /* ReminderSummary ×N, ordered by scheduled_for */ ]
}
```

**Server logic (exactly PRD §8.2, in this order, one transaction):**

```
1. BEGIN
2. lock business row FOR UPDATE                     # serialises capacity per business
3. debtor: resolve existing (scoped) or create new  # flush to get debtor.id
4. re-run capacity check with amount_kobo           # never trust the frontend
     if requires_override and not (override and override_reason):
         raise CapacityExceeded  → 422 CAPACITY_EXCEEDED
5. reference = "CRD-" + str(nextval(credit_transaction_reference_seq)).zfill(6)
6. public_token = secrets.token_urlsafe(32)
7. INSERT credit_transactions(status='pending_ack',
       capacity_override=override, override_reason=override_reason,
       created_by_business_id=business.id)
8. INSERT reminders  ← build_schedule(issue_date, due_date, now_wat())   (§9.3)
9. INSERT transaction_events(type='transaction_created', actor='creditor', data={…})
10. COMMIT
11. send email #1 (new credit notice) for the new_credit reminder
12. UPDATE that reminder → sent|failed ; INSERT reminder_sent|reminder_failed event
13. return 201
```

```mermaid
flowchart TD
    A["POST /transactions<br/>(validated payload)"] --> B["BEGIN<br/>LOCK business row"]
    B --> C{"debtor_id or<br/>new_debtor?"}
    C -->|existing| D["load debtor<br/>scoped to business"]
    C -->|new| E["INSERT debtor<br/>(409 if email exists)"]
    D --> F["re-run capacity check<br/>(never trust the frontend)"]
    E --> F
    F --> G{"over limit?"}
    G -->|"yes, no override+reason"| H["ROLLBACK<br/>422 CAPACITY_EXCEEDED"]
    G -->|"within limit, or override+reason"| I["nextval → CRD-000123<br/>secrets.token_urlsafe(32)"]
    I --> J["INSERT credit_transactions<br/>status = pending_ack"]
    J --> K["INSERT reminders<br/>(past dates skipped)"]
    K --> L["INSERT transaction_created event"]
    L --> M["COMMIT"]
    M --> N["send email 1<br/>(new credit notice)"]
    N --> O["UPDATE reminder sent|failed<br/>+ reminder_sent|reminder_failed event"]
    O --> P["201 transaction + pay_link<br/>+ reminders[]"]
```

**Why the reference uses a sequence and not a count:** `MAX(id)+1` races under concurrency and produces duplicates on rollback; a sequence never reuses a value and gaps are acceptable on a reference (it is an identifier, not a count).

**Reminder rows created** for issue 17 Nov / due 27 Nov (all 9:00 WAT = 08:00Z):

| kind | scheduled_for | Note |
| --- | --- | --- |
| `new_credit` | now (sent synchronously in step 11) | Sends immediately, not at 9:00 |
| `upcoming` | 24 Nov 08:00Z | due − 3 |
| `due_today` | 27 Nov 08:00Z | due |
| `overdue_1` | 30 Nov 08:00Z | due + 3 |
| `overdue_followup` | 4 Dec 08:00Z | due + 7; the job chains the rest |

Dates already past at creation are **not** inserted (PRD §7.2). A transaction created 5 days overdue therefore starts at `overdue_1` (30 Nov is past → skipped) — precisely: `upcoming` and `due_today` are past ⇒ skipped, `overdue_1` past ⇒ skipped, `overdue_followup` = due+7 may also be past ⇒ skipped, so the schedule can legitimately be *empty* apart from `new_credit`. The creation response must handle `reminders: []` and the UI must say "no automatic reminders — this invoice is already overdue" (§9.3.2).

**Errors:** 401 · 404 (debtor not in business) · 409 `DEBTOR_EXISTS` · 422 `VALIDATION_ERROR` / `CAPACITY_EXCEEDED` / `INVALID_DATE_RANGE`.

**Tables:** `businesses` (lock+read), `debtors` (read/insert), `credit_transactions` (insert), `reminders` (insert/update), `transaction_events` (insert).

### 6.5.2 `GET /transactions`

| | |
| --- | --- |
| Auth | JWT |
| Query | `status` (stored status or `overdue`), `q`, `overdue` (bool), `page`, `limit`, `sort` (`created_at` default, `due_date`, `amount`) |

**Filter semantics**

- `status=<stored>` filters on the stored column.
- `status=overdue` and/or `overdue=true` ⇒ `due_date < today_wat AND status NOT IN (settled,cancelled,disputed)` **and** computed balance > 0.
- `q` matches `reference`, `invoice_number`, `description` (case-insensitive substring) and debtor `name` (join).
- Sorting is stable and always has `id` as a tiebreak so pagination cannot duplicate rows.

**Response 200:** `{"data": [TransactionSummary], "meta": {…}}`.

**Business logic:** build a filtered `SELECT` scoped by `business_id`; LEFT JOIN a paid-per-transaction aggregate; compute `display_status`, `days_overdue`, `has_open_promise`, `next_reminder` in the projection. Count query for `meta.total` uses the same predicates.

**Tables:** `credit_transactions`, `payments`, `debtors`, `reminders`, `debtor_responses`.

**Errors:** 401 · 422 (unknown enum value).

### 6.5.3 `GET /transactions/:id`

**Response 200**

```json
{
  "transaction": {
    "id": "…", "reference": "CRD-000123", "invoice_number": "INV-0042",
    "debtor": { "id": "…", "name": "Bright Foods Ltd", "email": "accounts@…",
                "phone": "+234…", "contact_person": "Ada Obi" },
    "description": "50 bags of rice", "amount_kobo": 15000000,
    "paid_kobo": 10000000, "outstanding_kobo": 5000000, "overpaid_kobo": 0,
    "issue_date": "2026-11-17", "due_date": "2026-11-27",
    "status": "partially_paid", "display_status": "partially_paid",
    "days_overdue": 0,
    "notes": "Delivered by Musa",
    "capacity_override": false, "override_reason": null,
    "acknowledged_at": "2026-11-17T09:14:10Z", "settled_at": null,
    "pay_link": "https://app.credence.ng/pay/xJ8k…",
    "created_at": "2026-11-17T09:12:03Z"
  },
  "money": { "amount_kobo": 15000000, "paid_kobo": 10000000,
             "outstanding_kobo": 5000000, "progress_pct": 67 },
  "timeline": [ /* TransactionEvent ×N newest first, each with rendered `text` */ ],
  "upcoming_reminders": [ /* ReminderSummary where status='scheduled', ASC */ ],
  "reminders": [ /* all, newest first — powers "did it send?" */ ],
  "payments": [ /* PaymentSummary, newest first */ ],
  "open_promise": { "id": "…", "promised_date": "2026-11-20",
                    "promised_amount_kobo": 10000000, "message": "Will pay after Thursday delivery",
                    "created_at": "…" },
  "open_dispute": null,
  "actions": { "can_remind": true, "can_cancel": true, "can_resolve_dispute": false,
               "remind_disabled_reason": null }
}
```

**`actions`** is **[REC]** additive and saves the frontend from re-implementing PRD rules ("manual button disabled when disputed/settled/cancelled", "Resolve dispute only when disputed"). The server owns the rule; the UI renders the button from it.

`progress_pct` = `min(100, round(paid × 100 / amount))` — integers only, computed from kobo.

**Tables:** `credit_transactions`, `debtors`, `payments`, `reminders`, `debtor_responses`, `transaction_events`.

**Errors:** 401 · 404.

### 6.5.4 `POST /transactions/:id/remind` — manual reminder

**Request:** empty body (or `{}`).

**Response 200**

```json
{ "reminder": { "id": "…", "kind": "manual", "status": "sent",
                "sent_at": "2026-11-19T14:03:11Z", "template": "overdue_1" },
  "event": { "id": "…", "type": "reminder_sent", "created_at": "…" } }
```

**Business logic**

1. Load scoped; 404 if absent.
2. Terminal/blocked states ⇒ `409 REMINDER_NOT_ALLOWED` with `fields.state`:
   `disputed`, `settled`, `cancelled`.
3. Cooldown: if a `manual` reminder for this transaction has `sent_at > now − 1h` ⇒ `429 REMINDER_TOO_SOON` with `retry_after_seconds`.
4. Choose template **from the state now** (§9.4): `pending_ack` → New credit; not yet due → Upcoming; due today → Due today; 1–6 days late → First overdue; ≥7 → Overdue follow-up.
5. Insert `reminders(kind='manual', scheduled_for=now)`; send synchronously; update status; insert event.
6. Return the outcome. A failed send returns **200** with `status:'failed'` and `error` — the operation itself succeeded, and PRD's design is that a send failure is recorded, not raised.

**Tables:** `credit_transactions`, `reminders`, `transaction_events`.

**Errors:** 401 · 404 · 409 `REMINDER_NOT_ALLOWED` · 429.

### 6.5.5 `POST /transactions/:id/notes`

**Request** `{ "note": "Called Ada; she says cheque cleared Friday." }` — 1..2000 chars, trimmed.

**Response 201**

```json
{ "event": { "id": "…", "type": "note_added", "actor": "creditor",
             "data": { "note": "Called Ada; she says cheque cleared Friday." },
             "text": "Called Ada; she says cheque cleared Friday.",
             "created_at": "2026-11-19T15:00:00Z" } }
```

**Business logic:** append-only event + update `credit_transactions.notes` to this note (latest-wins convenience column, per A-11). Cancelled/settled transactions still accept notes — an audit trail should be appendable at any time.

**Tables:** `transaction_events` (insert), `credit_transactions` (update `notes`).

**Errors:** 401 · 404 · 422.

### 6.5.6 `POST /transactions/:id/resolve-dispute`

**Request** `{ "note": "Confirmed with debtor: goods were received; invoice accepted." }` — 1..2000, required.

**Response 200:** the full detail object (§6.5.3).

**Business logic (PRD §5, §7.2)**

```
1. lock transaction row FOR UPDATE
2. if no open dispute (type='dispute' AND resolved_at IS NULL) → 409 DISPUTE_NOT_OPEN
3. recompute balance NOW
4. new_status = settled   if balance == 0
              = partially_paid if paid > 0
              = active    otherwise
5. set dispute.resolved_at = now(), resolution_note = note
6. set transaction.status = new_status
7. INSERT dispute_resolved event (actor creditor, data{note, new_status})
8. rebuild_schedule(transaction, from=today_wat())         # §9.3.3
9. COMMIT
```

> **Edge case the PRD implies but does not state:** resolving a dispute on a transaction whose balance is 0 (paid while disputed) makes it `settled` and must also **cancel** the newly rebuilt reminders. The rebuild function is called with the post-resolve status, and it returns an empty schedule for a settled/cancelled transaction — so this falls out for free. It must be tested (§12.14).

**Tables:** `credit_transactions` (lock, update), `debtor_responses` (update), `reminders` (cancel + insert), `transaction_events` (insert), `payments` (read).

**Errors:** 401 · 404 · 409 `DISPUTE_NOT_OPEN` · 422.

### 6.5.7 `POST /transactions/:id/cancel`

**Request:** optional `{ "reason": "Invoice raised in error" }` (≤500). Not required by the PRD; accepted and stored in the event `data` if present.

**Response 200:** the detail object with `status='cancelled'`, `display_status='cancelled'`.

**Business logic:** lock row → if already `cancelled` return 200 idempotently (no second event); if `settled` ⇒ `409 TXN_CANCELLED` is wrong here, use `409 REMINDER_NOT_ALLOWED`-style code `TXN_NOT_CANCELLABLE` **[REC]** — you cannot cancel a debt that has been paid in full. Otherwise set `status='cancelled'`, cancel all `scheduled` reminders with `skip_reason='cancelled'`, insert `cancelled` event.

**A cancelled transaction with successful payments:** allowed (partial payment then goods returned). The balance is still computed; `display_status` precedence shows `cancelled`. Money is never returned automatically — refunds are out of scope, so the event records the state for a human.

**Tables:** `credit_transactions`, `reminders`, `transaction_events`.

**Errors:** 401 · 404 · 409 `TXN_NOT_CANCELLABLE`.

## 6.6 Receipts

### 6.6.1 `GET /transactions/:id/payments/:pid/receipt`

| | |
| --- | --- |
| Auth | JWT (creditor variant) |
| Query | `format` = `html` (default) \| `pdf` |
| Response | `text/html` (inline) or `application/pdf` (attachment `RCT-000045.pdf`) |

**Rules:** `pid` must belong to `:id`, and `:id` must belong to the business — otherwise `404 PAYMENT_NOT_FOUND` (never 403; see §11.2). Only `status='successful'` payments have a receipt; anything else ⇒ `404`.

**What the balance on the receipt means (D-5).** "Total paid to date" and "balance remaining" are computed **when the receipt is rendered**, so they describe the transaction's balance *at the moment of viewing*, not the balance immediately after this payment. The receipt says so in one fixed line of copy (§8.10.2) rather than implying a historical snapshot. There is no `receipts` snapshot table in the MVP (ADR-12).

When `payments.provider_mode = 'sandbox'` the receipt carries a `SANDBOX` marker in the header (§8.10.2), so a demo receipt can never be mistaken for a real one.

`format=pdf` when `RECEIPT_PDF_ENABLED=false` ⇒ `400 UNSUPPORTED_FORMAT` with `fields.format = "PDF receipts are disabled."` (the SHOULD feature must degrade predictably, not 500).

**Public variant** `GET /public/tx/:token/receipts/:receipt_number` — §6.7.7.

Full receipt design (§8.10): layout, SETTLED stamp, what is calculated at render time, and why the balance shown on a receipt may differ from today's balance.

## 6.7 Public debtor endpoints (PRD §8.3)

### 6.7.0 How public access works

- The token is the whole credential: `secrets.token_urlsafe(32)` (43 chars, 256 bits) generated with a CSPRNG and stored plaintext in `credit_transactions.public_token` (ADR-7 explains why plaintext is required by the PRD's "Copy pay link" feature). The complete safeguard set is in §11.4 — in short: HTTPS only, never logged, `no-store`, `no-referrer`, one transaction per token, rotation/revocation deferred and documented.
- **HTTPS is mandatory.** `APP_URL` must be an `https` origin outside local development (§13.3 refuses to boot otherwise), because a bearer token in a URL over plain HTTP is a credential in clear text on every hop and in every proxy log.
- Dependency `PublicTransaction`: `token → SELECT credit_transaction WHERE public_token = :token`. Miss ⇒ `404 TXN_NOT_FOUND`, indistinguishable from a wrong token — no timing or wording oracle.
- Every route here is rate-limited (§11.5), sets `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `X-Robots-Tag: noindex`.
- No creditor-only field is ever serialised: `notes`, `override_reason`, `created_by_business_id`, `capacity_override`, `raw_webhook`, or anything belonging to another debtor.

### 6.7.1 `GET /public/tx/:token`

**Response 200**

```json
{
  "creditor": { "name": "Adeyemi Wholesale Ltd", "logo_url": null,
                "initials": "AW", "email": "ops@adeyemi.ng" },
  "transaction": {
    "reference": "CRD-000123", "invoice_number": "INV-0042",
    "description": "50 bags of rice", "amount_kobo": 15000000,
    "paid_kobo": 10000000, "outstanding_kobo": 5000000,
    "issue_date": "2026-11-17", "due_date": "2026-11-27",
    "status": "partially_paid", "display_status": "partially_paid",
    "days_overdue": 0,
    "actions": { "can_pay": true, "can_promise": true, "can_dispute": true,
                 "read_only_message": null }
  },
  "open_promise": { "promised_date": "2026-11-20", "promised_amount_kobo": 10000000 },
  "open_dispute": null,
  "payments": [ { "amount_kobo": 10000000, "paid_at": "2026-11-20T11:02:44Z",
                  "receipt_number": "RCT-000045",
                  "receipt_url": "/public/tx/xJ8k…/receipts/RCT-000045" } ],
  "payment_config": { "min_amount_kobo": 10000, "currency": "NGN",
                      "provider_mode": "sandbox" }
}
```

`initials` is computed server-side ("AW" from "Adeyemi Wholesale Ltd") so the PRD's logo fallback cannot be implemented three different ways. `payment_config.min_amount_kobo` avoids hardcoding ₦100 in the frontend. `payment_config.provider_mode` (D-10) lets the public page show a "Test payment — no real money" banner when the deployment is using Kora's sandbox. It is derived from server config, never from the request.

**Terminal transactions** (`settled`, `cancelled`) return the same shape with all `actions` false, `read_only_message` set ("This invoice is settled. Thank you." / "This invoice was cancelled."), and payments still listed with receipt links (PRD §8.3).

**Errors:** 404 only (plus 429). Never 401/403 — the token is either valid or the transaction does not exist for this caller.

### 6.7.2 `POST /public/tx/:token/acknowledge`

**Request:** empty. Called by the page's JavaScript **after load**, never by the server rendering the GET (PRD §13: link scanners).

**Response 200**

```json
{ "status": "active", "display_status": "active", "acknowledged_at": "2026-11-17T09:14:10Z" }
```

**Business logic (idempotent by construction)**

```
lock transaction row FOR UPDATE
if status == 'pending_ack':
    status = 'active'; acknowledged_at = now()
    INSERT event debtor_acknowledged (actor debtor)
elif status in ('settled','cancelled'):
    return current state                    # never re-acknowledge a terminal document
else:
    if acknowledged_at IS NULL: acknowledged_at = now()   # e.g. disputed without ack
return current state
```

Calling it twice, or on a `partially_paid` transaction, produces exactly one event and no error. That is the PRD's "Idempotent" requirement made concrete.

**Tables:** `credit_transactions` (lock, maybe update), `transaction_events` (insert at most once).

**Errors:** 404 · 429.

### 6.7.3 `POST /public/tx/:token/pay`

**Request**

```json
{ "amount_kobo": 10000000 }
```

Optional header `Idempotency-Key: <uuid>` — **[REC]**, strongly advised: a double-tap on a phone must not create two Kora charges.

| Field | Type | Rules |
| --- | --- | --- |
| `amount_kobo` | int | Required. `> 0`. `≥ 10 000` unless `balance < 10 000`, in which case it must equal `balance`. `≤ balance` (the UI cannot overpay; overpayment can still arise from two simultaneous successful charges — §8.9) |

**Response 201**

```json
{ "checkout_url": "https://checkout.korapay.com/…", "reference": "CRD-000123-P1",
  "amount_kobo": 10000000, "payment_id": "…" }
```

**Business logic**

```
1. load tx by token (404)
2. lock tx row FOR UPDATE
3. if status in ('settled','cancelled')        → 409 TXN_NOT_PAYABLE
4. balance = amount - sum(successful), clamped at 0
   if balance == 0                             → 409 TXN_NOT_PAYABLE
5. validate amount against balance and min
6. if Idempotency-Key present:
     existing = payment with (transaction_id, idempotency_key)      # uq_pay_idempotency
     if existing and existing.amount_kobo != amount_kobo:
         -> 409 IDEMPOTENCY_KEY_REUSED          # same key, different intent
     if existing.status in (initiated, pending):
         return 200 with existing.checkout_url + reference   # replay: no second Kora call
     if existing.status == 'successful':
         return 200 with the stored result      # already paid; never charge again
     if existing.status == 'failed':
         -> 409 IDEMPOTENCY_KEY_REUSED          # a new attempt needs a new key
7. attempt = max(attempt_number)+1  (under the row lock)
   kora_reference = f"{tx.reference}-P{attempt}"
8. INSERT payments(status='initiated', amount_kobo, attempt_number, kora_reference)
   COMMIT                                          # the row exists before Kora is called
9. KoraClient.initialize(amount_naira, currency='NGN', reference=kora_reference,
                         customer{name,email}, redirect_url, notification_url, metadata)
10. success: UPDATE payments → 'pending', checkout_url; commit; return 201
    failure: UPDATE payments → 'failed', failure_reason; commit;
             INSERT payment_failed event; return 502 PAYMENT_INIT_FAILED
```

**Why the `initiated` row is committed before calling Kora:** if Kora succeeds but our process dies before persisting the response, the webhook can still find the payment by reference. An in-memory-only attempt would strand a real charge with no local record — the worst possible outcome in this system.

**Idempotency contract (D-4).** `Idempotency-Key` is optional, but the shipped frontend always sends one. Its semantics are spelled out because ambiguity here costs money:

| Case | Response | Effect |
| --- | --- | --- |
| New key | `201` | one new `payments` attempt, one Kora initialize |
| Same key, same amount, attempt still open | `200` | the **same** `checkout_url` and reference; **no** second Kora call |
| Same key, same amount, attempt already `successful` | `200` | the stored result; no new charge |
| Same key, **different** amount | `409 IDEMPOTENCY_KEY_REUSED` | nothing created; caller retries with a fresh key |
| Same key, attempt `failed` | `409 IDEMPOTENCY_KEY_REUSED` | nothing created; a retry is a *new* attempt and needs a new key |
| No key | `201` | attempt numbering still allocates safely (`-P1`, `-P2`), so two clicks are two legitimate charges — which is exactly why the key exists |

Uniqueness is `UNIQUE (transaction_id, idempotency_key) WHERE idempotency_key IS NOT NULL`, so the race between two identical clicks is resolved by the database, not by a read-then-write check.

**`redirect_url`** = `{APP_URL}/pay/{token}/result?ref={kora_reference}` — built from config, never from the request `Host` (open-redirect protection, §11.7).
**`notification_url`** = `{APP_URL}/webhooks/kora` — or omitted, relying on the dashboard-configured webhook URL. **[VERIFY]** Kora documents both a dashboard-level webhook URL and a per-charge `notification_url`; confirm in sandbox which wins and pin it (R-3).

**Errors:** 404 `TXN_NOT_FOUND` · 409 `TXN_NOT_PAYABLE` · 422 `AMOUNT_OUT_OF_RANGE`/`VALIDATION_ERROR` · 429 · 502 `PAYMENT_INIT_FAILED`.

**Tables:** `credit_transactions` (lock, read), `payments` (insert/update), `transaction_events` (insert on failure).

### 6.7.4 `GET /public/tx/:token/payments/:ref`

The result page polls this every 3 s for ≤30 s (PRD §8.4 step 5).

**Response 200**

```json
{ "reference": "CRD-000123-P1", "amount_kobo": 10000000,
  "status": "successful", "paid_at": "2026-11-20T11:02:44Z",
  "provider_mode": "sandbox",
  "receipt_number": "RCT-000045",
  "receipt_url": "/public/tx/xJ8k…/receipts/RCT-000045",
  "transaction": { "outstanding_kobo": 5000000, "display_status": "partially_paid" } }
```

`provider_mode` lets the result page keep its "test payment" banner after the redirect. The route never reports `overpaid_kobo` or `review_reason`: an overpayment is an ops concern for the creditor, not something to explain to a debtor mid-checkout.

`status` ∈ `initiated|pending|successful|failed`. Never exposes `raw_webhook` or Kora's raw response; a failed payment returns a coarse `failure_message` only.

**Scoping:** `ref` must belong to the transaction identified by the token, else `404 PAYMENT_NOT_FOUND`. This is what stops a token holder probing other debtors' references.

**Polling cost:** 10 requests per paying debtor in 30 s; §11.5 gives this route a 60/min per-token allowance specifically for that.

**Errors:** 404 · 429.

### 6.7.5 `POST /public/tx/:token/promise`

**Request**

```json
{ "promised_date": "2026-11-20", "promised_amount_kobo": 10000000,
  "message": "Will pay after our Thursday delivery" }
```

| Field | Type | Rules |
| --- | --- | --- |
| `promised_date` | date | Required. `today_wat ≤ date ≤ today_wat + 60d` (PRD §8.3). Outside ⇒ `422 PROMISE_WINDOW_INVALID` |
| `promised_amount_kobo` | int? | `> 0`. Omitted/`null` ⇒ "the full balance at promise time" (PRD §7.3). `> balance` ⇒ `422 AMOUNT_OUT_OF_RANGE` |
| `message` | str? | ≤1000 |

**Response 201**

```json
{ "promise": { "id": "…", "promised_date": "2026-11-20",
               "promised_amount_kobo": 10000000,
               "message": "Will pay after our Thursday delivery",
               "status": "open", "created_at": "…" },
  "transaction": { "status": "active", "display_status": "active" },
  "next_reminder": { "kind": "overdue_1", "scheduled_for": "2026-11-28T08:00:00Z" } }
```

**Business logic**

```
lock tx row FOR UPDATE
if status in ('settled','cancelled')          → 409
validate window/amount against the current balance
supersede any open promise                    # §5.4.3
INSERT promise (status='open', amount as sent or NULL)
if status == 'pending_ack': status = 'active'; acknowledged_at = now()
INSERT promise_made event (actor debtor, data{promised_date, amount, message})
shift the next scheduled reminder to 9:00 WAT the day after promised_date   # §9.5
COMMIT
email #8 to the creditor ("{debtor} promised to pay ₦X by {date}")
```

`next_reminder` is **[REC]** additive: the PRD says promises delay reminders, so telling the debtor *when* the next nudge comes builds trust and prevents "I promised and you still emailed me".

**Idempotency:** a byte-identical retry within 5 minutes returns the existing open promise with `200` rather than creating a second one. A *different* promise legitimately supersedes (§7.3).

**Errors:** 404 · 409 `TXN_SETTLED`/`TXN_CANCELLED` · 422 · 429.

**Tables:** `credit_transactions` (lock/update), `debtor_responses` (supersede + insert), `reminders` (update), `transaction_events` (insert).

### 6.7.6 `POST /public/tx/:token/dispute`

**Request**

```json
{ "reason": "goods_not_received", "message": "Only 30 of the 50 bags arrived." }
```

| Field | Type | Rules |
| --- | --- | --- |
| `reason` | enum | `wrong_amount` \| `goods_not_received` \| `already_paid` \| `other` |
| `message` | str | Required, 1–2000 |

**Response 201**

```json
{ "dispute": { "id": "…", "reason": "goods_not_received",
               "message": "Only 30 of the 50 bags arrived.", "created_at": "…" },
  "transaction": { "status": "disputed", "display_status": "disputed" },
  "reminders_cancelled": 3 }
```

**Business logic**

```
lock tx row FOR UPDATE
if status in ('settled','cancelled')     → 409
if an unresolved dispute exists          → 409 DISPUTE_ALREADY_OPEN
                                           (identical reason+message ⇒ 200 with existing)
INSERT dispute (dispute_reason, message)
status = 'disputed'; acknowledged_at = now() if null
UPDATE reminders SET status='cancelled', skip_reason='disputed'
   WHERE transaction_id = :id AND status = 'scheduled'
INSERT dispute_raised event (actor debtor, data{reason, message, reminders_cancelled})
COMMIT
email #8 to creditor ("{debtor} raised a dispute: goods not received")
```

`reminders_cancelled` is returned because the PRD promises the debtor "we'll pause reminders"; a visible count is testable and demonstrable on stage.

**Errors:** 404 · 409 · 422 · 429.

**Tables:** `credit_transactions`, `debtor_responses` (insert), `reminders` (update), `transaction_events` (insert).

### 6.7.7 `GET /public/tx/:token/receipts/:receipt_number`

| | |
| --- | --- |
| Query | `format=html` (default) \| `pdf` |
| Rule | The receipt must belong to **this** transaction (found via the token), else `404`. This is the link in every email, so it must work with no login and no session |

**Response:** `text/html` or `application/pdf`, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`.

**Errors:** 404 `PAYMENT_NOT_FOUND` · 400 `UNSUPPORTED_FORMAT` · 429.

## 6.8 Webhooks

### 6.8.1 `POST /webhooks/kora`

| | |
| --- | --- |
| Auth | HMAC-SHA256 in `x-korapay-signature`, **not** JWT |
| Body | Kora's `{ "event": "...", "data": { ... } }` |
| Rate limit | none (provider traffic; protected by signature + idempotency instead) |

**Processing (the order is the security property)**

```
1. raw = await request.body()                       # bytes, untrusted
2. signature_ok = verify(raw, header['x-korapay-signature'], settings.kora_secret_key)
3. if not signature_ok:
     record kora_webhook_events(signature_ok=false, outcome='rejected')
     return 401 WEBHOOK_SIGNATURE_INVALID
4. payload = json.loads(raw); event = payload['event']; data = payload['data']
   reference = data.get('reference')                # missing ⇒ 400, record 'ignored'
5. INSERT kora_webhook_events(reference, event, payload, signature_ok=true)
       ON CONFLICT (kora_reference, event) DO NOTHING
   if rowcount == 0: return 200 {}                  # duplicate delivery — done
6. payment = SELECT payments WHERE kora_reference = reference
   if payment is None:
       outcome='unknown_reference'; return 200 {}      # D-8: recorded, nothing created
7. if payment.status == 'successful': outcome='duplicate'; return 200 {}
8. if event not in ('charge.success','charge.failed'): outcome='ignored'; return 200 {}
9. PaymentService.handle_webhook(reference, event, data, raw)    # verify + apply, ≤ ~3 s
10. outcome='applied'; return 200 {}
    (500 only if the DB itself failed and a retry is genuinely useful)
```

**Why 200 for `ignored`/unknown reference (D-8, decided):** Kora retries any non-200 for up to 72 hours (its docs are explicit), so a 4xx would turn one unrecognised reference into three days of pointless retries. The event is recorded with `outcome='unknown_reference'`, **no `payments` row is created, no transaction balance or status is touched**, and the response is `200`. That row is the triage artefact: if the reference later turns out to be a real charge we lost, it is visible and reconcilable (§8.12) instead of invisible.

| Outcome | Payment created? | Money touched? | HTTP |
| --- | --- | --- | --- |
| `unknown_reference` | no | no | `200` |
| `duplicate` | no (already exists) | no | `200` |
| `ignored` (unhandled event type, missing `data.reference`) | no | no | `200`, or `400` if the body is unparseable |
| `rejected` (bad signature) | no | no | `401` |
| `error:*` (DB failure) | — | — | `500`, so Kora retries |

**Why return 500 at all:** if the database is unavailable we *do* want Kora to retry. Validation failures and unknown references are not retryable.

Full lifecycle, idempotency and amount comparison: §8.6–§8.9.

**Errors:** 400 (unparseable) · 401 (bad signature) · 500 (transient DB failure only).

---

# 7. Service Layer Design

## 7.1 Placement rules

- A route validates input, resolves dependencies, calls **one** service method (occasionally two for read composition), and maps the result to a response schema. No route exceeds ~25 lines.
- A service method:
  - takes explicit arguments (`business: Business`, ids, a validated Pydantic payload) — never a `Request`;
  - owns its transaction boundary (`commit()` / `rollback()`);
  - emits `transaction_events` for every state change worth showing;
  - raises `AppError` subclasses (`NotFoundError`, `ConflictError`, `ValidationError`), all mapped by one handler.
- Services call other services **only downward**, never in a cycle:

```
CreditTransactionService → { CapacityService, DebtorService, ReminderService, EventService, EmailService }
PaymentService           → { TransactionService(status recompute), PromiseService,
                             ReminderService, ReceiptService, EventService, EmailService }
PromiseService           → { EventService, ReminderService }
ReminderService          → { EmailService, EventService }
ScoringService           → { queries only }
```

`PromiseService` must not call `PaymentService`, and `ReminderService` must not call `PaymentService` — both need only the *balance*, which lives in `balance.py` as pure functions. That is precisely why balance is a function module rather than a service method: it breaks otherwise-unavoidable cycles.

## 7.2 Service catalogue

### 7.2.1 `BusinessService` (`modules/businesses/service.py`)

| Operation | Contract |
| --- | --- |
| `get_profile(business)` | Pure projection |
| `set_credit_limit(business, credit_limit_kobo)` | Validates `> 0` or `None`; commits; returns profile |

Tables: `businesses`. Deliberately **not** responsible for capacity, even though it owns the limit: that keeps the hot aggregate out of a settings service.

### 7.2.2 `DebtorService`

| Operation | Contract |
| --- | --- |
| `list(business_id, q, page, limit)` | Page of debtors + outstanding/overdue/open-promise/open-dispute + score summary |
| `create(business_id, payload)` | Normalises email/phone, inserts, maps unique violation → `DebtorExists(existing)` |
| `update(business_id, debtor_id, payload)` | Patch semantics, same conflict mapping |
| `get_profile(business_id, debtor_id, page, limit)` | §6.4.4 assembly |
| `resolve_or_create(business_id, debtor_id \| new_debtor, session)` | **Used inside transaction creation**: does *not* commit; flushes; raises `DebtorExists` |
| `get_scoped(business_id, debtor_id)` | The only way to load a debtor for mutation; raises `NotFound` |

Dependencies: `ScoringService` (read), `balance.py`. Tables: `debtors`, `credit_transactions`, `payments`, `debtor_responses`.

### 7.2.3 `CreditCapacityService`

| Operation | Contract |
| --- | --- |
| `check(business_id, amount_kobo, debtor_id?, debtor_limit_kobo?)` | Read-only, no locks. Returns both blocks, `after_this`, `requires_override`, `over_by_kobo` |
| `assert_within_limit(...)` | **Inside a caller's transaction**, after the business row is locked. Raises `CapacityExceeded` unless override + reason |

Dependencies: aggregate functions in `queries.py`. No writes, no commits.
Tables: `businesses`, `credit_transactions`, `payments`, `debtors`.

The **same** `business_outstanding()` function serves `check`, the dashboard and the profile — one definition, three call sites. This is the single most important deduplication in the design.

### 7.2.4 `CreditTransactionService`

| Operation | Contract |
| --- | --- |
| `create(business, payload)` | §6.5.1 flow. Owns the boundary, sequence, token, schedule, event, post-commit email |
| `list(business_id, filters, page, limit)` | Filtered, computed projection |
| `get_detail(business_id, tx_id)` | §6.5.3 assembly + `actions` |
| `get_scoped(business_id, tx_id, for_update=False)` | Loader used everywhere; 404 on cross-business access |
| `add_note(business_id, tx_id, note)` | Event + convenience column |
| `cancel(business_id, tx_id, reason?)` | Lock, guard, status, cancel reminders, event |
| `resolve_dispute(business_id, tx_id, note)` | Lock, recompute, status, event, rebuild schedule |
| `apply_balance_status(tx, balance)` | **Internal**, called by `PaymentService` inside *its* transaction: `partially_paid` / `settled` (sets `settled_at`), or leaves `disputed` alone unless balance is 0 |

Dependencies: `CapacityService`, `DebtorService`, `ReminderService`, `EventService`, `EmailService`, `balance.py`.
Tables: `credit_transactions`, `debtors`, `reminders`, `transaction_events`, `payments` (read).

### 7.2.5 `PaymentService` (state machine in §8)

| Operation | Contract |
| --- | --- |
| `initialize(token, amount_kobo, idempotency_key?)` | §6.7.3. Creates the attempt, calls Kora, returns the checkout URL |
| `handle_webhook(reference, event, data, raw)` | Verify + apply. The only internet-reachable entry point into money state |
| `apply_verified_charge(payment_id, verified_amount_kobo, paid_at, raw)` | The single writer of `successful`, of `review_reason`, and of the payment-driven status change (§8.6). Idempotent by construction; credits the **gross** amount |
| `mark_failed(payment, reason)` | `failed` + `payment_failed` event |
| `status_for_public(token, reference)` | §6.7.4 projection |
| `flag_for_review(payment, reason)` | Internal: sets `payments.review_reason` inside the applying transaction. Called only by `apply_verified_charge`; never a route |

Dependencies: `KoraClient`, `CreditTransactionService`, `PromiseService`, `ReminderService`, `ReceiptService`, `EventService`, `EmailService`.
Tables: `payments`, `credit_transactions`, `debtor_responses`, `reminders`, `transaction_events`, `kora_webhook_events`.

### 7.2.6 `KoraService` / `KoraClient` (`integrations/kora/client.py`)

An adapter, not a domain service.

| Operation | Contract |
| --- | --- |
| `initialize_charge(...)` | POST `/charges/initialize` → `KoraCharge{reference, checkout_url, status, raw}`; raises `KoraError(code, retryable)` |
| `verify_charge(reference)` | GET `/charges/{reference}` → `KoraVerification{status, amount_kobo, currency, paid_at, raw}` — **parses naira decimal → kobo** (§8.4) |
| `verify_signature(raw_body, header)` | Pure function in `signature.py` |

It **never** decides whether a payment counts; it only reports what Kora said. Timeout 10 s, one retry on connection errors, no retry on 4xx.

### 7.2.7 `ReminderService`

| Operation | Contract |
| --- | --- |
| `build_schedule(issue_date, due_date, now)` | **Pure**: the default rows for a new transaction, skipping past dates (§9.3.1) |
| `create_for_transaction(tx, session)` | Inserts `build_schedule` output; no commit |
| `rebuild_for_transaction(tx, from_date, session)` | Cancel all `scheduled`, then re-insert anchored at "now" (§9.3.3) |
| `cancel_pending(tx_id, reason, session)` | Bulk cancel with `skip_reason` |
| `send_now(tx)` | §6.5.4 path |
| `deliver(reminder)` | Template selection + email + status + event (§9.5) |
| `next_scheduled(tx_id)` | For `next_reminder` in summaries |

Dependencies: `EmailService`, `EventService`, `balance.py`, `templates.py`.
Tables: `reminders`, `transaction_events`, `credit_transactions` (read).

### 7.2.8 `PromiseService`

| Operation | Contract |
| --- | --- |
| `make(tx, promised_date, promised_amount_kobo?, message?)` | Supersede + insert + status/ack + event + schedule shift (§6.7.5) |
| `open_for(tx_id)` | The single open promise or `None` |
| `evaluate(promise, payments, today)` | **Pure**: `kept` / `missed` / `still_open` (§8.13) |
| `check_after_payment(tx, promise)` | Inside the payment transaction; marks kept when the window is satisfied |
| `run_daily_check(today)` | §9.9 |

Dependencies: `EventService`, `ReminderService`, `balance.py`.
Tables: `debtor_responses`, `transaction_events`, `reminders`.

### 7.2.9 `RepaymentScoreService` (`modules/scoring/`)

| Operation | Contract |
| --- | --- |
| `for_debtor(business_id, debtor_id, with_facts=True)` | Full `ScoreBlock` |
| `for_debtors(business_id, debtor_ids)` | Batched summary for lists |
| `compute(facts)` | **Pure**: facts → value/label/category. The only place the formula lives (§10.4) |

Read-only; no commits, no events.

### 7.2.10 `ReceiptService`

| Operation | Contract |
| --- | --- |
| `render_html(payment, transaction, debtor, business)` | Jinja2 → HTML. Balance computed at render time |
| `render_pdf(html)` | WeasyPrint; raises `UnsupportedFormat` when disabled |
| `assign_number(session)` | `RCT-` + padded sequence; called only from `apply_verified_charge` |

Tables: none (read-only projections).

### 7.2.11 `EmailService` (`integrations/email/`)

| Operation | Contract |
| --- | --- |
| `send(template_key, to, context, cc=None)` | Renders + posts to Resend → `EmailResult{provider_message_id}` or raises `EmailError(retryable, message)` |
| `send_creditor_notice(tx, response_summary)` | Email #8 |

**Never** raises into a route after a commit — the caller records the failure (§3.4). All 8 templates live in one file (PRD §8.6).

### 7.2.12 `TransactionEventService` (`modules/transactions/events.py`)

| Operation | Contract |
| --- | --- |
| `record(session, tx_id, type, actor, data)` | Inserts; **does not commit** (joins the caller's transaction) |
| `render_text(type, data)` | **Pure**: `data` → the PRD §8.7 sentence, one implementation |
| `timeline(tx_id)` | Newest-first list with `text` |

This is why the dashboard activity feed and the details timeline cannot disagree: both render through `render_text`.

### 7.2.13 `DashboardService`

| Operation | Contract |
| --- | --- |
| `summary(business_id, today)` | §6.3.4: composes the aggregates + `render_text` |

Read-only, six queries, no N+1.

## 7.3 Event payloads and rendered text (the single rendering rule)

Every event's `data` carries both machine fields and the exact string the UI shows. Rendering is server-side because the PRD fixes the wording per event type (PRD §8.7) and naira formatting must be identical everywhere.

| `type` | `actor` | `data` keys | Rendered `text` |
| --- | --- | --- | --- |
| `transaction_created` | creditor | `amount_kobo`, `due_date`, `debtor_name`, `reference` | `Credit of ₦150,000.00 recorded · due 27 Nov 2026` |
| `reminder_sent` | system | `kind`, `template`, `to`, `provider_message_id` | `"Due today" reminder emailed to accounts@brightfoods.ng` |
| `reminder_failed` | system | `kind`, `to`, `error` | `Reminder to accounts@… failed` |
| `debtor_acknowledged` | debtor | `acknowledged_at` | `Bright Foods Ltd viewed and acknowledged the invoice` |
| `promise_made` | debtor | `promised_date`, `promised_amount_kobo`, `message` | `Promised to pay ₦100,000.00 by Fri 20 Nov: "Will pay after our Thursday delivery"` |
| `promise_kept` | system | `promised_date`, `promised_amount_kobo`, `paid_kobo` | `Promise for 20 Nov kept ✓` |
| `promise_missed` | system | `promised_date`, `promised_amount_kobo`, `paid_kobo` | `Promise for 20 Nov missed ✗` |
| `payment_received` | debtor | `amount_kobo`, `receipt_number`, `balance_kobo`, `kora_reference`, `provider_mode`, `overpaid_kobo?`, `review_reason?` | `Paid ₦100,000.00 via Kora · receipt RCT-000045 · balance ₦50,000.00` (a flagged payment appends `· overpayment under review`) |
| `payment_failed` | debtor | `amount_kobo`, `reason` | `A payment attempt of ₦100,000.00 failed` |
| `dispute_raised` | debtor | `reason`, `message` | `Dispute: "Goods not received"` |
| `dispute_resolved` | creditor | `note`, `new_status` | `Resolved by creditor: <note>` |
| `note_added` | creditor | `note` | the note text |
| `settled` | system | `amount_kobo`, `paid_kobo` | `Fully settled · reminders stopped` |
| `cancelled` | creditor | `reason?` | `Cancelled · reminders stopped` |

`render_text` is a pure function with a `match` on `type` and a total fallback, unit-tested per row (§12.3). Dates in text are rendered WAT (`27 Nov 2026`), never raw ISO.

## 7.4 Service ↔ table matrix

| Service | Writes | Reads |
| --- | --- | --- |
| Business | `businesses` | `businesses` |
| Debtor | `debtors` | `debtors`, `credit_transactions`, `payments`, `debtor_responses` |
| Capacity | — | `businesses`, `credit_transactions`, `payments`, `debtors` |
| Transaction | `credit_transactions`, `reminders`, `transaction_events` | + `debtors`, `payments`, `debtor_responses` |
| Payment | `payments`, `credit_transactions`, `reminders`, `debtor_responses`, `transaction_events`, `kora_webhook_events` | same |
| Promise | `debtor_responses`, `transaction_events` | `payments`, `credit_transactions` |
| Reminder | `reminders`, `transaction_events` | `credit_transactions`, `debtor_responses`, `payments` |
| Scoring | — | `credit_transactions`, `payments`, `debtor_responses` |
| Receipt | — | all (read) |
| Event | `transaction_events` | `transaction_events` |
| Dashboard | — | everything (read) |

No service writes a table it does not own, with two deliberate exceptions: `PaymentService` writes `credit_transactions.status` and `debtor_responses.promise_status`, because applying one payment must be atomic with both. Both are documented in §3.7.

## 7.5 Error taxonomy (`app/core/errors.py`)

```python
class AppError(Exception):
    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    def __init__(self, message: str, *, fields: dict | None = None, extra: dict | None = None): ...

class ValidationFailed(AppError):    code="VALIDATION_ERROR";  http_status=422
class NotFound(AppError):            code="NOT_FOUND";         http_status=404
class Conflict(AppError):            code="CONFLICT";          http_status=409
class Unauthorized(AppError):        code="UNAUTHORIZED";      http_status=401
class CapacityExceeded(AppError):    code="CAPACITY_EXCEEDED"; http_status=422
class DebtorExists(Conflict):        code="DEBTOR_EXISTS"
class TransactionNotPayable(Conflict): code="TXN_NOT_PAYABLE"
class PaymentInitFailed(AppError):   code="PAYMENT_INIT_FAILED"; http_status=502
...one class per code in §6.1.4
```

Services raise these; they never import `HTTPException`. One handler in `main.py` serialises them into the §6.1.2 envelope. This is what lets the worker reuse the same services without an HTTP server.

---

# 8. Payment Integration

## 8.1 The Kora contract, as confirmed from its current documentation

Everything below is taken from Kora's published documentation (cited), not assumed. Where the PRD guessed, the guess is marked and corrected.

| Item | Confirmed value | Source |
| --- | --- | --- |
| Base URL | `https://api.korapay.com/merchant/api/v1` | docs.korapay.com ("Base URL — api.korapay.com/merchant") |
| Auth | `Authorization: Bearer sk_live_…` / `sk_test_…` (secret key for pay-ins) | docs.korapay.com |
| Initialize | `POST /charges/initialize` | Kora Developer FAQ; kora technical walkthrough |
| Initialize body | `amount`, `currency`, `reference`, `narration`/`description`, `customer{name,email}`, `redirect_url`, `notification_url`, `channels[]`, `metadata`, `checkout{text,logo}` | Kora walkthrough sample; docs |
| **Amount unit** | **Major unit (naira)** — "Amount is in the base unit of the currency". Sample: `"amount": 100` for a KES/NGN charge | Kora API walkthrough; charges docs |
| Verify | `GET /charges/{reference}` | Kora docs "Accept Card Payments with APIs" |
| Verify response | `{"status": true, "message": "…", "data": {"reference", "status": "success", "amount": "2000.00", "amount_paid": "2000.00", "currency", …}}` — **`amount` is a decimal *string* in naira** | Kora docs sample response |
| Webhook header | `x-korapay-signature` | Kora Webhooks doc |
| Signature | `hex(HMAC_SHA256(secret_key, JSON.stringify(body.data)))` — **the `data` object only**, nothing else | Kora Webhooks doc |
| Webhook events | `charge.success`, `charge.failed`, `transfer.success`, `transfer.failed`, `refund.success`, `refund.failed` | Kora Webhooks doc |
| Webhook payload | `{"event", "data": {"fee", "amount", "status", "currency", "reference", "payment_reference", "payment_method", "transaction_date", …}}` — `amount` is a JSON **number** in naira | Kora Webhooks doc |
| Retries | non-200 or timeout ⇒ retried periodically **for up to 72 hours**; only the status code is inspected | Kora Webhooks doc |
| Dedup guidance | "Keep track of all notifications received… check that this has not been processed before" | Kora Webhooks doc |
| Fee bearer | **The payer bears the fee.** Kora's fee is not deducted from the amount Credence receives, so the verified amount is gross | **Decided in review (D-11)** — supersedes v1's open K-7 |

### 8.1.1 Three consequences the PRD does not anticipate

1. **`amount` is naira in both directions, but as a *string* on verify and a *number* on webhook.** Any comparison must normalise to kobo integers (§8.4). `float(amount) * 100` is banned: `150.99 * 100 == 15098.999999999998` in IEEE-754, and a kobo lost to rounding is a wrong balance.
2. **Signature verification re-serialises `data`.** Kora signs `JSON.stringify(data)`, so our verification must reproduce byte-for-byte what Kora stringified. Python's `json.dumps` with default separators will not match. §8.5 gives the algorithm and the fallback.
3. **`status` appears in two places** — a top-level `status: true` (request succeeded) and `data.status: "success"` (the payment succeeded). Reading the wrong one marks failed payments successful. The client parses `data.status` only.
4. **`data.fee` exists and must be ignored in arithmetic.** The payer bears the fee, so the amount we verify is already the amount the transaction is credited with. `fee` is left inside `payments.raw_webhook` for reconciliation; subtracting it would under-credit every debt by Kora's cut (§8.4).

## 8.2 What must be verified in the sandbox before writing payment code

**[VERIFY]** — do these in the first hour of Wednesday, in order, against `sk_test_…`:

| # | Check | Why it blocks code |
| --- | --- | --- |
| K-1 | `POST /charges/initialize` with `amount: 1500.00` (₦1,500) and confirm checkout shows ₦1,500, then verify returns `"amount": "1500.00"` | Confirms naira-in/naira-out and our ×100 conversion |
| K-2 | Does `amount` accept `1500` (int) and `"1500"` (string)? | Determines whether we send `str(Decimal)` or `int` for whole naira |
| K-3 | Capture a real webhook body and the header; reproduce the HMAC in Python with `json.dumps(data, separators=(",",":"))` and compare | Confirms canonicalisation actually matches; if not, switch to raw-substring extraction (§8.5.3) |
| K-4 | Send `charge.failed` — confirm `data.status == "failed"` and whether `failure_reason`/`message` is present | Determines what we can show as a failure message |
| K-5 | Does `notification_url` in the initialize body override the dashboard webhook URL? | Decides whether we pass it per-charge or configure once |
| K-6 | Verify response for a failed/abandoned charge: is `status: false`, or `data.status: "failed"`? | The "not successful" branch must not throw |
| ~~K-7~~ | ~~Exact fee-bearer field name and whether the fee reduces the settled amount~~ | **Retired in v2 (D-11).** The payer bears the fee, the verified amount is gross, and `data.amount` is authoritative. Nothing to verify in the sandbox |

Until K-1…K-6 are answered, no code in `integrations/kora` is written beyond the signature helper. Recording the answers in `docs/architecture/kora-notes.md` is part of the task. K-7 is retired by decision D-11 and no longer blocks anything; K-1 and K-2 still matter, because they confirm the naira↔kobo boundary the whole money model rests on.

## 8.3 Payment references

```
kora_reference = f"{transaction.reference}-P{attempt_number}"
                = "CRD-000123-P3"
```

| Property | Why |
| --- | --- |
| Deterministic derivation from our own data | Kora's reference is also a merchant lookup key; a readable reference makes the Kora dashboard usable during the demo |
| `UNIQUE (transaction_id, attempt_number)` | Two concurrent clicks cannot allocate the same attempt; the loser retries under the row lock |
| `UNIQUE (kora_reference)` globally | A webhook can only ever map to one payment row |
| Never reused after failure | A failed `P1` stays failed; the retry button creates `P2`. Reusing a reference after failure is how "why did my second payment show as the first" incidents happen |

Receipt numbers use a **separate** sequence (`payment_receipt_seq`) so receipt numbering has no gaps from failed attempts.

## 8.4 Amount comparison — the only correct way

```python
# app/core/money.py
from decimal import Decimal, ROUND_HALF_UP

KOBO = Decimal("100")

def kobo_to_naira(amount_kobo: int) -> Decimal:
    """Exact; only used at the Kora boundary and for display."""
    return (Decimal(amount_kobo) / KOBO).quantize(Decimal("0.01"))

def naira_to_kobo(value: str | int | Decimal) -> int:
    """Parse a provider amount into kobo without ever using float."""
    d = Decimal(str(value))
    return int((d * KOBO).to_integral_value(rounding=ROUND_HALF_UP))

def format_naira(amount_kobo: int) -> str:
    return f"₦{kobo_to_naira(amount_kobo):,.2f}"   # ₦150,000.00
```

Verification rule:

```python
expected_kobo = payment.amount_kobo                       # what we asked Kora to charge
actual_kobo   = naira_to_kobo(verify.data["amount"])      # "100000.00" -> 10_000_000
credited_kobo = actual_kobo                               # GROSS. Kora's fee is NOT subtracted.
currency_ok   = verify.data["currency"] == "NGN"
status_ok     = verify.data["status"] == "success"

if not (status_ok and currency_ok and credited_kobo == expected_kobo):
    mark_failed(payment, reason=…); return
```

### 8.4.1 Gross, not net — the fee rule (D-11)

Kora's fee is **borne by the payer**. The amount Kora verifies is therefore the amount the debtor actually paid towards the debt, and it is credited in full:

| Kora verified `data.amount` | Credited | Stored where |
| --- | --- | --- |
| `"1000.45"` (₦1,000.45) | `100045` kobo | `payments.amount_kobo = 100045` |
| `"150000.00"` (₦150,000.00) | `15000000` kobo | balance drops by exactly ₦150,000.00 |

Worked conversion, spelled out because two mistakes are easy here:

```
Decimal("1000.45")           # never float("1000.45")
  × Decimal("100")           # = Decimal("100045.00")
  .to_integral_value(ROUND_HALF_UP)
  → 100045                   # int kobo, exact
```

`float("1000.45") * 100 == 100044.99999999999`, which truncates to `100044` — one kobo of the debtor's money lost on every such payment, and a receipt that does not reconcile.

**What is explicitly not done:**

| Not done | Why |
| --- | --- |
| `credited = amount − data.fee` | The payer paid the fee on top; subtracting it invents a loss Credence did not take |
| Storing a `net_amount_kobo` column | There is no net amount in this model — one number, one meaning |
| Comparing `data.amount_paid` when it differs from `data.amount` | `amount` is the charge amount and the unit of the equality check (closed Q-12). If a sandbox test ever shows them diverging, that is a K-1/K-2 finding, recorded in `kora-notes.md`, not a code branch |
| Reporting the fee to the debtor mid-checkout | Irrelevant to what they owe |

If Credence ever decides to absorb Kora's fee itself, that is a **new** decision: a `fee_absorbed_kobo` column, a changed credit rule, and a new ADR. It is not a configuration switch, because it changes what the ledger means.

| Case | Action |
| --- | --- |
| `actual == expected` | Apply the payment (§8.6) |
| `actual < expected` | **Fail** the payment with `amount_mismatch`; alert in logs; balance unchanged. A merchant cannot be asked to accept partial settlement of a charge without our consent — but see §8.8.4 for the "under-paying into the invoice" path, which is a *separate* payment, not this one |
| `actual > expected` | **Fail** with `amount_over_mismatch`; balance unchanged. Overpayment is handled by `overpaid_kobo` (§8.9) only when *both* charges individually match their own expected amounts |
| `currency != NGN` | Fail with `currency_mismatch` |
| `status` not `success` | Fail with `provider_non_success` |

Numbers are compared as `int` kobo. Nowhere in the codebase is a monetary value a `float` — a CI grep (§12.3) fails the build if `float(` appears next to an amount identifier.

## 8.5 Webhook signature verification

### 8.5.1 The rule

```
header  = request.headers["x-korapay-signature"]        # lowercase hex
expected = hmac.new(secret.encode(), canonical_data.encode(), sha256).hexdigest()
valid   = hmac.compare_digest(expected, header)          # constant time
```

`hmac.compare_digest` — not `==` — so an attacker cannot time-attack the comparison.

### 8.5.2 Canonicalisation

```python
def canonical_data(raw: bytes) -> str | None:
    payload = json.loads(raw)
    data = payload["data"]
    # 1) compact separators, no whitespace — matches JSON.stringify
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
```

`ensure_ascii=False` matters: a debtor name with `á` is escaped by default `json.dumps`, which changes the bytes and breaks the MAC.

### 8.5.3 The fallback that guarantees correctness

If K-3 in the sandbox shows a mismatch, canonicalisation is not reproducible by re-serialisation (key order, number formatting such as `150.00` vs `150.0`). The robust approach is to verify over the **raw substring** of the original body:

```python
def raw_data_slice(raw: bytes) -> bytes | None:
    """Return the exact bytes of the 'data' value in the original body."""
    text = raw.decode("utf-8")
    key = re.search(r'"data"\s*:\s*', text)
    if not key: return None
    start = key.end()
    if text[start] != "{": return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1].encode("utf-8")
    return None
```

Verify against `raw_data_slice(raw)` **first**, then the canonical-JSON form, accepting if either matches. Record which strategy matched in `kora_webhook_events.outcome` (`applied:raw` / `applied:canon`). This is not over-engineering — it is the difference between "works in the demo" and "silently rejects every real webhook because Kora serialised `150.0`".

**Never** read the signature from the parsed body (Kora does not put it there) and **never** accept an unsigned webhook in a "sandbox mode" flag in production config.

## 8.6 `apply_verified_charge` — the single money mutation

```
INPUT: payment_id, verified_amount_kobo, paid_at, raw_payload

1. BEGIN
2. payment = SELECT … WHERE id=:id FOR UPDATE
3. if payment.status == 'successful': COMMIT; return ALREADY_APPLIED    # idempotent
4. tx = SELECT credit_transactions WHERE id=payment.transaction_id FOR UPDATE
   -- NB: the Kora verify call has ALREADY returned. No network I/O from here on.
5. paid_others = SELECT coalesce(sum(amount_kobo),0) FROM payments
                 WHERE transaction_id=tx.id
                   AND status='successful'
                   AND id <> payment.id            -- exclude the row being applied
6. balance_before = max(tx.amount_kobo - paid_others, 0)
7. credited       = verified_amount_kobo              -- GROSS; Kora's fee is not deducted
8. status_before  = tx.status
9. if status_before == 'cancelled':
       overpaid = None                            -- an overpayment needs a live debt
       review   = 'paid_cancelled_transaction'    -- D-3: record, keep cancelled, flag
   else:
       overpaid = max(credited - balance_before, 0)
       review   = 'overpaid' if overpaid > 0 else None
10. payment.status        = 'successful'
    payment.paid_at       = paid_at
    payment.verified_at   = now()
    payment.receipt_number= "RCT-" + pad(nextval(payment_receipt_seq))
    payment.raw_webhook   = raw_payload
    payment.overpaid_kobo = overpaid              -- NULL when 0
    payment.review_reason = review                -- NULL, 'overpaid', 'paid_cancelled_transaction'
11. balance_after = max(balance_before - credited, 0)
12. status transition (PRD §5) — computed from status_before, never guessed:
      if status_before == 'cancelled':           # terminal: money recorded, status kept
                                                 pass
      elif balance_after == 0:                   tx.status='settled'
                                                 tx.settled_at = tx.settled_at or now()
      elif status_before == 'disputed':          # stays disputed (PRD), money still counts
                                                 pass
      elif status_before in ('pending_ack','active','partially_paid'):
                                                 tx.status='partially_paid'
    settled_now = (tx.status == 'settled' and status_before != 'settled')
13. INSERT exactly ONE payment_received event (actor debtor,
        data{amount_kobo=credited, receipt_number, balance_kobo=balance_after,
             kora_reference, paid_at, provider_mode,
             overpaid_kobo?, review_reason?})
14. if settled_now:
        INSERT settled event; cancel outstanding reminders(skip_reason='settled')
15. PromiseService.check_after_payment(tx, open_promise)   # may insert promise_kept
16. COMMIT
17. AFTER COMMIT: send exactly ONE email
        settled_now → email #7 (settled, links receipt with the SETTLED stamp)
        else        → email #6 (receipt — also for a flagged payment, so the payer has proof)
    failure to send → log + reminder_failed event; never roll back the money
```

**Step 3 is the duplicate-payment defence**; **step 5 is the correctness of the balance** (it sums *verified* payments inside the transaction-row lock and excludes the row being applied, so re-running the function cannot double-count); and **steps 9/12 are where the PRD's unusual terminal rules are honoured literally**:

> "A payment on a disputed transaction is recorded and counted, but the status stays disputed until the creditor resolves it, unless the balance reaches 0, in which case it becomes settled." (PRD §5)

The `elif status_before == 'disputed': pass` branch is that sentence. It is the least intuitive branch in the system, so §12.14 tests it explicitly.

The `status_before == 'cancelled'` branch is decision **D-3** (see §8.9.4): the payment is written as `successful`, `settled_at` stays `NULL`, the transaction stays `cancelled`, and `review_reason='paid_cancelled_transaction'` puts it on the ops worklist. Nothing is reopened, nothing is discarded.

### 8.6.1 Status transition matrix (exhaustive)

| From \ Payment outcome | partial | settles balance | overpays | fails |
| --- | --- | --- | --- | --- |
| `pending_ack` | `partially_paid` | `settled` | `settled` + `overpaid_kobo` | unchanged |
| `active` | `partially_paid` | `settled` | `settled` + flag | unchanged |
| `partially_paid` | stays | `settled` | `settled` + flag | unchanged |
| `disputed` | stays `disputed` | `settled` | `settled` + flag | unchanged |
| `settled` | n/a (pay refused) | n/a | n/a | n/a |
| `cancelled` | stays `cancelled` | stays `cancelled` | stays `cancelled` | unchanged |

Rows in which the payment is applied but the status does not move (`disputed`, `cancelled`) also set `review_reason` when the money cannot be reconciled against a live debt: `paid_cancelled_transaction` always, `overpaid` whenever `credited > balance_before` on a non-cancelled transaction.

`reversed` exists in the enum for a future refund flow; **no MVP code writes it**, and a `reversed` payment is excluded from `sum(successful)` automatically because the sum filters on `status='successful'`.

### 8.6.2 How the six concurrency requirements are met

Your review asked for six specific guarantees. Each is a mechanism in the algorithm above, not an aspiration:

| Requirement | Mechanism | Failure it prevents |
| --- | --- | --- |
| **The same verified payment is never applied twice** | `SELECT payments … FOR UPDATE` + `if status == 'successful': return` (step 3); `UNIQUE(kora_reference)`; `UNIQUE(kora_reference, event)` on the webhook log | A Kora retry, a dashboard "resend", or our own reconciliation re-credit the same money |
| **The transaction row is locked while applying** | `SELECT credit_transactions … FOR UPDATE` (step 4), always after the payment lock — the fixed order in §5.7.1 | A concurrent dispute/cancel/promise writing status from a stale balance read |
| **The outstanding balance is recalculated from verified payments** | `Σ successful` read inside the lock, excluding the row being applied (step 5) — the balance is never incremented or decremented | Drift from a missed event, a double event, or two writers |
| **Settlement side effects fire once** | Every side effect is gated on `settled_now` (transition, not state): one `settled` event, one reminder cancellation, one email #7 | Two "your debt is settled" emails, or reminders cancelled twice and a duplicate timeline entry |
| **Two concurrent successful payments are handled deterministically** | Both serialise on the transaction row; the second sees `balance_before = 0`, records a full overpayment, and skips the settled transition (§5.7.5 worked through) | Undefined behaviour, lost payment, double settlement |
| **Overpayments are detected and flagged, never discarded** | `overpaid = max(credited − balance_before, 0)` → `payments.overpaid_kobo` + `review_reason='overpaid'` + event data + `ix_pay_review` | Money received with no record, or a payment silently failed because the balance was already 0 |

Two further properties worth stating, because they are what make the above testable:

- **The money mutation is bounded by one network call, before the lock.** `verify_charge()` runs first and its result is passed in; the function never calls Kora while holding a row lock. A slow provider therefore cannot hold a transaction open.
- **The function is safe to call from three entry points** — webhook, reconciliation job, and tests — because idempotency lives in the row state, not in the caller. That is why §8.12's safety net is 40 lines and has no special cases.

## 8.7 The complete payment lifecycle

```mermaid
sequenceDiagram
    autonumber
    participant D as Debtor browser
    participant API as Credence API
    participant DB as PostgreSQL
    participant K as Kora
    participant M as Resend

    D->>API: POST /public/tx/{token}/pay {amount_kobo}
    API->>DB: lock tx; validate balance/min
    API->>DB: INSERT payments(initiated, CRD-000123-P1); COMMIT
    API->>K: POST /charges/initialize (amount=₦100,000.00, ref, redirect, notify)
    K-->>API: {checkout_url, reference}
    API->>DB: payments.status=pending, checkout_url; COMMIT
    API-->>D: 201 {checkout_url, reference}
    D->>K: redirect to checkout, pays
    K-->>D: redirect → /pay/{token}/result?ref=CRD-000123-P1

    par Webhook path (authoritative)
        K->>API: POST /webhooks/kora (x-korapay-signature)
        API->>API: HMAC verify (data-only)
        API->>DB: INSERT kora_webhook_events ON CONFLICT DO NOTHING
        API->>DB: payment already successful? → 200 STOP
        API->>K: GET /charges/CRD-000123-P1 (server verify)
        K-->>API: data.status=success, amount="100000.00", currency=NGN
        API->>API: naira_to_kobo(amount) == payment.amount_kobo?
        API->>DB: BEGIN … apply_verified_charge … COMMIT
        API-->>K: 200 OK
    and Result page polling
        D->>API: GET /public/tx/{token}/payments/CRD-000123-P1 (every 3s, ≤30s)
        API-->>D: status (reads our DB only — never calls Kora)
    end

    API->>M: email 6 (receipt) OR email 7 (settled) — exactly one
    D->>API: GET receipt → HTML
```

**The result page never triggers verification.** If the webhook is delayed, the debtor sees "Confirming your payment…" until it lands. That is intentional: a client-driven verify is an attacker-controlled write path. The bounded poll exists so the page gives up gracefully, not so it can force state.

## 8.8 Idempotency, layer by layer

| Layer | Mechanism | Prevents |
| --- | --- | --- |
| 1. Browser double-tap | `Idempotency-Key` header → `payments.idempotency_key` (unique per transaction) | Two checkout pages for one intent |
| 2. Attempt allocation | `UNIQUE(transaction_id, attempt_number)` + row lock | Two payments with the same reference |
| 3. Provider reference | `UNIQUE(kora_reference)` | A reference mapping to two rows |
| 4. Webhook delivery | `UNIQUE(kora_reference, event)` + `ON CONFLICT DO NOTHING` | The same event processed twice (Kora's 72h retries, dashboard "Resend") |
| 5. Payment state | `SELECT … FOR UPDATE` + `if status == 'successful': return` | A second `charge.success` moving money twice |
| 6. Receipt numbering | sequence + `UNIQUE(receipt_number)` | Two receipts for one payment |
| 7. Status recompute | recomputed from the payment sum, not incremented | Any drift from a missed/duplicated event |
| 8. Client intent | `UNIQUE(transaction_id, idempotency_key)` + an amount comparison on replay (§6.7.3) | A double-tap that reuses a key with a *different* amount, and a "retry" that would silently charge again |
| 9. Ops visibility | `review_reason` + `ix_pay_review` | A duplicate that legitimately could not be prevented (two devices, two full payments) becoming invisible money |

**Nothing in the payment path does `balance -= amount`.** The balance is `amount − sum(successful)` every time it is read (§5.1, ADR-3). Duplicate detection is therefore defence-in-depth rather than the only thing standing between a retry and a wrong balance.

### 8.8.1 Duplicate webhook, worked through

```
t0  charge.success arrives → kora_webhook_events row inserted → verify → applied
t+30s same payload arrives (Kora retry because our 200 was slow)
    step 5: INSERT … ON CONFLICT DO NOTHING → rowcount 0 → return 200, no work
t+1h  Kora dashboard "Resend Webhook"
    same as t+30s → 200
t+2h  a *new* charge.failed arrives for a payment already successful
    step 7: payment.status == 'successful' → outcome 'duplicate' → 200
          (a late failure for a settled charge must never un-settle it)
```

### 8.8.2 Webhook arrives before the initialize response is persisted

Kora cannot send a webhook before it returns the checkout URL, but it *can* return while our process is between the Kora call and the `UPDATE … status='pending'`. Because the `initiated` row was committed in step 8 of §6.7.3, the webhook finds `kora_reference`, verifies, and applies. When the initialize response arrives afterwards, it must **not** overwrite a terminal status:

```python
# in initialize(), after the Kora call returns
fresh = session.execute(select(Payment).where(Payment.id == payment.id).with_for_update()).scalar_one()
if fresh.status in (PaymentStatus.SUCCESSFUL, PaymentStatus.FAILED):
    return existing_result(fresh)          # the webhook won the race; keep its verdict
fresh.status = PaymentStatus.PENDING; fresh.checkout_url = resp.checkout_url
```
This is a real, observed ordering in payment integrations and is cheap to handle correctly.

### 8.8.3 Webhook times out but Kora charged

Kora retries for 72 h, so the normal path self-heals. If all retries are lost, `GET /public/tx/{token}/payments/:ref` still shows `pending` and the debtor has a receipt-less payment. The reconciliation job (§8.12) is the answer: it re-verifies stale `initiated`/`pending` payments and applies any that Kora reports successful. This is why `ix_pay_stale` exists.

### 8.8.4 Underpayment made as a deliberate second charge

If the debtor pays ₦40,000 against a ₦50,000 balance by entering ₦40,000 in the pay box, that is a **new** attempt with `amount_kobo = 4_000_000`. It matches its own expected amount, so it applies normally and the balance drops to ₦10,000. "Partial payments" are therefore a first-class supported path (PRD §3, §8.4 step 4), distinct from an amount mismatch on a single charge.

## 8.9 Partial payments, settlement, overpayment

### 8.9.1 Partial

`paid > 0 and paid < amount` ⇒ status `partially_paid` (unless disputed/cancelled). The receipt says "Partially paid", shows `total paid to date` and `balance remaining` computed at render time. Email #6 goes to the debtor, cc the creditor.

### 8.9.2 Settlement

`balance_after == 0` ⇒ `settled`, `settled_at = now()`, all `scheduled` reminders cancelled with `skip_reason='settled'`, one `settled` event, and **email #7 instead of** email #6 — never both (PRD §14 correction 12). Email #7 links the same receipt URL, which renders with the SETTLED stamp.

### 8.9.3 Overpayment

```
balance_before = 5,000,000 kobo (₦50,000)
charge A (P1) = 5,000,000 → applied → balance 0 → settled
charge B (P2) = 5,000,000 → webhook + verify → apply_verified_charge:
    balance_before  = 0
    overpaid_kobo   = 5,000,000
    payment.status  = 'successful'          ← both charges are recorded
    review_reason   = 'overpaid'            ← flagged for investigation/refund
    balance_after   = 0                     ← clamped
    event data     += { overpaid_kobo: 5_000_000, review_reason: 'overpaid' }
    no second 'settled' transition; no second settled email to the debtor
    email #6 (receipt) still goes out for B, so the payer has proof
```

| Rule | Where |
| --- | --- |
| Both charges recorded | `payments` rows, both `successful` |
| Balance clamped at 0 | `max(amount − sum, 0)` in `balance.py` — structural, not a guard |
| Flagged for manual refund | `payments.review_reason='overpaid'` + `payments.overpaid_kobo` + `payment_received.data` (both fields), listed by `ix_pay_review` |
| No double "settled" email | the settled email is only sent on the transition *into* settled in the same transaction that caused it |
| Total collected may exceed extended | `total_collected_kobo` is a sum of payments, so yes — the dashboard's numbers are honest rather than clamped, and the overpayment surfaces as an ops item |
| Refund itself | **out of scope** (no payout/refund in PRD §3) |

How can two charges both succeed when the UI caps the amount at the balance? Two tabs, both showing ₦50,000 outstanding, both paying in full. The server cannot prevent that at init time across two devices — `POST /pay` validates against a balance that is still correct at that instant — so the design accepts it and handles it deterministically instead: **serialise, record both, credit the debt once, flag the excess**.

**What "flagged" means operationally (and what it does not mean):** the payment stays `successful`, the money is in `payments`, the receipt exists, and `ix_pay_review` lists the row with its overpaid amount. Settling the ops item — refunding via Kora, or applying the credit elsewhere — is **out of MVP scope** (there is no refund API in the PRD). What the MVP guarantees is that the surplus is recorded, visible, and impossible to lose, which is the part that cannot be fixed later.

### 8.9.4 Payment on a `cancelled` transaction (D-3, decided)

A debtor can still be looking at a pay page — or a saved email link — for an invoice the creditor cancelled an hour ago. Kora will take the money. The PRD says nothing about this, so v1 asked; the answer is now a rule.

| Aspect | Behaviour |
| --- | --- |
| Is the payment recorded? | **Yes.** `payments.status='successful'`, `paid_at`, `verified_at`, `receipt_number`, `raw_webhook` — a real receipt the payer can open |
| Does the transaction status change? | **No.** `cancelled` is terminal; `settled_at` stays `NULL`; the CHECK on `settled_at` is untouched |
| Is it flagged? | **Yes.** `review_reason='paid_cancelled_transaction'`; the full amount is the item to investigate |
| Is `overpaid_kobo` set? | **No.** There is no live debt to overpay; setting it would imply a balance arithmetic that does not exist here |
| Is the transaction reopened? | **Never.** Reopening would silently undo the creditor's decision and resurrect reminders |
| Is the payment discarded or failed? | **Never.** That would destroy a record of money actually received |
| Which email goes out? | Email #6 (receipt) to the debtor, cc creditor — proof of payment, no "settled" language |
| Do reminders restart? | **No.** The transaction stays `cancelled`; the schedule was cancelled on cancel and is not rebuilt |
| Where does the ops item come from? | `ix_pay_review`, and the `payment_received` event on the timeline with `review_reason` |

This is deliberately the same pattern as overpayment: **record the money, preserve the state machine, surface the anomaly.** The only recovery action in the MVP is a human one — refund the payer in the Kora dashboard, or agree with them to apply it to another invoice — and either way the row stays as the audit evidence of what happened. Q-7 is closed by this decision; §16 records it as decided, not open.

## 8.10 Receipts

### 8.10.1 One template, two outputs

`modules/payments/templates/receipt.html` is a single Jinja2 document with print CSS. HTML is the primary artefact (PRD item 10 MUST); PDF is the same HTML through WeasyPrint (PRD item 13 SHOULD). No second layout, so a change cannot drift between formats.

### 8.10.2 Rendered fields (PRD §8.5)

| Field | Source |
| --- | --- |
| Receipt number | `payments.receipt_number` |
| Creditor name / logo / email | `businesses.name`, `logo_url` (fallback: initials block), `email` |
| Debtor name | `debtors.name` |
| Reference, invoice number | `credit_transactions.reference`, `.invoice_number` |
| Description | `credit_transactions.description` |
| Amount paid this time | `payments.amount_kobo` |
| Date and time paid | `payments.paid_at` rendered in **WAT** for display |
| Method, Kora reference | constant `"Kora"`, `payments.kora_reference` |
| Original amount | `credit_transactions.amount_kobo` |
| Total paid to date | `SUM(successful payments)` **at render time** |
| Balance remaining | `max(amount − total_paid, 0)` **at render time** |
| Balance caption (fixed copy) | "Balance shown as at the time this receipt was viewed." — D-5: the number is the transaction's *current* balance, not a historical snapshot |
| Status | `SETTLED` if balance 0, else `Partially paid` |
| Mode marker | `SANDBOX — test payment` in the header when `payments.provider_mode='sandbox'` (D-10) |

The amount credited on the receipt is `payments.amount_kobo` — the **gross** verified amount. Kora's fee never appears on a Credence receipt, because it was never part of the debt (§8.4.1).

### 8.10.3 Why the balance is computed at render time (and the consequence)

A receipt is a legal-ish document about *this* payment, and the PRD requires "total paid to date" and "balance remaining (calculated at generation)". Computing at render means a receipt for the first of two payments, re-opened later, shows the balance as of *now* — not as of then.

**Decision D-5 makes this explicit rather than implicit.** The receipt states in words that the balance is the transaction's balance at the moment of viewing. A debtor re-opening last month's receipt sees "balance ₦0.00" on a debt they have since cleared, which is the truthful answer to "what do I owe?" and is also what the PRD's wording asks for. What the receipt must *not* do is imply that the number is frozen at payment time; the caption prevents that misreading. Historical snapshots remain a documented future improvement (ADR-12), not an MVP table.

That is a genuine trade-off:

- **Option A (chosen):** compute at render. Nothing to backfill, and a settled receipt always shows `SETTLED` + balance ₦0 even if it is re-opened a week later. Matches the PRD's wording.
- **Option B:** snapshot the balance into a `receipts` table on success. Historically exact, but a new table, a new write in the payment transaction, and a receipt that shows "₦50,000 remaining" forever after the debt was paid.

Option A is right for a debtor-facing document whose purpose is "here is what you owe now". A future audit export would need Option B; that is an ADR (ADR-12) and out of MVP scope.

### 8.10.4 Receipt for a payment on a disputed transaction

Issued (money was received), status line reads "Partially paid", no dispute language on the receipt itself. The debtor page still shows the dispute. A receipt is a record of a payment, not a statement of the whole relationship (A-12).

## 8.11 Payment-related events and emails (nothing else may fire)

| Trigger | Event(s) | Email(s) |
| --- | --- | --- |
| Payment verified, balance > 0 | `payment_received` | #6 Receipt (debtor, cc creditor) |
| Payment verified, balance = 0 | `payment_received` + `settled` (+ `promise_kept`) | **#7 only** |
| Verify says non-success / mismatch | `payment_failed` | none |
| Initialize fails | `payment_failed` | none |
| Payment on disputed tx, balance > 0 | `payment_received` | #6 |
| Payment on a `cancelled` tx | `payment_received` (with `review_reason`) | #6 |
| Payment that overpays | `payment_received` (with `overpaid_kobo`, `review_reason`) | #6, or #7 only if this payment is what settles the debt |
| Promise satisfied by this payment | `promise_kept` (+ the above) | #7 if settled, else #6 |

No email ever says "overdue" about a settled debt, because settling cancels reminders within the same transaction and the email choice is made from the post-settlement status.

## 8.12 Reconciliation job (safety net) [REC]

`run_payment_reconciliation()` — every 30 minutes in the worker, and available as `python -m app.scripts.run_payment_reconciliation_once`.

```
SELECT * FROM payments
 WHERE status IN ('initiated','pending')
   AND created_at < now() - interval '20 minutes'
 LIMIT 50
for each:
    verify with Kora
    success + amount matches  → apply_verified_charge()   # idempotent; same code as webhook
    success + mismatch        → mark_failed(amount_mismatch) + log
    failed / not found        → mark_failed(reconciled_no_charge)
    still pending             → leave (Kora may still be processing); attempt_count++
```

This is the only code path that can rescue a payment whose webhook never arrived, and the only reason a `pending` payment is not a permanent dead end. It is 40 lines, uses the same idempotent `apply_verified_charge` (so if the webhook lands at the same moment, one of them is a no-op), and can be dropped without affecting the demo — hence [REC], not MUST. It never bypasses verification and never invents an overpayment path: if Kora says the amount differs from what we asked, the attempt fails and is logged.

## 8.13 Promises and payments — the exact interaction

```python
# app/modules/promises/service.py
def evaluate(promise, payments, today) -> str:
    """Pure. payments = successful payments of the transaction."""
    window_end = promise.promised_date                     # inclusive, WAT date
    paid_in_window = sum(
        p.amount_kobo for p in payments
        if p.paid_at.date() <= window_end                  # WAT-converted
    )
    target = promise.promised_amount_kobo or promise.balance_at_promise_kobo
    if paid_in_window >= target:
        return "kept"
    if today > window_end:
        return "missed"
    return "still_open"
```

| Situation | Outcome |
| --- | --- |
| Pay ₦100,000 promised, ₦100,000 paid on the promised day | `kept`; `promise_kept` event; score's `promise_rate` improves |
| Pay in two parts totalling the promise, both within the window | `kept` (it is the **sum**, per PRD §7.3) |
| Nothing paid by end of promised date | `missed` (daily job) → reminders resume automatically |
| Paid before the promise date | `kept` immediately (`paid_at ≤ window_end`) |
| Promised full balance, then a partial payment | still open until the window closes |
| New promise made | previous becomes `superseded`; excluded from kept/missed |
| Promise made on an already-overdue transaction | legal; window anchored on `promised_date` (A-4) |
| Transaction settled by a payment | if the settled amount already met the promise, `kept`; if the debt settled with less than the promise (overpayment not possible here — settlement means full balance), `kept` applies when the promise amount ≤ total paid |

`balance_at_promise_kobo` is **[REC]** stored in the promise's `data` when `promised_amount_kobo` is `NULL`, because "the full balance at promise time" is otherwise unrecoverable once payments arrive. It is derived at promise creation and written to the `promise_made` event's `data` — no extra column needed.

## 8.14 Failure modes and exactly what the user sees

| Failure | Internal state | API response | Debtor sees | Creditor sees |
| --- | --- | --- | --- | --- |
| Kora initialize 5xx/timeout | `payments.failed`, `init_error` | `502 PAYMENT_INIT_FAILED` | "Payment could not start. Try again." | `payment_failed` event |
| Debtor abandons checkout | `payments.pending` → reconciled to `failed` in 20 min | poll returns `pending` then `failed` | "Confirming…" then "Payment failed / Try again" | event once reconciled |
| Card declined | `payments.failed`, `provider_declined` | heard via webhook | "Payment failed" + Try again | `payment_failed` event |
| Webhook signature bad | nothing changes | `401` to Kora | no change | nothing (recorded in `kora_webhook_events`) |
| Webhook duplicate | nothing changes | `200` | no change | no duplicate event |
| Verify says success, amount ≠ expected | `payments.failed`, `amount_mismatch` | — | "Payment failed" (honest: we did not credit it) | `payment_failed` + ops alert in logs |
| Two charges succeed (race) | both successful, second has `overpaid_kobo` | — | one receipt each | both payments listed; overpayment visible for refund |
| Webhook arrives for unknown reference | `kora_webhook_events.unknown_reference` | `200` | — | nothing to see; row available for triage |
| Verified payment on a `cancelled` tx | payment `successful`, tx still `cancelled`, `review_reason='paid_cancelled_transaction'` | — | receipt for the payment; invoice still reads cancelled | payment listed, flagged for investigation/refund |
| Verified payment overpays | payment `successful`, `overpaid_kobo`, `review_reason='overpaid'` | — | receipt for what they paid | payment listed, overpayment visible for refund |
| Duplicate payment key, different amount | nothing created | `409 IDEMPOTENCY_KEY_REUSED` | "This payment was already started" | — |

## 8.15 Kora details still to confirm (consolidated)

K-1…K-6 above (K-7 retired by D-11), plus:

| # | Question | Impact if wrong | Mitigation |
| --- | --- | --- | --- |
| K-8 | Does the sandbox support a fake success without a real card (test card numbers, or a "simulate" endpoint)? | Cannot complete the demo story before Friday | Confirm Wednesday AM; if not, use a real ₦100 sandbox card charge and escalate to Kora support early |
| K-9 | What is the checkout URL's TTL? | A pay link emailed Monday may have a dead checkout Thursday | Re-initialise on click (already the design: a new attempt per click!) |
| K-10 | Are there per-merchant reference-format restrictions? | `CRD-000123-P1` rejected | Fallback: `CRD000123P1` (no hyphens) behind a config-derived formatter |
| K-11 | Does Kora send the webhook for the virtual-account/bank-transfer channel with a different `data` shape? | A shape-specific parse breaks on the channel the demo picks | Parse defensively: `data.reference` + `data.amount` + `data.status` only |
| K-12 | Are webhooks signed with the **secret** key in test mode too? | Signature tests in sandbox fail | Confirmed approach: same key; test with real sandbox webhook |

The design deliberately depends on a **minimal** Kora surface: one initialize call, one verify call, one webhook event family, signature header. Everything else (their dashboard, payment links, refunds) is unused.

---

# 9. Background Jobs and Notifications

## 9.1 Scheduler choice

**Recommendation: APScheduler, in a separate `worker` process, driving jobs that read and write PostgreSQL.**

| Option | Fit | Verdict |
| --- | --- | --- |
| **APScheduler 3.x, `BlockingScheduler`, separate process** | `IntervalTrigger(minutes=15)` + `CronTrigger(hour=0, minute=5, timezone="Africa/Lagos")`; jobs are plain functions; no broker, no extra service | **Chosen.** ~30 lines of wiring, one dependency, survives restarts because all state is in `reminders` |
| Celery + Redis + beat | Robust retries/visibility, but a Redis instance, two more processes, a broker dependency and a serialization boundary for every job | Rejected for MVP (ADR-2) |
| OS cron / platform cron hitting an HTTP endpoint | No library, but requires a public authenticated endpoint, no misfire handling, and platform cron is often 1-min granularity with no timezone awareness | Rejected: adds an attack surface (a URL that sends emails) |
| Postgres `pg_cron` | Excellent, runs even if the worker is down | Rejected: not available on every managed provider the team may pick; noted as an upgrade |
| Never — compute reminders lazily on read | Zero infra, but nothing sends email while nobody is looking | Rejected: automated reminders are the product |

**Non-negotiables regardless of scheduler** (this is why the choice is low-risk):

1. All state is in `reminders`. The scheduler only decides *when to look*.
2. Duplicate execution is harmless (`FOR UPDATE SKIP LOCKED` + status transitions).
3. A missed tick is caught up: the job selects `scheduled_for <= now()`, not "== now".
4. A manual trigger exists: `python -m app.scripts.run_reminders_once`, and (dev-only) `POST /internal/jobs/reminders` guarded by a shared secret — the demo-day rescue button.

## 9.2 Worker topology

```python
# app/worker.py
scheduler = BlockingScheduler(timezone=WAT)

scheduler.add_job(run_reminder_tick, IntervalTrigger(minutes=15),
                  id="reminders", max_instances=1, coalesce=True,
                  misfire_grace_time=900)
scheduler.add_job(run_promise_check, CronTrigger(hour=0, minute=5, timezone=WAT),
                  id="promises", max_instances=1, coalesce=True)
scheduler.add_job(run_payment_reconciliation, IntervalTrigger(minutes=30),
                  id="reconcile", max_instances=1, coalesce=True)
```

| Setting | Why |
| --- | --- |
| `max_instances=1` | A slow tick must not overlap itself inside one worker |
| `coalesce=True` | After a restart, N missed 15-minute ticks become one run, not N |
| `misfire_grace_time=900` | A tick delayed by a slow email send still runs |
| `BlockingScheduler` | No event loop needed; the jobs use the sync SQLAlchemy session |
| Separate process | A wedged tick cannot stall API latency, and a crash-looping API does not stop reminders |

**If a second worker instance is ever started:** `FOR UPDATE SKIP LOCKED` makes it safe (each reminder is claimed once). Nothing else needs to change — that is the point of state-in-the-database.

## 9.3 The schedule builder (one function, two callers)

### 9.3.1 `build_schedule` — one function, every caller

The v1 draft had a real defect here: an already-overdue transaction could end up with **no reminder at all**, because every candidate date was in the past and the fallback clause was written as a broken condition. Correction **C-A** replaces it with one rule, implemented once:

> **If a transaction is already overdue when a schedule is (re)built, it gets exactly one `overdue_followup` reminder at 09:00 WAT on the next day — 09:00 Africa/Lagos tomorrow, never a past instant, never immediately.**

```python
# app/modules/reminders/schedule.py — pure: no DB, no ambient clock
REMINDER_HOUR_WAT = 9

def at_9am_wat(day: date) -> datetime:
    """09:00 Africa/Lagos on `day`, as an aware UTC instant."""
    return datetime(day.year, day.month, day.day, REMINDER_HOUR_WAT,
                    tzinfo=WAT).astimezone(UTC)

def next_overdue_slot(now_utc: datetime) -> datetime:
    """THE rule for an already-overdue transaction: 09:00 WAT on the next day."""
    return at_9am_wat(today_wat(now_utc) + timedelta(days=1))

def build_schedule(issue_date, due_date, now_utc,
                   reference_today=None, existing_kinds=()) -> list[ReminderPlan]:
    today = reference_today or today_wat(now_utc)
    plans: list[ReminderPlan] = []
    overdue_pending = any(k.startswith("overdue") for k in existing_kinds)

    candidates = [
        ("upcoming",         due_date - timedelta(days=3)),
        ("due_today",        due_date),
        ("overdue_1",        due_date + timedelta(days=3)),
        ("overdue_followup", due_date + timedelta(days=7)),
    ]
    for kind, day in candidates:
        if kind in existing_kinds:          # rebuild: never duplicate a kind
            continue
        if day < today:                     # PRD §7.2: never schedule into the past
            continue
        slot = at_9am_wat(day)
        if slot <= now_utc:                 # today's 09:00 already passed
            slot = next_tick_instant(now_utc)   # send on the next tick, not "in the past"
        plans.append(ReminderPlan(kind=kind, scheduled_for=slot))
        if kind.startswith("overdue"):
            overdue_pending = True

    # ---- C-A: already overdue and nothing overdue outstanding -> tomorrow 09:00 WAT
    if due_date < today and not overdue_pending:
        plans.append(ReminderPlan("overdue_followup", next_overdue_slot(now_utc)))

    return plans
```

`new_credit` is the one reminder built elsewhere: it is immediate (created with the transaction, `scheduled_for = now`), because the PRD's first email is a notice, not a 9 a.m. nudge.

**Why "tomorrow", not "today at 09:00 if it has not passed":** a debtor whose invoice was already overdue when the creditor recorded it must not receive a chase email minutes after data entry, and must not receive one at an instant that has already gone by. One deterministic answer — tomorrow at 09:00 WAT — is easier to explain to a creditor, easier to test, and identical whether the transaction is created at 08:00 or 23:00.

**The three cases this function must produce, and nothing else:**

| Situation at build time | Resulting `overdue_followup` | Why |
| --- | --- | --- |
| `due_date` in the future | at `due_date + 7` (09:00 WAT) | normal chain |
| `due_date == today` | at `due_date + 7`; `due_today` fires today | the debt is not yet overdue |
| `due_date < today` (already overdue) | **one row at 09:00 WAT tomorrow**; `upcoming`, `due_today`, `overdue_1` all skipped as past | C-A; the debt still gets chased, starting on the next eligible day |

### 9.3.2 Creation vs rebuild — the difference

| | Creation | Rebuild (dispute resolve) | Promise expiry (tick) |
| --- | --- | --- | --- |
| Trigger | `POST /transactions` | `POST /transactions/:id/resolve-dispute` | the 15-minute tick, once `promised_date < today` |
| Anchor | `issue_date`/`due_date` | current WAT date | current WAT date |
| Existing rows | none | `scheduled` rows cancelled with `skip_reason='disputed'`; `sent` kinds remembered | the moved row itself is re-dated, not rebuilt |
| Already-overdue handling | one `overdue_followup` at 09:00 WAT tomorrow | **same rule, same function** | the moved row already sits at 09:00 WAT of a future day |
| Result | 0–4 planned rows + the new-credit row | 1–3 rows, whichever are still in the future | one row, unchanged in kind |

**One rule, five entry points.** The point of putting `next_overdue_slot()` in `schedule.py` is that every caller necessarily agrees:

| Entry point | Calls | Already-overdue transaction ends up with |
| --- | --- | --- |
| Transaction creation (§6.5.1) | `build_schedule(...)` | `overdue_followup` @ 09:00 WAT tomorrow |
| Dispute resolution (§6.5.6) | `build_schedule(..., reference_today=today_wat())` | `overdue_followup` @ 09:00 WAT tomorrow |
| Reminder rebuild (§9.3.3) | `build_schedule(...)` with `existing_kinds` | the same, unless an overdue kind is already sent/scheduled |
| Promise created (§6.7.5) | does not rebuild — the tick moves the row (§9.5.2) | the existing overdue row, moved to 09:00 WAT after the promised date |
| Promise expired (§9.9) | tick resumes the moved row | the moved row, which is always in the future |

**Disputed transactions stay out of this entirely.** Raising a dispute cancels `scheduled` rows; the rebuild only runs on resolution, and `build_schedule` is never called for a `disputed` transaction. The tick additionally re-checks status before sending (§9.5.2), so a reminder cannot slip out while a dispute is open even if a row were somehow left behind.

### 9.3.3 `rebuild_for_transaction`

```sql
UPDATE reminders SET status='cancelled', skip_reason='disputed', updated_at=now()
 WHERE transaction_id = :id AND status = 'scheduled';
```
then insert plans from `build_schedule(..., reference_today=today_wat())`, passing `existing_kinds` = every kind already `sent` **or** already `scheduled` in the future (idempotent under double-click, and the only reason a double-resolve cannot produce two identical reminders).

The cancelled rows keep `skip_reason='disputed'`, so the timeline can explain the gap. An already-overdue transaction that is resolved today gets its `overdue_followup` at 09:00 WAT tomorrow — the same slot it would have received at creation (§9.3.1), which is what makes the rule consistent across the two paths rather than "close enough".

**Re-sending a reminder that was already sent before the dispute**: the rebuild does not reset `sent` rows, so the debtor is not re-spammed with a "Due today" they already received. The new schedule starts from the current date.

## 9.4 Template selection at send time (never at schedule time)

```python
def choose_template(tx, balance_kobo, today) -> str:
    if tx.status == PENDING_ACK:            return "new_credit"        # PRD §7.2
    days_overdue = (today - tx.due_date).days
    if days_overdue < 0:                    return "upcoming"
    if days_overdue == 0:                   return "due_today"
    if 1 <= days_overdue <= 6:              return "overdue_1"
    return "overdue_followup"
```

This is why a delayed reminder never says the wrong thing (PRD §14 correction 7): the `kind` column is *why it was scheduled*, the template is *what it says now*. `kind` and chosen template are both written to the `reminder_sent` event's `data` so the timeline can show `"Due today" reminder (scheduled as upcoming)` if they ever diverge.

**The manual button uses the same function** — so "Send reminder now" on a 10-day-overdue invoice sends the follow-up wording, and on a `pending_ack` invoice sends the original new-credit notice.

## 9.5 The 15-minute tick, exactly

```python
def run_reminder_tick(now=None):
    now = now or now_utc()
    for reminder in claim_due_reminders(now, limit=50):
        with SessionLocal() as session:
            try:
                process_one(session, reminder, now)
            except Exception as exc:
                record_failure(session, reminder, exc)
```

### 9.5.1 Claim (the only place locking matters)

```sql
WITH due AS (
  SELECT id FROM reminders
   WHERE status = 'scheduled'
     AND scheduled_for <= :now
     AND (locked_until IS NULL OR locked_until < now())
   ORDER BY scheduled_for
   LIMIT 50
   FOR UPDATE SKIP LOCKED
)
UPDATE reminders r
   SET locked_until = now() + interval '5 minutes',
       attempt_count = r.attempt_count + 1
  FROM due
 WHERE r.id = due.id
RETURNING r.*;
```

`SKIP LOCKED` is what makes two workers, or an overlapping tick, safe. `locked_until` is what makes a *crashed* worker's rows reclaimable (5 minutes later) without a manual unstick.

### 9.5.2 Decide and send

```
load transaction (fresh), compute balance NOW
if tx.status in ('settled','cancelled'):
    status='skipped', skip_reason=tx.status              → event? no (nothing happened to the debtor)
elif tx.status == 'disputed':
    status='skipped', skip_reason='disputed'
elif open_promise and open_promise.promised_date >= today_wat():
    target = at_9am_wat(max(promised_date, today_wat()) + 1 day)   # always future
    scheduled_for = max(reminder.scheduled_for, target)            # never pull a reminder earlier
    locked_until = NULL                                → stays 'scheduled', not sent
    (attempt_count was already incremented by the claim; harmless for a row that is not sent)
else:
    template = choose_template(...)                    (9.4)
    context  = build_context(tx, balance, debtor, business)   (9.7)
    result   = EmailService.send(template, to=debtor.email, context)
    status    = 'sent', sent_at=now, provider_message_id=result.id
    event      reminder_sent (actor system, data{kind, template, to, provider_message_id})
    if kind == 'overdue_followup':
        INSERT reminders(kind='overdue_followup', scheduled_for=at_9am_wat(today+7), status='scheduled')
```

**Promise handling is a *move*, not a skip** (PRD §14 correction 6): the row stays `scheduled` with a new date, so the reminder really does fire the day after the promise — the exact behaviour the PRD demands.

**The move uses the same slot rule as creation (C-A).** `max(promised_date, today) + 1 day` at 09:00 WAT means a promise made on an already-overdue transaction pushes the reminder to 09:00 tomorrow, never into the past and never earlier than where the row already sat. A promise can delay a reminder; it can never accelerate one.

**The promise check runs before the template decision**, so a promise made 3 seconds ago already protects the debtor from today's 9:00 overdue email.

### 9.5.3 Chain the follow-up

Only on **sent**, never on skip/failure. The chain ends naturally when the transaction settles/cancels, because the next tick's pre-check skips (and the settle path already cancels `scheduled` rows).

### 9.5.4 Timeout and batch size

50 rows × ≤2 s per email ≈ 100 s worst case, well inside the 15-minute interval. If a provider hangs, the 10 s HTTP timeout bounds it.

## 9.6 Manual reminder path (immediate, not queued)

`POST /transactions/:id/remind` sends synchronously so the creditor sees the outcome immediately (PRD: the button is the point). Guards: not `disputed`/`settled`/`cancelled`; ≤1 `manual` send per hour per transaction; template chosen by §9.4; both success and failure recorded with events.

It does **not** touch the automated schedule — sending manually must not consume or shift the `upcoming` reminder. `kind='manual'` rows are excluded from `next_reminder` (which reports the next *automatic* one), and the UI labels it "manual".

## 9.7 Email context and delivery tracking

```python
def build_context(tx, balance, debtor, business) -> dict:
    return {
        "debtor_name": debtor.name,
        "business_name": business.name,
        "reference": tx.reference,
        "invoice_number": tx.invoice_number or "",
        "description": tx.description,
        "transaction_amount": format_naira(tx.amount_kobo),
        "amount_paid": format_naira(tx.paid_kobo),
        "outstanding_balance": format_naira(balance),
        "due_date": format_date_wat(tx.due_date),          # "Fri 27 Nov 2026"
        "days_overdue": str(max((today_wat() - tx.due_date).days, 0)),
        "payment_link": f"{settings.app_url}/pay/{tx.public_token}",
        "receipt_number": …, "receipt_link": …, "response_summary": …,
    }
```

Exactly the placeholder set the PRD lists — no invented ones, and `{{…}}` substitution is a single `str.replace` loop (PRD: "one file with `{{placeholder}}` replacement"), not a template engine with logic. Jinja2 is used **only** for the receipt HTML, where iteration over payments is needed.

**Tracking**

| Field | Purpose |
| --- | --- |
| `provider_message_id` | Resend message id → correlate bounces/complaints in their dashboard |
| `error` | Truncated provider error for `failed` |
| `attempt_count` | Retry budget |
| `reminder_sent` / `reminder_failed` events | User-visible delivery history per transaction |

**Retry policy**

| Attempt | Action |
| --- | --- |
| 1 | send; on transient error (5xx, timeout) → `status='scheduled'`, `scheduled_for = now + 10 min`, `attempt_count=1` |
| 2 | retry; transient → `now + 30 min`, `attempt_count=2` |
| 3 | retry; any failure → `status='failed'`, `error` set, `reminder_failed` event |
| 4+ | never automatic. The creditor can press "Send reminder now" (which creates a new `manual` row) |

Permanent errors (invalid recipient, 4xx) fail immediately with no retry. This bounds inbox spam and database churn while giving a real chance to a flaky provider.

## 9.8 Timezone handling — the rule and the enforcement

| Rule | Implementation |
| --- | --- |
| Store UTC | `TIMESTAMPTZ`; `now_utc()` returns `datetime.now(timezone.utc)` |
| All "today" is WAT | `today_wat()` = `datetime.now(WAT).date()` |
| "9:00 WAT" is an instant | `at_9am_wat(d)` = `datetime.combine(d, time(9,0), tzinfo=WAT).astimezone(timezone.utc)` |
| Never construct naive datetimes | a lint rule/`grep` in CI rejects `datetime.now()` without a tz and `datetime.utcnow()` (naive, deprecated) |
| Display in WAT | `format_date_wat`, `format_datetime_wat` in `core/time.py`; used by receipts, emails and rendered event text |
| `Africa/Lagos` has no DST | so no ambiguity — but the code uses the named zone (`ZoneInfo("Africa/Lagos")`), never `UTC+1`, so the assumption is explicit and correct if that ever changes |

```python
WAT = ZoneInfo("Africa/Lagos")
def today_wat(now: datetime | None = None) -> date:
    return (now or now_utc()).astimezone(WAT).date()
def at_9am_wat(d: date) -> datetime:
    return datetime.combine(d, time(9, 0), tzinfo=WAT).astimezone(timezone.utc)
```

Worked example that catches the classic bug: at 23:30 UTC on 19 Nov it is already 00:30 WAT on 20 Nov. `today_wat()` correctly says 20 Nov, so a due date of 20 Nov is "today", not "tomorrow". Every date comparison in the system uses `today_wat()`, never `date.today()`.

## 9.9 Promise check (daily, 00:05 WAT)

```python
def run_promise_check(now=None):
    today = today_wat(now)
    for promise in open_promises_with(promised_date__lt=today):   # strictly past
        payments = successful_payments(promise.transaction_id)
        outcome = PromiseService.evaluate(promise, payments, today)
        if outcome == "missed":
            promise.promise_status = "missed"
            event promise_missed (actor system)
            # reminders resume automatically: the 15-min tick no longer sees an
            # open promise with promised_date >= today, so it sends the moved row
        elif outcome == "kept":
            promise.promise_status = "kept"      # late payment inside window
            event promise_kept
        # still_open cannot occur for promised_date < today
```

**Why run at 00:05 rather than 23:59:** a payment made at 23:50 WAT on the promised date must count as kept. Running just after midnight in WAT gives the whole promised day (inclusive) before the verdict — matching `window_end` inclusivity in §8.13. The 15-minute tick can also mark a promise kept earlier in the day, which is the demo story's step 6.

**Reminders resume automatically** because the tick's promise branch only delays while `promised_date >= today`. No explicit "resume" call is needed — one rule, one place (PRD §7.3: "Reminders resume automatically").

A missed promise on an already-overdue transaction therefore resumes at the date the tick had already written (09:00 WAT of `promised_date + 1`), and if that instant has somehow passed (worker down for a day) the claim query selects `scheduled_for <= now`, so it sends on the first tick after recovery rather than being lost. That is the same catch-up property the tick has everywhere else, and it is why no code path needs to compute "the next eligible day" twice.

## 9.10 Job inventory

| Job | Schedule | Bounded by | Idempotent because |
| --- | --- | --- | --- |
| `run_reminder_tick` | every 15 min | 50 rows/tick | claim + status transition + `scheduled_for <= now` |
| `run_promise_check` | 00:05 WAT daily | all open promises with a past date | status only moves open → terminal |
| `run_payment_reconciliation` | every 30 min | 50 rows | `apply_verified_charge` is idempotent |
| `seed` | manual (`python -m app.scripts.seed_demo`) | — | wipes and recreates its own demo business only |

**Failed-job handling:** every job catches per-item exceptions, logs with the id, and continues. A job-level failure is logged and (optionally) reported to Sentry; the next tick retries naturally because state is unchanged.

## 9.11 Promise lifecycle

```mermaid
stateDiagram-v2
    [*] --> Open: debtor POST /promise<br/>(supersedes any prior Open)
    Open --> Kept: Σ verified payments<br/>up to promised_date ≥ promised_amount
    Open --> Missed: promised_date passed<br/>& amount not met (daily job)
    Open --> Superseded: a newer promise arrives
    Kept --> [*]
    Missed --> [*]
    Superseded --> [*]

    note right of Open
      Reminders move to 9:00 WAT
      the day after promised_date
    end note
    note right of Missed
      Reminders resume automatically
      on the next 15-min tick
    end note
```

Only `Kept` and `Missed` feed the score; `Superseded` is excluded from both numerator and denominator (PRD §7.3).

## 9.12 Dispute lifecycle

```mermaid
stateDiagram-v2
    [*] --> AnyOpen: transaction active/pending_ack/partially_paid
    AnyOpen --> Disputed: debtor POST /dispute<br/>reminders cancelled (reason=disputed)
    Disputed --> Disputed: verified payment arrives<br/>(recorded; status unchanged)
    Disputed --> Settled: balance reaches 0 by payment
    Disputed --> PartiallyPaid: creditor resolve + paid > 0
    Disputed --> Active: creditor resolve + nothing paid
    Disputed --> Settled: creditor resolve + balance 0
    PartiallyPaid --> Settled: remaining balance paid
    Active --> [*]
    Settled --> [*]

    note right of Disputed
      Reminders rebuilt on resolve
      from the current date
    end note
```

Every arrow into `PartiallyPaid`/`Active`/`Settled` out of `Disputed` runs the resolve flow (§6.5.6) and rebuilds the schedule (§9.3.3).

---

# 10. Repayment Score Engine

## 10.1 What it answers, and what it must never use

The score answers **"Can I extend credit to this person again?"** (PRD §7.4). Its only inputs are:

1. `payments` rows with `status='successful'` (verified money), and
2. `debtor_responses` rows with `promise_status IN ('kept','missed')` (recorded outcomes).

Explicitly **not** inputs: message text, reminder counts, how often someone was chased, dispute reasons, the debtor's own claims, or anything a human typed. No sentiment analysis, no scoring model. [PRD]

The score is **computed on every read**. There is no `debtors.score` column, no cached value, no nightly recompute job. [PRD]

## 10.2 Selection rules (the part that is easy to get wrong)

### 10.2.1 Counted transactions

> "this debtor's transactions with this business that are not cancelled and not currently disputed, and that are settled or past their due date" (PRD §7.4)

```sql
-- counted set for one debtor
SELECT ct.id, ct.amount_kobo, ct.due_date, ct.settled_at, ct.status
  FROM credit_transactions ct
 WHERE ct.business_id = :bid
   AND ct.debtor_id   = :did
   AND ct.status NOT IN ('cancelled','disputed')
   AND (ct.status = 'settled' OR ct.due_date < :today_wat)
```

| Inclusion question | Answer | Reason |
| --- | --- | --- |
| Due **today**, unpaid | **excluded** | Not yet "past" its due date; judging it would penalise a debtor still inside their window |
| Settled before due | included, on time | |
| Settled after due | included, late | |
| `partially_paid`, past due, balance > 0 | included, late (unsettled) | Past due, so it counts — and it hurts, which is correct |
| `pending_ack`, past due | included, late | Silence is not a defence; the debt was recorded and is overdue |
| `disputed` | excluded while open | PRD: "never treated as a confirmed default until a person reviews it" |
| `cancelled` | excluded forever | Never a real debt |
| Disputed then **resolved** | included from that moment (if settled/past due) | Resolution is the review the PRD requires |

> **Demo-critical detail (PRD §14 correction 2):** the live ₦150,000 transaction created on demo day is due 27 Nov, so on 20 Nov it is **not counted**. Bright Foods' score therefore cannot move because of that transaction — it moves because the promised amount is **kept**, which changes `promise_rate`. That is why the PRD requires seeded history and why `promise_rate` carries weight 0.3.

### 10.2.2 Promise outcomes

```sql
SELECT
  count(*) FILTER (WHERE dr.promise_status = 'kept')   AS kept,
  count(*) FILTER (WHERE dr.promise_status = 'missed') AS missed
  FROM debtor_responses dr
  JOIN credit_transactions ct ON ct.id = dr.transaction_id
 WHERE ct.business_id = :bid
   AND ct.debtor_id   = :did
   AND ct.status NOT IN ('cancelled','disputed')
   AND dr.type = 'promise'
   AND dr.promise_status IN ('kept','missed')
```

Note the difference from counted transactions: promises count across **all** non-cancelled, non-disputed transactions — a promise on a not-yet-due transaction still counts (it has already resolved). `superseded` and `open` are excluded from both sides. [PRD §7.3]

## 10.3 The aggregates

```sql
WITH counted AS (
  SELECT ct.id, ct.amount_kobo, ct.due_date, ct.settled_at, ct.status,
         coalesce(p.paid_kobo, 0) AS paid_kobo
    FROM credit_transactions ct
    LEFT JOIN (
      SELECT transaction_id, sum(amount_kobo) AS paid_kobo
        FROM payments WHERE status = 'successful'
       GROUP BY transaction_id
    ) p ON p.transaction_id = ct.id
   WHERE ct.business_id = :bid AND ct.debtor_id = :did
     AND ct.status NOT IN ('cancelled','disputed')
     AND (ct.status = 'settled' OR ct.due_date < :today)
)
SELECT
  count(*)                                                      AS counted,
  count(*) FILTER (WHERE settled_on_time)                        AS on_time,
  count(*) FILTER (WHERE NOT settled_on_time)                    AS late,
  coalesce(avg(days_late) FILTER (WHERE NOT settled_on_time), 0)  AS avg_days_late,
  count(*) FILTER (WHERE paid_kobo > 0 AND paid_kobo < amount_kobo
                     AND status <> 'settled')                    AS partial_payments
FROM (
  SELECT *,
         (settled_at IS NOT NULL
          AND (settled_at AT TIME ZONE 'Africa/Lagos')::date <= due_date) AS settled_on_time,
         greatest(coalesce((settled_at AT TIME ZONE 'Africa/Lagos')::date, :today) - due_date, 0)
                                                                 AS days_late
    FROM counted
) t;
```

Plus the promise aggregate (10.2.2) and the open-dispute count (a displayed fact, not a score input):

```sql
SELECT count(*) FROM debtor_responses dr
  JOIN credit_transactions ct ON ct.id = dr.transaction_id
 WHERE ct.business_id=:bid AND ct.debtor_id=:did
   AND dr.type='dispute' AND dr.resolved_at IS NULL;
```

Three queries per debtor, or **three queries for a whole page** using `debtor_id = ANY(:ids)` with `GROUP BY ct.debtor_id`. The list endpoint must batch: one query per debtor is the N+1 that turns a 50-debtor list into 150 round trips.

### 10.3.1 `avg_days_late` semantics

| Case | `days_late` |
| --- | --- |
| Settled on/before due | 0, and not included in the average (it is not a late row) |
| Settled 5 days after due | 5 |
| Unpaid, 12 days past due | 12 (`today − due_date`) |
| Unpaid, due today | excluded from the counted set entirely |

Averaged over **late counted transactions only**, per PRD. If there are none, `avg_days_late = 0`, so `lateness = 1.0`.

## 10.4 The formula, with the rounding that matters

```python
def compute(facts) -> ScoreResult:
    if facts.counted == 0:
        return ScoreResult(value=None, label="No history yet", category="no_history")

    on_time_rate = Decimal(facts.on_time) / Decimal(facts.counted)
    promise_rate = (
        Decimal(facts.kept) / Decimal(facts.kept + facts.missed)
        if (facts.kept + facts.missed) > 0 else Decimal(1)        # PRD: 1.0 if none
    )
    lateness = Decimal(1) - min(Decimal(facts.avg_days_late), Decimal(30)) / Decimal(30)

    raw = Decimal(100) * (Decimal("0.5") * on_time_rate
                        + Decimal("0.3") * promise_rate
                        + Decimal("0.2") * lateness)
    value = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))  # NOT round()
    return ScoreResult(value=value, **_category(value))
```

| Decision | Why |
| --- | --- |
| `Decimal`, not `float` | `0.5*a + 0.3*b + 0.2*c` in binary floats yields `81.99999999999999`, so `82` becomes `81` under `round()` |
| `ROUND_HALF_UP`, not `round()` | `round()` is banker's rounding: `round(82.5) == 82` but `round(83.5) == 84`. The PRD says "round(100 × …)"; half-up is the conventional reading and is platform-stable |
| `min(avg, 30) / 30` | 30+ days late floors `lateness` at 0; maximum lateness penalty is 20 points |
| `promise_rate = 1.0` when no promises | A debtor who never promised is not penalised |
| `counted == 0` ⇒ `no_history` | **Decided (D-6, Option A).** Promises alone never produce a number: a kept promise is a statement of intent kept, not evidence of repayment. The PRD's own category table says "No counted transactions → No history yet", and this follows it |

> **The one place the literal formula and the literal category rule could disagree — now decided (D-6).** A debtor with promise outcomes and zero counted transactions *would*, by the raw formula alone, score at most 50 (`0.3×1 + 0.2×1`, since `on_time_rate` has no denominator). That is exactly the score that would mislead a creditor: it looks like a repayment record when there is no repayment record. So:

| Input available | Output |
| --- | --- |
| counted transactions = 0, promises kept/missed > 0 | `score.value = null`, `label = "No history yet"`, `category = "no_history"`, **facts block populated** with `promises_kept` / `promises_missed` |
| counted transactions = 0, no promises | the same, facts at zero |
| counted transactions > 0 | the full formula (promises contribute via `promise_rate`) |

The API is explicit about the distinction rather than hiding it: the debtor profile shows "No history yet" **and** a separate line reading e.g. "1 promise kept, 1 missed". A zero is not rendered anywhere near the score, so the frontend cannot print `0` as a score by accident.

This closes Q-8. It also means `promise_rate` never has a silent denominator of zero producing a fabricated number: when there are promises but no counted transaction, the score is absent by construction, not by a special case in the renderer.

### 10.4.1 Categories

| Value | `category` | `label` | UI |
| --- | --- | --- | --- |
| 80–100 | `strong` | "Strong repayment record" | green |
| 50–79 | `mixed` | "Mixed repayment record" | amber |
| 0–49 | `weak` | "Weak repayment record" | red |
| none | `no_history` | "No history yet" | grey, **no number** |

Boundaries inclusive exactly as the PRD's table: 80 strong, 79 mixed, 50 mixed, 49 weak.

## 10.5 Worked example — Bright Foods after the demo story

Seed: settled transactions (2 on time, 1 five days late), 3 promises (2 kept, 1 missed), plus the live ₦150k (due 27 Nov, not counted) and the demo promise of ₦100k kept on 20 Nov.

| Fact | Value |
| --- | --- |
| counted | 3 |
| on_time | 2 → `on_time_rate = 0.667` |
| late | 1 |
| avg_days_late | 5 → `lateness = 1 − 5/30 = 0.833` |
| promises | kept 3, missed 1 → `promise_rate = 0.75` |
| score | `100 × (0.5×0.667 + 0.3×0.75 + 0.2×0.833) = 100 × (0.333 + 0.225 + 0.167) = 72.5 → 73` |

Before the demo promise is kept: `kept=2, missed=1 → promise_rate 0.667 → 70`. After: **73** — a 3-point move, still "Mixed". Honest, but not a dramatic on-stage change.

To make the story land as **Strong**, the seed must make the kept promise the marginal input:

| Seed variant | counted | on time | avg late | kept:missed before → after | score before → after |
| --- | --- | --- | --- | --- | --- |
| A | 3 | 2 | 5 | 2:1 → 3:1 | 70 → 73 (Mixed) |
| **B (recommended)** | 4 | 3 | 3 | 2:1 → 3:1 | 78 → **81** (Mixed → **Strong**) |
| C | 3 | 3 | 0 | 2:1 → 3:1 | 87 → 90 (already Strong; no visible transition) |

Variant **B** produces the visible Mixed→Strong flip PRD §11 asks for ("a mixed-to-strong score that moves when the live promise is kept"). §15.5 specifies seed B's exact rows.

## 10.6 API surface

```json
{
  "score": {
    "value": 81,
    "label": "Strong repayment record",
    "category": "strong",
    "facts": {
      "transactions_counted": 4,
      "paid_on_time": 3,
      "paid_late": 1,
      "avg_days_late": 3,
      "promises_kept": 3,
      "promises_missed": 1,
      "partial_payments": 0,
      "open_disputes": 0
    },
    "note": "Based on verified payments and recorded promise outcomes."
  }
}
```

| Surface | Shape |
| --- | --- |
| `GET /debtors` (badge) | `value`, `label`, `category` — no facts (payload size) |
| `GET /debtors/:id` | full block with `facts` |
| Create form, debtor selected | the list payload already carries the badge; facts need one `GET /debtors/:id` |
| No history | `value: null`, `"No history yet"`, `category: "no_history"`, facts present (zeros, or real promise counts when promises exist). **No number is ever sent** for this case (D-6) |

`note` is server-supplied so the PRD's required caption cannot be paraphrased away, and the label vocabulary is fixed — no "untrustworthy", no "bad debtor", anywhere in the API.

## 10.7 Performance

| Path | Cost |
| --- | --- |
| One profile | 3 aggregate queries, index-covered (`ix_ct_debtor`, `ix_pay_received`, `ix_dr_transaction`) |
| 50-debtor list | 3 aggregate queries total, grouped over `debtor_id = ANY(:ids)` |
| Dashboard | no scores (PRD does not require them) |

Sub-10 ms at MVP volumes. A `debtor_score_snapshots` table would only be warranted at hundreds of debtors per list — explicitly not now (ADR-13).

## 10.8 Tests the score must pass

| # | Case | Expected |
| --- | --- | --- |
| S-1 | No transactions | `no_history`, `value: null` |
| S-2 | One settled on time | `1.0/1.0/1.0` → 100 |
| S-3 | One settled 30 days late | `0`, `lateness 0`, `promise_rate 1` → 30 |
| S-4 | One settled 60 days late | `lateness` clamped at 0, never negative → 30 |
| S-5 | 3 kept, 1 missed | `promise_rate = 0.75` |
| S-6 | Disputed, unsettled, past due | excluded from counted |
| S-7 | Cancelled | excluded everywhere |
| S-8 | Unpaid, 10 days past due | counted, late, `days_late = 10` |
| S-9 | Unpaid, due today | not counted |
| S-10 | Unpaid, due tomorrow | not counted |
| S-11 | Raw 82.5 | `83` (half-up, not banker's) |
| S-12 | Superseded promise | excluded from numerator and denominator |
| S-13 | Two businesses sharing a debtor email | each score covers only its own transactions |
| S-14 | Promise kept by two part-payments | `kept` |
| S-15 | Payment on the promised date itself | counts as kept (inclusive window) |

---

# 11. Security and Reliability

## 11.1 Authentication (existing, reused)

| Aspect | Current behaviour | Change in this design |
| --- | --- | --- |
| Token | HS256 JWT, `sub` = `businesses.id`, `exp` = 30 min | none |
| Verification | `verify_access_token` → `get_current_business` → DB lookup | none |
| Password hashing | argon2id via `argon2-cffi` | none |
| Error shape | `HTTPException(detail=...)` | normalised into the PRD envelope by one handler |

**Gaps to close (small but real):**

1. **`exp` has no leeway, no `iat`, no `jti`.** Acceptable for MVP: a stolen token lives ≤30 min and there is no revocation list. Not worth building now.
2. **`jwt.decode` passes `algorithms=[settings.jwt_algorithm]`** — correct. Do **not** relax it to "whatever the token advertises" (the `alg: none` class of attack).
3. **`ph.verify` can raise `VerificationError`, not only `VerifyMismatchError`.** A corrupt stored hash should be a 401, not a 500 — catch both in the login route, without swallowing other exceptions.
4. **`/auth/login` is unrate-limited.** Credential stuffing is the realistic attack on this system; add the limiter from §11.5 (10/min per IP).

## 11.2 Authorisation: business-level isolation

**The rule: every creditor query is scoped by `business_id` from the JWT, as the first predicate. No request may supply a business id.**

```python
# The only sanctioned loader pattern
def get_scoped(self, business_id: UUID, tx_id: UUID, *, for_update=False) -> CreditTransaction:
    stmt = select(CreditTransaction).where(
        CreditTransaction.id == tx_id,
        CreditTransaction.business_id == business_id,     # ← the tenant key, always
    )
    if for_update:
        stmt = stmt.with_for_update()
    tx = self.session.execute(stmt).scalar_one_or_none()
    if tx is None:
        raise NotFound("Transaction not found")           # 404, never 403
    return tx
```

**Cross-tenant objects are `404`, not `403`.** A `403` on another business's transaction id confirms the id exists — an enumeration oracle. `404` makes "not yours" indistinguishable from "not there". Same for debtor ids and receipt payment ids.

| Endpoint family | Scoping mechanism |
| --- | --- |
| `/business`, `/capacity`, `/dashboard/*` | JWT business only; no other entity can be named |
| `/debtors/*` | `business_id = business.id` in every statement |
| `/transactions/*` | `business_id = business.id`; any `debtor_id` validated to belong to the business before use |
| `/public/tx/:token/*` | the token **is** the scope; it maps to exactly one transaction |
| `/webhooks/kora` | HMAC only; can touch only the payment its reference names |

**Checks that are easy to forget:**

- `POST /transactions` with `debtor_id`: the debtor must match `business.id`, else `404`. A valid debtor of another business must be unusable *and* indistinguishable from a nonexistent one.
- `GET /transactions/:id/payments/:pid/receipt`: assert `payment.transaction_id == tx.id` **and** `tx.business_id == business.id`. Checking only the first lets a caller read a payment from another transaction in the same business (harmless); checking only the second lets them read a foreign payment (harmful).
- `GET /debtors/:id`: transactions and payments filtered by `debtor_id` **and** `business_id` — defence in depth, since the debtor is already scoped.

## 11.3 Client-supplied values that must never be trusted

| Input | Treatment |
| --- | --- |
| `business_id` (anywhere) | ignored or rejected; always from JWT |
| `status`, `paid_kobo`, `outstanding_kobo`, `settled_at`, `receipt_number` | never accepted in a body; server-derived |
| `public_token` in a creditor body | not accepted; server-generated, read-only in responses |
| `amount_kobo` on pay | validated against the live balance |
| `override` | must carry a reason; capacity re-checked regardless |
| `format` | allow-list `html` or `pdf` |
| `page`/`limit` | clamped |
| `redirect_url`/`next` | does not exist as a client input |

## 11.4 Public token design

| Property | Choice | Rationale |
| --- | --- | --- |
| Generation | `secrets.token_urlsafe(32)` → 43 chars, 256 bits | Unguessable; URL-safe so no encoding bugs in email clients |
| Storage | plaintext, `UNIQUE` | Required by the "Copy pay link" feature (ADR-7, **approved in review — D-2**). A hash makes the link unrecoverable |
| Transport | **HTTPS only**; `APP_URL` must be an `https` origin outside local development | A bearer token in a URL over plain HTTP is a credential in clear text on every hop, proxy and browser history entry (§13.3 refuses to boot otherwise) |
| Entropy | CSPRNG (`secrets.token_urlsafe`), 256 bits | Guessability must not depend on length alone; `secrets` is the only generator used |
| Exposure | only in `pay_link` for the owning creditor, and the URL the debtor holds | Never in lists, never in `GET /transactions`, never in logs |
| Lifetime | the transaction's lifetime; no expiry | Emails link to it weeks later; expiring links would break the product |
| Rotation | none in MVP — **documented future improvement** | The obvious next security feature: `POST /transactions/:id/rotate-token` invalidates old emails. Deliberately not built now (no PRD endpoint, and it breaks every previously sent link) |
| Revocation | none in MVP — **documented future improvement** | Today, revoking access means cancelling the transaction (which stops payment but keeps read access) or deleting the row. A per-token `revoked_at` is the post-MVP design |
| Scope | exactly one transaction: read + the four allowed actions | Cannot list, cannot search, cannot reach a sibling |
| Headers | `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, `X-Robots-Tag: noindex` | PRD requires the first; the second stops a shared phone's back button showing a stale balance; the third stops indexing |
| Logging | path redacted for `/public/tx/*` | **A token in a log is a leaked credential** |

**Logging rule, concretely:** middleware rewrites `/public/tx/<token>/…` to `/public/tx/{token}/…` before the log line is emitted, and the redactor strips `public_token`/`pay_link`/`token` keys from any structured payload. Without it, a platform log drain stores live credentials for every debtor.

**The complete D-2 safeguard set, in one place** — every item is implemented, not aspirational:

| Safeguard | Where |
| --- | --- |
| Token generated with `secrets.token_urlsafe(32)` | `CreditTransactionService.create` |
| HTTPS enforced for public links | `APP_URL` startup check (§13.3) |
| Never exposed in application logs | path-rewrite middleware + key redactor (§11.5, §11.10) |
| `Cache-Control: no-store` on sensitive debtor responses | response middleware for `/public/*` and receipt routes |
| `Referrer-Policy: no-referrer` | same middleware (also PRD-mandated) |
| A token grants access to **its own transaction only** | `PublicTransaction` dependency scopes every query by `public_token`; a `:ref` or `:receipt_number` from another transaction is `404`, never a filtered list (§6.7.4) |
| Not serialised in creditor lists | `TransactionSummary` has no token field; only `GET /transactions/:id` returns `pay_link` (§6.5.3) |
| Rotation/revocation | documented above as future improvements, with the reason they are not in the MVP |

## 11.5 Rate limiting

| Route | Limit | Key | Reason |
| --- | --- | --- | --- |
| `POST /auth/login` | 10/min | IP | Credential stuffing |
| `POST /auth/register` | 5/min | IP | Abuse |
| `GET /public/tx/:token` | 60/min | token + IP | Result page and refreshes |
| `GET /public/tx/:token/payments/:ref` | 60/min | token | 3 s polling = 20/min per open page |
| `POST /public/tx/:token/pay` | 5/min | token | Charge spam |
| `POST /public/tx/:token/promise` | 10/min | token | |
| `POST /public/tx/:token/dispute` | 5/min | token | |
| `GET /public/tx/:token/receipts/*` | 30/min | IP | |
| `POST /transactions/:id/remind` | 1/hour | transaction | PRD rule, enforced in the service (§6.5.4), not by the limiter |

**Implementation [REC]:** `slowapi` over `limits`, in-memory storage for the MVP.

- **Trade-off stated plainly:** with `--workers 2` the effective limit is 2× configured, because counters live in each worker. For MVP-scale abuse protection that is fine; Redis would buy exactness at the cost of an infrastructure dependency nobody will exercise on demo day.
- **Upgrade path:** point `limits` storage at Redis (one URI); decorators unchanged.
- **Correctness requirement:** public limits are keyed by **token** where one exists, so an office behind one NAT is not throttled into silence — especially on the polling route, where an IP-keyed limit would break paying for a whole building.

## 11.6 Webhook security

| Control | Implementation |
| --- | --- |
| Signature | HMAC-SHA256 over `data` only; `hmac.compare_digest` (§8.5) |
| Replay | `UNIQUE(kora_reference, event)`; a replay is a no-op returning 200 |
| Forgery | unsigned/wrongly signed bodies change nothing and are recorded |
| Amount forgery | the body is never trusted for amounts; verify is called (§8.4) |
| Cross-tenant | the reference maps to exactly one payment; a webhook cannot name a business |
| Downtime | non-2xx triggers Kora retries for 72 h; reconciliation covers total loss |
| Secret | `KORA_SECRET_KEY` server-side only; never in the frontend, a response, or a log |

**No IP allow-list:** Kora's egress ranges are not documented as stable, a signature is strictly stronger, and an allow-list would be one more demo-day failure mode.

## 11.7 Input validation and injection

| Concern | Control |
| --- | --- |
| SQL injection | SQLAlchemy with bound parameters everywhere; the only `text()` statements are the claim query and migrations, both parameterised |
| Body shape | Pydantic v2 with `extra="forbid"` on writes |
| Oversized bodies | proxy limit (1 MB) + `max_length` on every string field |
| Enum smuggling | `Literal`/`StrEnum`; an unknown `status` query value is 422, not a silent no-op |
| Path traversal | `:id` parsed as `UUID`; `:receipt_number` matched against `^RCT-\d{6,}$`; no filesystem path is built from input |
| Open redirect | `redirect_url` comes from `settings.app_url`; no client `next`/`redirect` parameter exists |
| XSS in receipts/emails | Jinja2 autoescape **on** for receipts; email placeholders HTML-escaped before substitution. A debtor named `<script>` must not become markup |
| Header injection | `to`/`cc`/`reply_to` are `EmailStr`; subjects have `\r\n` stripped from every substituted value |
| Kobo/naira confusion | `amount_kobo` is strict `int`; `150000.0` is rejected, not silently truncated |
| Phone/email normalisation | one normaliser used by both debtor-creation paths |

## 11.8 Error handling

```python
@app.exception_handler(AppError)                 # domain errors → code/message/fields
@app.exception_handler(RequestValidationError)   # → 422 VALIDATION_ERROR + fields
@app.exception_handler(StarletteHTTPException)   # legacy HTTPException → envelope
@app.exception_handler(Exception)                # → 500 INTERNAL_ERROR, logged with request_id
```

**An error response must never contain:** stack traces, SQL, table or column names, provider raw responses, tokens, `str(exc)` from an unexpected exception, or evidence that another business's id exists.

**Correlation [REC]:** every request gets a `request_id` (from a header if provided, else generated), included in the log line and in a 500's `error.request_id`, so a demo-day failure is one grep away.

## 11.9 Audit logging — three trails, deliberately (D-9 / C-C)

The review asked for business-level traceability without polluting a transaction's timeline. There are now three distinct trails, each with one job:

| Trail | Where | Contents | Who reads it |
| --- | --- | --- | --- |
| **Transaction timeline** | `transaction_events` (durable, user-visible, append-only) | every material change **to a transaction**: created, reminder sent, acknowledged, promise, payment, dispute, note, settled, cancelled | creditor (UI), score engine, support |
| **Business activity** | structured log lines in a reserved `audit` namespace, plus `businesses.updated_at` | business-level changes that are **not** about one debt: `business.credit_limit_changed`, and future equivalents (business profile, payout details) | operators, support, incident review |
| **Operational log** | stdout, structured JSON | request id, route, status, duration, `business_id`, error code. **No** tokens, secrets, or full bodies | engineers |

### 11.9.1 Why business changes are not `transaction_events`

`transaction_events` is keyed by `transaction_id` and rendered as *one debt's story*. A credit-limit change belongs to the business, not to any invoice. Writing it as a transaction event would either need a nullable `transaction_id` (weakening the one NOT NULL that makes the timeline meaningful) or a synthetic transaction row. Both are worse than the problem. It would also silently enter the score's and the timeline's input set, which is exactly the kind of quiet coupling that produces "why does this invoice show a limit change" tickets.

### 11.9.2 What the MVP actually records, and what that buys

There is **no business-activity table** in the existing schema and none is added (deferred — `business_activities` is the right shape later: `id, business_id, type, actor, data, created_at`). Instead, every business-level mutation emits exactly one structured audit line:

```json
{"level":"INFO","audit":"business.credit_limit_changed","business_id":"…",
 "actor":"business:…","old_credit_limit_kobo":null,"new_credit_limit_kobo":500000000,
 "request_id":"…","at":"2026-11-17T10:12:03Z"}
```

| Property | How it is achieved |
| --- | --- |
| Traceable *that* it changed | `businesses.updated_at` is written on every update |
| Traceable *what* changed | old and new values are both in the line |
| Traceable *who* changed it | `actor` = the JWT's business id — the only identity that exists (D-1) |
| Traceable *which request* | `request_id`, the same one in the response and the request log |
| Durable | platform log drain retention (typically ≥ 30 days); `business_id` is indexed for search by the log platform, not by Postgres |
| Cannot be forged by a client | `old_credit_limit_kobo` is read inside the same transaction as the update |

**What it cannot do, stated plainly:** it is not queryable in SQL, it has no API or UI, and its retention is the log provider's, not ours. That is an acceptable MVP trade — the PRD requests no activity feed, no screen reads it, and adding a table plus a feed would be new product surface. The moment anyone needs "show me the history of this business's limit", the deferred table is the implementation, and the audit lines already written remain the backfill source.

**One rule that keeps the trails from lying to each other:** a change is recorded in exactly one of them. If it happened to a transaction, it is a `transaction_events` row; if it happened to the business, it is an audit line. No fact appears in both, and neither is used as a fallback for the other.

## 11.10 Secrets and configuration

| Rule | Enforcement |
| --- | --- |
| Secrets only in env / platform store | `Settings` reads env; `.env` gitignored; `.env.example` lists keys with empty values |
| No secret in a response, log or error | logging redactor strips configured keys; `Settings` is never printed |
| No secret in the frontend | Kora secret is server-side; no provider key is ever serialised |
| Rotation | rotating `KORA_SECRET_KEY`/`RESEND_API_KEY` needs only a restart |
| Separate keys per environment | `KORA_MODE` (`sandbox`\|`live`) must match the key's prefix in **every** environment; production + sandbox requires the fenced demo flag (§13.3, D-10) |

That last guard prevents two opposite failures: a demo that silently charges nobody because a test key leaked into production config, and — worse — **a live key used during a rehearsal without anyone noticing**. The mode is explicit, checked at boot, and stamped onto every payment (`payments.provider_mode`), so "was this real money?" is answerable from the database rather than from memory.

## 11.11 Concurrency and race conditions — the catalogue

| Race | Consequence without a control | Control |
| --- | --- | --- |
| Two creates both pass capacity | business over its limit | business row `FOR UPDATE` |
| Two pay clicks | two Kora charges | attempt-allocation lock + `Idempotency-Key` |
| Two webhooks, one payment | balance reduced twice | payment lock + `successful` guard + event dedupe |
| Two genuine full payments (two devices) | undefined balance, lost money, or two "settled" emails | transaction-row lock, verified-sum recompute, `settled_now` gating, `review_reason='overpaid'` (§5.7.5, §8.9.3) |
| Same `Idempotency-Key`, different amount | the wrong amount charged | amount comparison on replay → `409 IDEMPOTENCY_KEY_REUSED` (§6.7.3) |
| Two promises concurrently | two open promises, corrupted `promise_rate` | transaction lock + partial unique index |
| Promise made while a reminder sends | one "unwarranted" email | tick re-reads transaction + open promise immediately before sending. A promise landing in the same instant can still race — accepted: an email sent 1 s before a promise is not false |
| Dispute during payment application | status overwritten | both take the transaction lock; the writer recomputes from payments |
| Settle while a reminder is claimed | email to a just-settled debtor | pre-check reads fresh status; a settle between check and send can produce one stray email. Not a money bug, and the event records it |
| Resolve dispute twice | duplicate reminder rows | `resolved_at` under lock → 409, or idempotent 200 for the same note |
| Sequence collision | duplicate reference | `UNIQUE(reference)` + one retry |

**The pattern throughout: lock the row that owns the invariant, re-read inside the lock, write, commit.** Nothing depends on timing.

## 11.12 Availability and degradation

| Dependency down | Behaviour |
| --- | --- |
| Kora API | Pay returns `502 PAYMENT_INIT_FAILED`; balances and reminders unaffected |
| Kora webhooks | payments stay `pending`; reconciliation catches up; result page says "Confirming…" |
| Resend | reminders recorded `failed`; the transaction still exists; the creditor can resend |
| Database | everything 5xx; webhooks return 500 so Kora retries for 72 h — the correct answer |
| Worker | reminders stop but are not lost; settle/dispute state is already correct because API paths write it |
| Redis (unused) | n/a |

**No database transaction is ever held open across a call to Kora or Resend.** That single rule keeps a slow provider from exhausting the connection pool during the demo.

---

# 12. Testing Strategy

## 12.1 Principles

1. **Test against PostgreSQL, never SQLite.** This schema depends on native enums, `TIMESTAMPTZ`, `jsonb`, partial unique indexes, `FOR UPDATE SKIP LOCKED` and `AT TIME ZONE`. A SQLite suite would pass while the production schema failed. **[REC]**
2. **Test the rules, not the routes.** The demo's risk is a wrong balance or a double email, not a wrong status code — so services and the pure functions carry the test weight, with API tests proving wiring and authorisation.
3. **Every bug found during the build becomes a test.** No exceptions on a three-day clock.
4. **Time and money are frozen, not approximated.** `time-machine` for clocks, `Decimal`/int for money; a test may never depend on the wall clock.
5. **No network in tests.** Kora and Resend are replaced by fakes at the module boundary (`respx` for HTTP, or a stub client object); the signature helper is tested with real HMAC computations.

## 12.2 Test stack and layout

| Tool | Role |
| --- | --- |
| `pytest` | runner |
| `pytest-cov` | coverage gate on `app/modules`, `app/core` (target ≥85% on services/pure functions; no gate on routes) |
| `pytest-postgresql` or a docker-compose Postgres + `DATABASE_URL` env | real database |
| `httpx` + `TestClient` | API tests |
| `respx` | mock Kora/Resend HTTP |
| `time-machine` | freeze/advance time |
| `faker` | data, with a fixed seed for reproducibility |

```
app/tests/
├── conftest.py            # engine, session, client, factories, frozen WAT clock
├── factories.py           # business/debtor/transaction/payment/promise builders
├── unit/                  # money, time, signature, template selection, score math, text rendering
├── api/                   # status codes, envelopes, validation, authz matrix
├── integration/           # services + DB + concurrency + jobs
└── e2e/                   # the PRD demo story, once, start to finish
```

**Database isolation:** one schema per test session; each test runs inside a transaction that is rolled back, except concurrency tests, which need two real sessions and must clean up by truncation.

## 12.3 Unit tests (fast, no DB)

| Area | Cases |
| --- | --- |
| `core/money.py` | kobo↔naira round-trips for 1, 99, 100, 15 000 000, 500 000 000; `naira_to_kobo("2000.00") == 200_000`; `naira_to_kobo("150.99") == 15099` (**not** 15098); `format_naira(15000000) == "₦150,000.00"`; no `float` anywhere (a grep test scans `app/` for `float(` near amount identifiers) |
| `core/time.py` | 23:30 UTC = next day in WAT; `at_9am_wat(2026-11-27) == 2026-11-27T08:00Z`; `today_wat` around month/year boundaries |
| `kora/signature.py` | a known body + secret produces the expected hex; wrong secret rejected; unicode body; compact vs spaced JSON; `raw_data_slice` extracts exactly the `data` object including nested braces |
| `reminders/templates.py` | `pending_ack` → new_credit; due−1 → upcoming; due day → due_today; +1..+6 → overdue_1; +7 → overdue_followup; manual uses the same rules |
| `transactions/balance.py` | `display_status` precedence for all 6 stored statuses × (overdue/not) × (balance 0/>0); `outstanding` clamps at 0 |
| `transactions/events.render_text` | one test per event type asserting the exact PRD §8.7 wording and naira formatting |
| `scoring/service.compute` | S-1…S-15 from §10.8, as pure-function tests with fact dictionaries |
| `promises/service.evaluate` | kept by one payment; kept by two part-payments; missed after window; inclusive promised_date; superseded ignored |

## 12.4 API tests (contract + authz)

| Group | Cases |
| --- | --- |
| Error envelope | 401/404/409/422/429 all return `{"error":{code,message,fields}}`; legacy `/auth/login` failure also returns the envelope |
| Validation | negative/zero `amount_kobo`; `due_date < issue_date`; `issue_date` in the future (WAT); `override=true` without reason; `debtor_id` + `new_debtor` together; body with an unknown field (`extra="forbid"`) |
| Pagination | default 20; `limit=500` clamped to 100; `page=0` clamped to 1; `meta.total` matches filtered count |
| Money types | `amount_kobo: 150000.0` is rejected; `"150000"` is accepted or rejected consistently (document the choice) |
| Public routes | valid token 200; unknown token 404; wrong-case token 404; token of another transaction's receipt 404 |
| Headers | `/public/*` responses carry `Referrer-Policy: no-referrer` and `Cache-Control: no-store` |
| Receipts | `format=pdf` when disabled → 400; `format=csv` → 400; successful payment → HTML containing the receipt number and SETTLED stamp only when balance is 0 |

## 12.5 Database tests

| Case | Assertion |
| --- | --- |
| Migrations | `upgrade head` then `downgrade base` then `upgrade head` on an empty DB |
| Constraints | duplicate `(business_id, lower(email))` raises; duplicate `kora_reference` raises; two open promises raise; `status='successful'` without `verified_at` raises; `override=true` with blank reason raises |
| Enums | inserting `status='overdue'` fails (there is no such stored value) |
| FKs | deleting a business/debtor with transactions fails (RESTRICT) |
| Sequences | 3 sequential creates yield `CRD-000001..000003`; a failed insert leaves a gap (documented, accepted) |
| Partial indexes | after settling a transaction, it disappears from the `ix_ct_open_by_business` predicate (`EXPLAIN` shows the index used) — a sanity test, not a perf test |

## 12.6 Authorisation tests (the matrix that matters)

Two businesses, each with a debtor, a transaction, a payment and a receipt. Then, for **every** `/:id` route, authenticated as business A, request business B's id and assert `404` (never 200, never 403).

| Test | Assertion |
| --- | --- |
| A lists transactions | B's rows absent |
| A GETs B's transaction | 404 |
| A PATCHes B's debtor | 404 |
| A PATCHes B's credit limit | B's limit unchanged |
| A GETs B's receipt | 404 |
| A creates a transaction with B's `debtor_id` | 404 |
| A resolves a dispute on B's transaction | 404, B's state unchanged |
| A's dashboard totals | exclude B's money entirely |
| A's debtor list `?q=` | cannot match B's debtors |
| Same email in two businesses | both create successfully (proves per-business uniqueness) |

## 12.7 Capacity tests

| Case | Expected |
| --- | --- |
| No limit set | `business_ok: true`, `available: null`, never blocks |
| Exactly at limit | allowed (inclusive) |
| 1 kobo over | `requires_override: true`, create → `422 CAPACITY_EXCEEDED` |
| Over with `override=true` + reason | created; `capacity_override=true`; reason stored; event present |
| Debtor block only | debtor over, business fine → override required |
| `debtor_limit_kobo` for a new debtor | debtor outstanding treated as 0 |
| Disputed debt included | outstanding counts it (PRD §7.1) |
| Settled/cancelled excluded | outstanding excludes them |
| **Two concurrent creates** (two sessions/threads, same business) | exactly one succeeds when the pair exceeds the limit; the other gets 422 |

## 12.8 Repayment score tests

The S-1…S-15 table in §10.8, plus:

- the same debtor under two businesses yields two independent scores;
- `GET /debtors` produces identical `score.value` to `GET /debtors/:id` for the same debtor (guards against the batched path diverging from the single path — the most likely scoring bug);
- a debtor with no history returns `value: null` and the label "No history yet" (and the frontend gets no number to render).

## 12.9 Promise outcome tests

| Case | Expected |
| --- | --- |
| Promise → payment within window | `kept`, event, promise absent from `open_promise` |
| Promise → no payment → daily job after date | `missed`, event |
| Second promise while one is open | first `superseded`, second `open`, exactly one open |
| Identical retry within 5 min | `200`, still one promise |
| Promise → reminders moved | next `scheduled_for` is 9:00 WAT the day after `promised_date` |
| Promise missed → reminder resumes | next tick sends the moved reminder |
| Promise amount > balance | 422 |
| Promise date > 60 days | 422 |
| Promise date in the past | 422 |

## 12.10 Reminder scheduling tests

| Case | Expected |
| --- | --- |
| Create with due = today + 10 | 5 rows: new_credit(now) + upcoming/due_today/overdue_1/overdue_followup at 9:00 WAT |
| Create with due = today − 20 | only `new_credit` + one `overdue_followup` at the next 9:00 WAT |
| Create with due = today + 2 | `upcoming` skipped (past), `due_today` and later present |
| Tick with settled transaction | `skipped`, reason `settled`, no email |
| Tick with disputed transaction | `skipped`, reason `disputed`, no email |
| Tick with open future promise | not sent; `scheduled_for` moved to promised_date + 1 at 9:00 WAT |
| Tick sends `overdue_followup` | a new `overdue_followup` row exists at +7 days |
| Two ticks run concurrently | each reminder sent exactly once (assert `sent` count and email-call count) |
| Manual remind twice within an hour | second is 429; only one email |
| Manual remind on disputed/settled/cancelled | 409 |
| Diagonal: 15:00 UTC tick vs 9:00 WAT | the 08:00Z instant is respected exactly |

**Email counting is the real assertion:** every test asserts the number of `EmailService.send` calls, because "a reminder went out twice" is the failure the PRD's duplicate-prevention rules exist to stop.

### 12.10.1 Already-overdue transactions (C-A)

The correction is only worth anything if all five entry points are asserted, so these are table-driven from `next_overdue_slot()`:

| # | Case | Expected `scheduled_for` |
| --- | --- | --- |
| R-1 | Created 10 days overdue, at 08:00 WAT | 09:00 WAT **tomorrow**, exactly one `overdue_followup` row |
| R-2 | Created 10 days overdue, at 23:30 WAT | same instant as R-1's *tomorrow* (i.e. the day after the 23:30 creation date) |
| R-3 | Created 2 days overdue (past `upcoming`/`due_today`/`overdue_1`, before `overdue_followup`) | `overdue_followup` at tomorrow 09:00, not at `due_date + 7` |
| R-4 | Created due-tomorrow (not overdue) | `upcoming` at `due_date − 3` skipped as past; `due_today` / `overdue_*` as computed — **no** C-A row |
| R-5 | Dispute raised then resolved on an overdue transaction | one `overdue_followup` at tomorrow 09:00; the pre-dispute scheduled rows are `cancelled` |
| R-6 | Resolve twice (double-click) | still exactly one `overdue_followup` (idempotent `existing_kinds`) |
| R-7 | Promise made on an overdue transaction, promised date = today | row moves to 09:00 WAT tomorrow, not earlier, not into the past |
| R-8 | Promise missed, worker was down for 2 days | row sends on the first tick after recovery (`scheduled_for <= now`), never lost |
| R-9 | Disputed transaction with a leftover `scheduled` row | tick skips it with `skip_reason='disputed'`; no email |
| R-10 | DST-free assumption check | 09:00 WAT is `08:00Z` year-round (Africa/Lagos has no DST); asserted in one test so a tz-database change cannot silently shift every reminder |

## 12.11 Payment concurrency tests

| Case | Expected |
| --- | --- |
| Two threads apply the same payment | one `successful` row, one `payment_received` event, balance reduced once |
| Two different payments both succeed | both recorded, balance reduced by both, status `settled`, one `settled` event |
| Two concurrent promise creations | one `open`, one `superseded` (or a clean 409), never two `open` |
| Payment applied while a dispute is raised | transaction lock orders them; final status matches §8.6.1 |
| Capacity race (see §12.7) | one success, one 422 |
| Two successful full payments, second applied after the first commits | both `successful`; balance 0; exactly **one** `settled` event, **one** reminder cancellation, **one** email #7; second payment has `overpaid_kobo` and `review_reason='overpaid'` |
| Second payment commits first (inverted order) | identical outcome — the flags land on whichever payment ran second, and the ledger totals are order-independent |
| Same payment applied twice sequentially | one `successful` row, one `payment_received`, one receipt number |
| Whole transaction rolled back mid-apply (injected error) | no `successful` row, no event, no balance change — the money mutation is atomic with its evidence |
| Concurrent dispute-resolve + payment | one wins the transaction lock; final status matches §8.6.1; no orphan `settled_at` |

Concurrency tests use two real connections with explicit `BEGIN`/`COMMIT`, and are skipped (not silently passed) if the test database is unavailable — a skipped test is visible, a fake pass is not.

## 12.12 Kora webhook tests

| Case | Expected |
| --- | --- |
| Valid signature + `charge.success` + matching amount | payment `successful`, receipt assigned, balance updated, event, one email |
| Invalid signature | 401, no state change, `kora_webhook_events.signature_ok=false` recorded |
| Missing signature header | 401 |
| Duplicate delivery (same reference+event) | 200, no second event, no second email |
| Different event for an already-successful payment | 200, no change |
| Unknown reference | 200, `outcome='ignored'` |
| Verify says `status: false` / `data.status: "failed"` | payment `failed`, `payment_failed` event, balance unchanged |
| Verify amount ≠ expected (under and over) | `failed` with `amount_mismatch`, balance unchanged |
| Verify currency ≠ NGN | `failed`, balance unchanged |
| Verify returns naira **string** `"100000.00"` | parsed as 10 000 000 kobo and matched |
| Webhook body with `150.0` (single decimal) | signature verified via raw-slice path; applied |
| Kora API timeout during verify | payment stays `pending`; webhook returns 500 so Kora retries; reconciliation then applies |
| Malformed JSON | 400, recorded, no crash |
| Webhook for a `cancelled` transaction | recorded `successful`; status stays `cancelled`; `review_reason='paid_cancelled_transaction'`; `settled_at` stays NULL; receipt exists; no settled email; no reminders rebuilt |

## 12.13 Idempotency tests (beyond webhooks)

| Case | Expected |
| --- | --- |
| `POST /acknowledge` twice | 200 both times; exactly one `debtor_acknowledged` event |
| `POST /pay` twice with the same `Idempotency-Key` | one `payments` row; same `checkout_url`; one Kora initialize call |
| `POST /pay` twice without a key | two attempts (`-P1`, `-P2`), both valid |
| `POST /promise` identical twice | one open promise |
| `POST /dispute` twice | one open dispute; second is 409 or an idempotent 200 with identical payload |
| `POST /cancel` twice | 200; one `cancelled` event |
| `resolve-dispute` twice | second is 409; one `dispute_resolved` event and one rebuild |
| `POST /pay` same key, **different** amount | `409 IDEMPOTENCY_KEY_REUSED`; no second row; no Kora call |
| `POST /pay` same key after the attempt succeeded | `200` with the stored result; no second row; one Kora call total |
| `POST /pay` same key after the attempt failed | `409 IDEMPOTENCY_KEY_REUSED`; a fresh key allocates `-P{n+1}` |
| Two `POST /pay` with the same *new* key, concurrent | exactly one row and one Kora call (the unique index decides); the loser receives the winner's checkout URL |

## 12.14 The demo-story end-to-end test (the acceptance gate)

One test, run against a real DB with mocked Kora/Resend, asserting the PRD §2 story exactly:

```
1. business created, credit_limit_kobo = null
2. PATCH /business/credit-limit → 500_000_000
3. GET /capacity?amount_kobo=15_000_000 → business_ok true
4. POST /transactions (Bright Foods, 15_000_000, due today+10)
   → 201, reference matches CRD-\d{6,}, pay_link present, 5 reminders
   → email 1 sent exactly once
5. GET /public/tx/{token} → 200, no internal notes, no public_token echo
6. POST /public/tx/{token}/acknowledge → active; second call → still active, 1 event
7. POST /public/tx/{token}/promise (10_000_000, date today+3) → open, reminders moved
8. POST /public/tx/{token}/pay (10_000_000) → 201, checkout_url, reference P1
9. webhook charge.success (valid signature) + verify success/10 000 000
   → balance 5_000_000, display_status partially_paid
   → receipt RCT-000001, email 6 sent once, email 7 NOT sent
   → promise kept, promise_kept event
   → timeline contains: created, acknowledged, promise_made, payment_received, promise_kept
10. debtor score changed from its pre-payment value (assert the specific numbers)
11. repeat steps 8–9 for the remaining 5_000_000
   → settled, settled_at set, reminders cancelled, email 7 sent once, email 6 NOT sent
12. GET /public/tx/{token} → settled read-only page, receipt links present
```

This single test is **the definition of done for the backend**. If it passes on the deployed URLs with the real Kora sandbox (steps 9 and 11 un-mocked), the MVP is demonstrable.

## 12.15 Edge cases that must pass before the MVP is "complete"

| # | Edge case | Why it matters |
| --- | --- | --- |
| E-1 | Two concurrent creates at the limit | Silent credit over-extension |
| E-2 | Duplicate webhook | Double-counted money |
| E-3 | Webhook whose reference is unknown | Crash or phantom payment |
| E-4 | Payment on a disputed transaction, balance > 0 | Status must stay disputed (PRD's oddest rule) |
| E-5 | Payment on a disputed transaction that settles it | Must become settled + reminders stopped |
| E-6 | Overpayment from two successful charges | Balance clamped, flag raised, no double settled email |
| E-7 | Promise kept by two part-payments | Wrong `promise_rate` otherwise |
| E-8 | Promise exactly on promised_date | Inclusive window |
| E-9 | Resolve dispute when balance is already 0 | Must settle, not reactivate |
| E-10 | Manual reminder inside the cooldown | 429, no second email |
| E-11 | Reminder for a transaction that settles mid-tick | No email to a settled debtor |
| E-12 | Business with no credit limit | Never blocks (PRD: "Never blocks") |
| E-13 | Inline debtor create with a duplicate email | 409 with `existing_debtor` |
| E-14 | Cross-business access on every route | 404 everywhere |
| E-15 | Receipt re-opened after a later payment | Shows current balance/SETTLED per ADR-12 |
| E-16 | Public token in the access log | Redacted |
| E-17 | `issue_date` submitted as "today" at 00:15 WAT | Accepted (WAT, not UTC) |
| E-18 | Tokenised link opened by a scanner | Acknowledge comes from JS, so no false acknowledgement from the server GET |
| E-19 | Cancelled transaction with a successful payment | Money recorded, status stays cancelled, no crash |
| E-20 | Score for a debtor with 1 old settled transaction | Numeric, not `no_history` |

---

The following were added by this revision and must pass before the MVP is called complete:

| # | Edge case | Decision it proves |
| --- | --- | --- |
| E-21 | Verified payment overpays a settled transaction | D-3/D-11: both payments `successful`, one `settled` event, flag set, no lost money |
| E-22 | Verified payment on a `cancelled` transaction | D-3: recorded, still cancelled, flagged, receipt issued |
| E-23 | Transaction created already overdue | C-A: one reminder at 09:00 WAT tomorrow |
| E-24 | Debtor with promises but zero counted transactions | D-6: `No history yet`, no number, promise facts visible |
| E-25 | Kora verify returns `"1000.45"` | D-11: exactly `100045` kobo credited; no float artefact |
| E-26 | Credit-limit change | D-9: no `transaction_events` row; one audit line with old/new/actor/request id |
| E-27 | `DEMO_MODE=false` + sandbox key + `ENVIRONMENT=production` | D-10: refuses to boot |
| E-28 | `DEMO_MODE=true` + live key | D-10: refuses to boot |
| E-29 | Same `Idempotency-Key`, different amount | D-4: `409`, nothing charged |

# 13. Deployment and Environment Configuration

## 13.1 Processes and topology

| Service | Kind | Command | Notes |
| --- | --- | --- | --- |
| `web` | HTTP | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2` | 2 workers is plenty; more makes in-memory rate limits looser (§11.5) |
| `worker` | none | `python -m app.worker` | No port. Must not be scaled to >1 without reading §9.2 (it is safe, but pointless) |
| `release` | one-shot | `alembic upgrade head` | Runs before `web` starts on each deploy |

Anything with managed Postgres works: Render, Railway, Fly.io, Heroku, ECS. No Redis, no object storage, no CDN requirement (receipt HTML is generated per request).

**`Dockerfile` shape** (if the host needs it):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info \
 && rm -rf /var/lib/apt/lists/*        # WeasyPrint deps only if PDF is enabled
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## 13.2 Environment variables

```bash
# --- existing ---
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/credence
JWT_SECRET_KEY=...
JWT_TOKEN_EXPIRY_MINUTES=30
JWT_ALGORITHM=HS256

# --- app ---
ENVIRONMENT=development            # development | staging | production
APP_URL=https://api.credence.ng    # used to build pay_link and Kora redirect URLs
CORS_ORIGINS=["https://app.credence.ng"]   # JSON array; replaces the hardcoded LAN origins
LOG_LEVEL=INFO

# --- Kora ---
KORA_SECRET_KEY=sk_test_...
KORA_MODE=sandbox                   # sandbox | live — MUST match the key prefix (checked at boot)
KORA_BASE_URL=https://api.korapay.com/merchant/api/v1
KORA_TIMEOUT_SECONDS=10

# --- Email ---
RESEND_API_KEY=re_...
EMAIL_FROM="Credence <no-reply@credence.ng>"
EMAIL_REPLY_TO_FALLBACK=ops@credence.ng    # used when a business has no reply-to address

# --- behaviour switches ---
RECEIPT_PDF_ENABLED=true
PUBLIC_RATE_LIMIT_PER_MINUTE=60
PAY_RATE_LIMIT_PER_MINUTE=5
MANUAL_REMINDER_COOLDOWN_MINUTES=60
DEMO_MODE=false                     # D-10: the ONLY way to run sandbox Kora under ENVIRONMENT=production

# --- dev only ---
INTERNAL_JOB_TOKEN=                # when set, enables POST /internal/jobs/reminders
SENTRY_DSN=                        # optional
```

**Two config changes required by the existing code:**

1. `CORS_ORIGINS` must replace the hardcoded `["http://localhost:5173", "http://192.168.1.105:5173"]` in `app/main.py`. A LAN IP in production CORS is worse than useless — it silently blocks the real frontend.
2. `DATABASE_URL` must use the `postgresql+psycopg://` scheme (psycopg 3 is in `requirements.txt`). A bare `postgresql://` will try psycopg2, which is not installed.

## 13.3 Startup checks (fail fast, not mid-demo)

`app/main.py` lifespan performs three checks and refuses to start on failure:

| # | Check | Failure message |
| --- | --- | --- |
| 1 | `DATABASE_URL` reachable (`SELECT 1`) | "Cannot reach database" |
| 2 | `APP_URL` is an absolute **https** origin when `ENVIRONMENT != development` | "APP_URL must be an https origin" — public tokens travel in those URLs (D-2) |
| 3 | `KORA_MODE` agrees with the key prefix (`sk_test_` ⇒ `sandbox`, `sk_live_` ⇒ `live`) | "KORA_MODE does not match the configured Kora key" |
| 4 | `ENVIRONMENT=production` + `KORA_MODE=sandbox` **and** `DEMO_MODE != true` | "Refusing to start: sandbox Kora in production requires DEMO_MODE=true" |
| 5 | `DEMO_MODE=true` + `KORA_MODE=live` | "Refusing to start: DEMO_MODE cannot be combined with a live Kora key" |

This is ~30 lines that prevent the four failures most likely to ruin the week: a dead DB URL, a plaintext pay link, a mode/key mismatch, and **test credentials silently surviving into real production processing**.

**How the demo-only exception (D-10) actually works.** The exception is not "test keys are allowed in production"; it is a single, explicit, self-contradicting-by-default flag:

| Property | Implementation |
| --- | --- |
| Off by default | `DEMO_MODE=false` in `Settings`, in `.env.example`, and in the production template. Nothing enables it implicitly |
| Cannot be enabled by accident | It only *permits* sandbox mode; it never selects it. Both `KORA_MODE=sandbox` and `DEMO_MODE=true` must be set, and the key must actually be a test key (check 3) |
| Cannot mask a live-key mistake | Check 5 refuses `DEMO_MODE=true` with a live key, so the flag can never be quietly repurposed into "anything goes" production mode |
| Visible at runtime | Startup logs one `WARNING` line naming the mode; every payment response and receipt carries `provider_mode`; the public page shows a test-payment banner |
| Auditable after the fact | `payments.provider_mode` is stamped per attempt, so a sandbox payment is distinguishable months later even if the deployment has since switched to live keys |
| Removable | Clearing `DEMO_MODE` (and switching the key) is the whole migration to real money — no code change |

## 13.4 Migrations in CI/CD

```
1. alembic upgrade head          # release step, before web/worker start
2. pytest -q                     # CI, against a throwaway Postgres
3. deploy web, then worker
```

- Migrations are **forward-only in production**. Rollback is a new forward migration, not `downgrade` (which exists and is tested, but is for development).
- Every migration is idempotent-safe on re-run where practical (`CREATE INDEX IF NOT EXISTS`), because a release step that dies halfway should be re-runnable.

## 13.5 Health and observability

| Endpoint | Purpose | Returns |
| --- | --- | --- |
| `GET /health` | exists today, liveness only | `{"status":"Working"}` |
| `GET /health/ready` **[REC]** | readiness: DB `SELECT 1` | `200` / `503` |

| Signal | Where |
| --- | --- |
| Request logs (JSON) | stdout → platform log drain |
| Payment failures, signature rejections | `WARNING`/`ERROR` with `kora_reference` and `request_id` |
| Reminder failures | `reminder_failed` event + log |
| Webhook volume | `kora_webhook_events` row count (a zero count during a demo means the webhook path is broken) |
| Uptime | platform ping on `/health/ready` |
| Errors (optional) | Sentry via `SENTRY_DSN`, with `business_id` and `request_id` tags, no secrets |

**Demo-day runbook (worth writing on a card):**

1. `curl $APP_URL/health/ready` → 200.
2. `python -m app.scripts.run_reminders_once --dry-run` → shows what would send.
3. Kora dashboard → webhook URL is the production one, mode is **sandbox**, and a test webhook was delivered today.
4. `SELECT count(*) FROM kora_webhook_events WHERE created_at > now() - interval '10 minutes';` after a test payment.
5. Resend dashboard → sending domain verified (SPF+DKIM) and a test email delivered.

## 13.6 Backup and recovery

| Item | MVP position |
| --- | --- |
| DB backups | Managed provider's daily snapshot (verify it is enabled on the chosen plan — free tiers sometimes are not) |
| Point-in-time recovery | Nice to have; not required at demo scale |
| Restore drill | Not performed; recorded as a known gap (R-10) |
| Seed | `python -m app.scripts.seed_demo` recreates the demo business from scratch, which is the practical recovery path for demo data |
| Secrets | Platform secret store; no copies in the repo, none in the workspace |

## 13.7 Environments

| Environment | DB | Kora | Email | `KORA_MODE` | `DEMO_MODE` | Purpose |
| --- | --- | --- | --- | --- | --- | --- |
| Local | local Postgres (docker) | sandbox | Resend test mode / logs | `sandbox` | `false` | development, migrations |
| Staging (optional) | second DB | sandbox | Resend with a real inbox | `sandbox` | `false` | Thursday rehearsal |
| Production (demo) | managed | sandbox **for the demo** | Resend verified domain | `sandbox` | **`true`** | the demo itself |
| Production (after the demo) | managed | live | Resend verified domain | `live` | `false` | real money |

The PRD is explicit that the demo runs on Kora's **sandbox** and says so on stage. That is a real-money exception, so v1's single permissive switch (`KORA_ALLOW_TEST_KEY_IN_PRODUCTION`) is replaced by the two-factor rule in §13.3: the mode must be declared *and* the key must match it *and* `DEMO_MODE` must be explicitly true, and `DEMO_MODE` cannot coexist with a live key.

**The distinction between sandbox and live is made visible three ways** (D-10): in configuration (`KORA_MODE`), on every payment and receipt (`provider_mode`), and in the UI (the public page's test-payment banner). A demo receipt that ends up in a screenshot is therefore self-labelling. Recording it at the payment level rather than only in config is what makes it trustworthy — config changes over time; the payment row does not.

**Switching to live money** is a config change plus a restart: `KORA_SECRET_KEY=sk_live_…`, `KORA_MODE=live`, `DEMO_MODE=false`. Check 3 fails the boot if the key and the mode disagree, so the switch cannot be half-done.

---

# 14. Architecture Decision Records

Each ADR states the decision, why, the alternatives, the trade-off, and whether it is needed for the MVP. **[R]** marks decisions needing your explicit sign-off.

### ADR-1: Modular monolith, two processes, one database
**Decision.** One codebase, one image, an `api` process and a `worker` process sharing PostgreSQL and configuration.
**Why.** The domain is one bounded context: a business, its debtors, its debts, its payments. Every candidate boundary crosses a transaction — applying a payment writes the payment, the transaction status, the promise outcome, reminders and the event. Splitting that would turn one ACID transaction into a distributed saga for zero user-visible benefit at MVP scale.
**Alternatives.** Microservices per domain (rejected: distributed transactions, five pipelines, 3-day clock); a single process with an in-process scheduler (rejected: a wedged email send stalls API latency, and one crash stops reminders).
**Trade-off.** The worker cannot scale independently; a bad deploy affects both. Acceptable — both are stateless containers on the same image.
**Necessary:** yes. **Revisit when** a second team owns another domain, or background volume needs independent scaling.

### ADR-2: APScheduler in a dedicated worker, no Celery/broker
**Decision.** `apscheduler` interval/cron triggers inside `python -m app.worker`; all job state in `reminders`.
**Why.** The jobs are "look at a table every 15 minutes". A broker adds a service to operate, a serialization boundary for every argument, and a new failure class (beat dead) for no capability this MVP uses. Durability comes from the table, not the queue.
**Alternatives.** Celery+Redis+beat (rejected: infrastructure for a feature that needs one index scan); platform cron hitting an endpoint (rejected: a public endpoint that sends email is a liability, and no misfire handling); `pg_cron` (rejected: not on every provider; a drop-in upgrade).
**Trade-off.** No built-in retry/visibility UI; two workers must cooperate via `SKIP LOCKED` (they do). In-table retries are slightly more code than `task.retry()`.
**Necessary:** yes — automated reminders are the product. **Escalate to Celery only if** jobs need fan-out, priorities, or multiple worker types.

### ADR-3 [R]: Balances, display status and score computed on read
**Decision.** No stored `outstanding`, `paid`, `overdue` flag or score. Every read recomputes from `payments` and `credit_transactions`.
**Why.** It removes the entire "the balance is wrong" class: duplicates, replays, overpayments and missed events all self-correct. It is also the PRD's explicit rule (§4).
**Alternatives.** A maintained `paid_kobo` column written in the same transaction (rejected: two writers, drift, backfill on every bug fix); event-sourced projection (rejected: over-engineering).
**Trade-off.** Every read pays for an aggregate join. Sub-millisecond at MVP volume; the partial index keeps it cheap as data grows.
**Necessary:** yes. **Revisit at** millions of payment rows.

### ADR-4 [R]: No generic repository layer
**Decision.** Services use `Session`/`select()` directly; only genuinely reused aggregate reads live in named `queries.py`/`balance.py` modules.
**Why.** A `BaseRepository[T]` forwards every call without hiding SQL or enabling a store swap (tests use Postgres anyway). The real duplication risk is *calculations* — outstanding, balance, score — which is exactly where the named modules sit.
**Alternatives.** Full repository + unit-of-work (rejected: ceremony); ActiveRecord (rejected: models would accumulate business rules, contradicting the service layer).
**Trade-off.** Query logic lives in services, so a service file can grow. Mitigated by extracting only hot shared aggregates.
**Necessary:** no — a simplification; adopting repositories later is mechanical.

### ADR-5 [R]: Sync SQLAlchemy and sync routes, with one async boundary
**Decision.** Keep `create_engine`/`SessionLocal`; DB routes are `def` (FastAPI's threadpool); only the webhook is `async` to read the raw body, delegating DB work to `run_in_threadpool`.
**Why.** The existing codebase is sync (psycopg 3, `Session`). Converting to `AsyncSession` touches every existing route and dependency for no MVP benefit while the database remains the bottleneck.
**Alternatives.** Fully async (rejected: churn plus a second mental model for no measured gain at this scale).
**Trade-off.** Thread-pool size bounds concurrency (default ~40), far above MVP need. The raw-body requirement is isolated to one route.
**Necessary:** yes, as a scoping decision.

### ADR-6 [R]: Capacity enforced by a business-row lock
**Decision.** `SELECT business FOR UPDATE` → recompute outstanding → insert, in one transaction.
**Why.** Correctness needs serialization *per business*, which is what a row lock gives at millisecond cost. A trigger cannot produce the field-level 422 the UI needs, and `SERIALIZABLE` would add retry loops and 500s.
**Alternatives.** Advisory locks (equivalent, less discoverable); optimistic version counters (more code, same outcome); DB trigger (rejected).
**Trade-off.** Creates for one business serialize. Irrelevant at MVP; the upgrade is a single conditional `INSERT … SELECT`.
**Necessary:** yes.

### ADR-7 [R]: Public token stored plaintext, unexpired, unique — **APPROVED (D-2)**
**Decision.** `secrets.token_urlsafe(32)` in `credit_transactions.public_token`, plaintext, no expiry, excluded from every creditor list serializer.
**Why.** The PRD requires a "Copy pay link" button at any time and links that live in emails for months — both impossible with a hash or a short TTL.
**Alternatives.** Store `sha256(token)` (rejected: the link could never be regenerated, breaking a MUST); a signed JWT link (rejected: longer URLs, key rotation invalidates old emails, still no revocation).
**Trade-off.** A database dump exposes live pay links; a log leak exposes one. Mitigated by HTTPS-only links, log redaction, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, single-transaction scoping, and never serialising the token in lists (§11.4). **Rotation and revocation are explicitly deferred and documented as future improvements** — they are the next security features, not oversights.
**Necessary:** yes, given the PRD. **Approved by you in review (D-2), with the safeguard set above as the condition of approval.**

### ADR-8: No debtor delete; cancellation is a status
**Decision.** No `DELETE /debtors/:id`; transactions are never deleted, only `cancelled`.
**Why.** PRD §3 says create/read/update only; deleting a debtor orphanates real debts and destroys the score's history. The audit trail is the product.
**Alternatives.** Soft delete with `deleted_at` (rejected: every query must remember to filter, and forgetting is invisible).
**Trade-off.** Stale debtors accumulate — carrying history, which is the point.
**Necessary:** yes.

### ADR-9 [R]: Native enums for closed status sets; `VARCHAR + CHECK` for event types and channel
**Decision.** PG enums for `credit_transaction_status`, `payment_status`, `debtor_response_type`, `promise_status`, `dispute_reason_type`, `reminder_kind`, `reminder_status`, `event_actor`. `VARCHAR + CHECK` for `transaction_events.type` and `reminders.channel`.
**Why.** Statuses are closed and load-bearing — a typo should fail at the database. Event types are the most likely future addition, and `ALTER TYPE … ADD VALUE` inside a migration transaction has version-specific restrictions. `channel` has one legal value today but is the obvious future expansion point (WhatsApp).
**Alternatives.** All enums (rejected: migration friction exactly where change is likely); all varchar+check (rejected: loses the strong guarantee where it matters).
**Trade-off.** Two conventions to remember — documented as a rule in §5.4.2.
**Necessary:** no, but deciding now is cheaper than retrofitting.

### ADR-10: Append-only events enforced by review, not a trigger
**Decision.** No `UPDATE`/`DELETE` on `transaction_events` in code; no DB trigger forbidding them.
**Why.** A raising trigger can block a legitimate emergency correction on demo day, and it guards against a mistake no code currently makes.
**Alternatives.** `BEFORE UPDATE/DELETE … RAISE EXCEPTION` (recommended post-MVP); a separate audit schema (rejected: over-engineering).
**Trade-off.** Discipline instead of enforcement — acceptable for a 3-person codebase; the trigger is a one-line migration later.
**Necessary:** no.

### ADR-11 [R]: Add `kora_webhook_events`
**Decision.** Record every webhook attempt, including rejected ones, with `UNIQUE(kora_reference, event)`.
**Why.** Provable idempotency, plus "did Kora send it and what did we do" without inferring from `payments.status`. The PRD's dedupe guidance ("keep track of all notifications received") effectively asks for it.
**Alternatives.** Rely on `payments.status` alone (rejected: cannot distinguish "never arrived" from "arrived and ignored", and a rejected signature leaves no trace); log-only (rejected: logs are not queryable in triage).
**Trade-off.** One extra table and write per webhook, plus a retention question (R-9).
**Necessary:** strongly recommended — the difference between a 5-minute and a 50-minute webhook debugging session.

### ADR-12 [R]: Receipt totals computed at render, not snapshotted — **APPROVED (D-5)**
**Decision.** "Total paid to date" and "balance remaining" are computed when the receipt renders.
**Why.** PRD §8.5 says "calculated at generation"; a debtor-facing receipt should say what is owed *now*, and a settled receipt must always show SETTLED.
**Alternatives.** A `receipts` snapshot table (rejected for MVP: extra table plus a write in the payment transaction, and receipts showing balances that no longer exist).
**Trade-off.** Re-opening an old partial-payment receipt shows today's balance, not the balance at that moment. Accepted, and now made **explicit in the document itself**: the receipt carries a fixed caption saying the balance is as at viewing time, so the reader is never misled into treating it as a historical snapshot. An audit export would need snapshots (the deferred Option B).
**Necessary:** no — but the cheaper correct choice now. **Approved by you in review (D-5).**

### ADR-13: Score never cached
**Decision.** Compute per read (3 batched queries for a page of debtors).
**Why.** PRD rule; and a cached score is wrong the moment a payment applies — precisely the demo moment.
**Alternatives.** Nightly snapshot (rejected: would show a stale score, the exact failure PRD correction 2 exists to fix); cache-on-write (rejected: another writer to keep correct).
**Trade-off.** Repeated work on every list render — negligible at MVP.
**Necessary:** yes.

### ADR-14: `slowapi` + in-memory limits for public routes
**Decision.** Per-token/IP limits in process memory; no Redis.
**Why.** The threat is casual abuse of public endpoints, and an in-memory limiter stops it. Exact global limits are not worth another service here.
**Alternatives.** Redis-backed `limits` (rejected: a new dependency for exactness nobody will test); no limiting (rejected: the PRD requires it).
**Trade-off.** With N workers the effective limit is N× configured — documented in §11.5; a one-line storage swap fixes it.
**Necessary:** yes (PRD requires rate limiting); in-memory is the pragmatic part.

### ADR-15 [R]: `created_by_business_id` instead of `created_by → users`
**Decision.** FK to `businesses`, not a new `users` table.
**Why.** The JWT subject *is* the business; there is no users table, and team roles are out of scope ([CONFLICT-1]).
**Alternatives.** Build `users` now (rejected: rewrites working auth to support an out-of-scope feature); nullable column (rejected: an unauthored transaction is a data-quality bug).
**Trade-off.** Deviates from a PRD column name; needs a migration when team members land.
**Necessary:** yes, given the codebase. **Approved by you in review (D-1).**

### ADR-16 [R]: Add `payments.idempotency_key` — **APPROVED (D-4)**
**Decision.** Optional `UUID`, unique per transaction, echoing a client `Idempotency-Key`.
**Why.** A double-tap on a mobile page creating two Kora charges is real and demoable, and it is the one duplicate path the record lock cannot prevent (two legitimate attempts).
**Alternatives.** Rely on attempt numbering (rejected: cannot distinguish a retry from a genuine second attempt); frontend debounce only (rejected: untrustworthy, defeated by two tabs).
**Trade-off.** One nullable column and one partial unique index; clients that ignore the header still work.
**Necessary:** recommended, not strictly MUST. **Approved by you in review (D-4).**

The approved semantics are stricter than v1's sketch, because a key that only deduplicates *concurrent* clicks leaves three holes: a replay after success (would create a second checkout), a replay with a different amount (would charge the wrong figure), and a replay against a failed attempt (would collide on the unique index). §6.7.3 now specifies all five cases and adds `409 IDEMPOTENCY_KEY_REUSED` for the two that must not silently succeed.

### ADR-17 [R]: Credit the verified gross amount; the payer bears Kora's fee — **APPROVED (D-11)**

**Decision.** `payments.amount_kobo` is the amount charged *and* the amount credited. Kora's `data.fee` is never subtracted; there is no net-settlement column, no fee arithmetic, and no fee on the receipt.
**Why.** Kora's fee is borne by the payer, so the verified amount is what the debtor actually paid towards the debt. Crediting a net figure would under-state every payment by the provider's cut and break the equality between "what we asked for" and "what we received" that makes verification simple and auditable.
**Alternatives.** Credit net and store the fee (rejected: invents a loss Credence did not take, and creates two money fields where one suffices); a `fee_absorbed` configuration flag (rejected: changes the meaning of the ledger, which is a decision, not a setting).
**Trade-off.** If Credence ever absorbs fees, every historical payment would need a backfill decision. Accepted: that is a future product change, and it will deserve its own migration and ADR.
**Necessary:** yes — it is the rule the whole money path depends on.

### ADR-18 [R]: Overpayments and paid-cancelled invoices are recorded and flagged, never discarded — **APPROVED (D-3)**

**Decision.** `payments.review_reason` (`overpaid` | `paid_cancelled_transaction`) is set inside `apply_verified_charge`. The payment stays `successful`; the transaction status is never changed by a flagged payment (a cancelled transaction stays cancelled, a settled one stays settled).
**Why.** Money that arrived is a fact, and the state machine belongs to the creditor. The two ways to get this wrong are both destructive: discarding/failing the payment loses the record of real money, and reopening the transaction silently reverses a creditor's decision and restarts reminders. Flagging preserves both truths and gives operations one query (`ix_pay_review`).
**Alternatives.** Auto-refund (rejected: no refund API in the PRD, and an automatic payout is a much larger commitment than a flag); reject the webhook (rejected: the money is already taken — a 4xx changes nothing for the payer); auto-reopen (rejected: overrides the creditor).
**Trade-off.** The surplus sits on the books until a human acts. At MVP volume that is honest; a refund workflow is future work.
**Necessary:** yes, given that neither the PRD nor Kora prevents these payments.

### ADR-19 [R]: One 09:00-WAT-next-day slot for already-overdue transactions (C-A)

**Decision.** `build_schedule()` is the only place a reminder date is computed, and an already-overdue transaction always receives exactly one `overdue_followup` at `next_overdue_slot()` = 09:00 Africa/Lagos on the next day. Creation, dispute resolution, rebuild, promise moves and promise expiry all resolve to it.
**Why.** v1 had an inconsistent, partly unreachable fallback that could leave an overdue debt with no reminder. One pure function with one slot rule makes the behaviour explainable and testable, and removes the "08:00 vs 23:00 creation behaves differently" class of bug.
**Alternatives.** Schedule at the next 9:00 even if it is today (rejected: a chase email minutes after data entry, and a same-day instant that may already be past); send immediately (rejected: the PRD's overdue reminders are 9 a.m. emails); let each caller compute its own slot (rejected: that is how v1 drifted).
**Trade-off.** An overdue invoice recorded at 08:00 waits ~25 hours for its first chase. Accepted — the creditor can always press "Send reminder now".
**Necessary:** yes; it fixes a defect.

### ADR-20 [R]: Sandbox Kora in the deployed demo, behind two explicit switches — **APPROVED (D-10)**

**Decision.** `KORA_MODE` (must match the key prefix) plus `DEMO_MODE` (default `false`, sandbox-only) are both required to run test credentials under `ENVIRONMENT=production`. `payments.provider_mode` records the mode per payment; responses and receipts surface it.
**Why.** The demo must run on Kora's sandbox, and the honest way to allow that is a narrow, visible, two-factor exception rather than a general "allow test keys in production" flag. Making it per-payment (not only per-deployment) means the distinction survives config changes and screenshots.
**Alternatives.** One permissive flag (rejected: a single boolean that permits test keys in production is one typo away from a silent live deployment problem); no exception at all (rejected: the PRD requires a sandbox demo); a separate staging deployment with test keys (rejected: the demo must run on the production URLs).
**Trade-off.** Two settings instead of one, and a boot check that can fail the deploy. That is the point.
**Necessary:** yes, for the demo.

### ADR-21 [R]: No business-activity table in the MVP; structured audit log instead — **APPROVED (D-9)**

**Decision.** Business-level changes (today: `PATCH /business/credit-limit`) write **no** `transaction_events` row and **no** new table. Each change emits one structured audit log line plus `businesses.updated_at`.
**Why.** There is no existing business-activity mechanism in the codebase, the PRD requires no activity feed, and a table nobody reads is cost without benefit. Log lines give what the review asked for — who changed what, when, in which request — without expanding the MVP's schema.
**Alternatives.** Add `business_activities` now (deferred: correct shape, no consumer yet, and the audit lines are its backfill source); put it in `transaction_events` (rejected: wrong scope, nullable FK, pollutes timelines and score inputs).
**Trade-off.** Traceability is log-retention-bound and not SQL-queryable. Documented as a known limitation with a costed upgrade path (§15.6).
**Necessary:** no — it is a deliberate, bounded simplification.

---

# 15. MVP Implementation Roadmap

Sequenced by the PRD's Tue–Fri plan, ordered by dependency, with the demo story as the only critical path. Times assume one backend engineer.

## 15.1 Day 1 (Tue 17) — schema, credit limit, debtors, capacity, create

| # | Task | Files | Done when |
| --- | --- | --- | --- |
| 1.1 | Convert `requirements.txt` to UTF-8 (no content change); add `apscheduler`, `jinja2`, `slowapi`, `respx`, `time-machine`, `pytest-cov` | `requirements.txt` | `pip install -r` still works; the diff is readable |
| 1.2 | `core/` foundations: `config`, `errors`, `money`, `time`, `pagination`, `logging`; extend `database.py` with `pool_pre_ping` | `app/core/*` | money/time unit tests pass |
| 1.3 | Migrations `0002`–`0007` (business columns, debtors, transactions, payments, responses, reminders) | `alembic/versions/*` | `upgrade head` then `downgrade -1` round-trips |
| 1.4 | Replace the `debtor.py` stub; add remaining models; export from `models/__init__.py`; add `db/enums.py` | `app/models/*`, `app/db/*` | `alembic check` reports no pending diff |
| 1.5 | `main.py`: routers, error handlers, CORS from settings, public-path middleware | `app/main.py` | existing auth still works; errors use the envelope |
| 1.6 | Business routes + `BusinessService` + the `business.credit_limit_changed` audit line | `modules/businesses/*` | PATCH sets/clears; `0` rejected; one audit line per change |
| 1.7 | Debtors create/list/patch/profile + `DebtorService.resolve_or_create` | `modules/debtors/*` | 409 carries `existing_debtor`; per-business uniqueness proven |
| 1.8 | `business_outstanding()` + `CreditCapacityService` + `GET /capacity` | `modules/capacity/*`, `businesses/queries.py` | response matches the PRD's JSON example |
| 1.9 | `balance.py` (`calculate_balance`, `display_status`) and `events.py` (`record`, `render_text`) | `modules/transactions/{balance,events}.py` | precedence + all event texts unit-tested |
| 1.10 | `ReminderService.build_schedule` (pure) + `next_overdue_slot` + `create_for_transaction` | `modules/reminders/schedule.py`, `service.py` | schedule for due+10 matches the PRD's list; R-1…R-4 pass |
| 1.11 | `EmailService` + all 8 templates | `integrations/email/*` | domain verified; email 1 lands in a real inbox |
| 1.12 | `POST /transactions` end to end (capacity re-check, sequence, token, reminders, event, post-commit email) | `modules/transactions/{service,router}.py` | 201 with `pay_link` + `reminders[]`; capacity race test passes |

**Day-1 exit:** a real credit transaction exists in the hosted DB with its schedule and its new-credit email delivered.

## 15.2 Day 2 (Wed 18) — public page, Kora, receipts, emails 6–8

| # | Task | Files | Done when |
| --- | --- | --- | --- |
| 2.1 | **Answer K-1…K-7 in the sandbox**; write `docs/architecture/kora-notes.md` | — | each answer recorded with the captured response |
| 2.2 | `kora/signature.py` (canonical + raw-slice) + tests | `integrations/kora/*` | K-3 resolved against a real body |
| 2.3 | `kora/client.py` (initialize, verify, naira→kobo) | `integrations/kora/client.py` | a sandbox charge returns a working checkout URL |
| 2.4 | `GET /public/tx/:token` with the safe projection, `initials`, `payment_config`, headers | `modules/public/*` | key-set test proves no internal field leaks |
| 2.5 | `acknowledge` (idempotent) + `POST /pay` (attempt allocation, full idempotency contract incl. `409 IDEMPOTENCY_KEY_REUSED`, Kora call) | `modules/public/service.py` | a real checkout opens; all five key cases behave as §6.7.3 |
| 2.6 | `POST /webhooks/kora` (signature, dedupe, verify, fast 200) | `modules/payments/router.py` | Kora's test webhook returns 200 and writes a row |
| 2.7 | `apply_verified_charge` + gross amount matching + status matrix + `review_reason` flags | `modules/payments/service.py` | §8.6.1 matrix and §12.11 concurrency rows pass |
| 2.7a | `payments.provider_mode` stamped at attempt creation; surfaced on payment + receipt | `modules/payments/*` | a sandbox payment is labelled in the API and on the receipt |
| 2.8 | `GET /public/tx/:token/payments/:ref` | `modules/public/*` | result page polls to `successful` |
| 2.9 | `POST /promise` + `PromiseService.make` + supersede + schedule shift | `modules/promises/*` | the demo promise moves reminders |
| 2.10 | `POST /dispute` + reminder cancellation | `modules/public/*` | `reminders_cancelled` correct |
| 2.11 | `ReceiptService` HTML + both receipt routes | `modules/payments/receipts.py`, `templates/receipt.html` | SETTLED stamp appears only at balance 0 |
| 2.12 | Emails 6, 7, 8 — exactly one on settlement | `integrations/email/templates.py` | test asserts 6 XOR 7 |
| 2.13 | `PromiseService.check_after_payment` + `promise_kept` | `modules/promises/service.py` | demo step 6 passes |
| 2.14 | Payment reconciliation job | `modules/payments/service.py`, `worker.py` | a stranded `pending` payment recovers |

**Day-2 exit:** demo steps 3–6 (acknowledge → promise → pay → webhook → balance drops) work on staging with real sandbox money.

## 15.3 Day 3 (Thu 19) — reminders job, timeline, dashboard, score, seed, disputes

| # | Task | Files | Done when |
| --- | --- | --- | --- |
| 3.1 | `ReminderService.deliver` (template at send time, promise move, follow-up chaining) | `modules/reminders/service.py` | §12.10 passes |
| 3.2 | `run_reminder_tick` with `SKIP LOCKED` claim + `worker.py` wiring | `modules/reminders/job.py`, `app/worker.py` | two concurrent ticks send each reminder once |
| 3.3 | `run_promise_check` daily job | `modules/promises/job.py` | missed promise → event + reminders resume |
| 3.4 | `POST /transactions/:id/remind` (cooldown, template, synchronous) | `modules/transactions/*` | 429 within the hour |
| 3.5 | `GET /transactions` (filters incl. `overdue`, stable sorting, pagination) | `modules/transactions/queries.py` | overdue filter matches `display_status` |
| 3.6 | `GET /transactions/:id` (timeline, payments, reminders, promise, `actions`) | same | every PRD §8.7 element present |
| 3.7 | `notes`, `cancel`, `resolve-dispute` (+ rebuild) | same | resolve-on-zero settles (§6.5.6 edge) |
| 3.8 | `RepaymentScoreService` + wire into debtor list/profile | `modules/scoring/*` | S-1…S-15 pass; batched == single |
| 3.9 | `GET /dashboard/summary` | `modules/dashboard/*` | totals tie to the transaction list |
| 3.10 | `GET /debtors/:id` profile (SHOULD) | `modules/debtors/*` | score facts render |
| 3.11 | Seed script — **variant B** (§15.5) | `app/scripts/seed_demo.py` | prints `Bright Foods Ltd: 78 (Mixed)` |
| 3.12 | Startup checks, `/health/ready`, login rate limit | `app/main.py` | refuses to boot with a test key in prod |
| 3.13 | Full test sweep + coverage | `app/tests/*` | §12.15 edge cases green |

**Day-3 exit:** the API is complete, the worker sends automated reminders, and the seed produces a visible score transition.

## 15.4 Day 4 (Fri 20, AM) — prove it twice

| # | Task | Done when |
| --- | --- | --- |
| 4.1 | Run the demo story on the **deployed URLs**, real Kora sandbox, real inbox | twice, cleanly, without touching the DB |
| 4.2 | Run the e2e test (§12.14) against staging | green |
| 4.3 | Kill the worker mid-tick; confirm reminders resume | no duplicate sends |
| 4.4 | Verify the seed resets demo state in under a minute | `seed_demo` then observe |
| 4.5 | Fix **only** what breaks the story | per the PRD's rule for the week |

## 15.5 Seed script specification (PRD §11, variant B)

| Entity | Rows | Purpose |
| --- | --- | --- |
| Business | "Adeyemi Wholesale Ltd", `credit_limit_kobo = NULL` | demo sets the limit live (step 1) |
| Bright Foods Ltd | real controlled inbox; 4 settled transactions (3 on time, 1 late by **3 days**); promises **2 kept, 1 missed** | score **78 → 81** when the live promise is kept |
| Strong debtor | 5 settled all on time, 2 kept, 0 missed | green badge |
| Weak debtor | 2 settled, one 40 days late, 1 missed | red badge |
| No-history debtor | 0 transactions | "No history yet" |
| Extra transactions | 1 overdue (due 14 days ago, balance > 0), 1 due in 4 days, 1 `disputed` | every dashboard list and badge has data |

**Seed mechanics that matter:**

- Write `payments` rows with `status='successful'` and backdated `paid_at` so `avg_days_late` and `promise_rate` are *real*, not fabricated numbers.
- Set `status='settled'` **and** `settled_at` together — the CHECK requires it.
- Do **not** create the live ₦150,000 transaction; the demo does that.
- Be idempotent: delete only the demo business's rows (fixed business id or email) before inserting. Never truncate tables globally.
- Print the pre-demo score at the end. If it is not `78 (Mixed)`, the seed or the scorer is wrong — a self-checking seed for five extra lines.

## 15.6 Deferred (and what it would take)

| Deferred | Why | Cost later |
| --- | --- | --- |
| PDF receipts | SHOULD; HTML covers the demo | ~1 h (WeasyPrint + a route branch) |
| Logo upload | **Dropped from the MVP by decision (D-7)**; `logo_url` is display-only and initials are the fallback | ~2 h (storage adapter + PATCH route) if it is ever wanted |
| Profile page polish | SHOULD | API already built |
| Redis-backed limits | MVP limits adequate | ~1 h |
| `users` table + roles | Out of scope | migration + JWT subject change |
| Offline/manual payments | Out of scope (Q2) | new table + reconciliation UI |
| Refunds/reversals | Out of scope; flagged payments (ADR-18) carry the ops need | new states + payout integration |
| `business_activities` table + activity feed | D-9/ADR-21: log lines cover traceability, no screen consumes it | ~2 h migration + read endpoint; audit lines are the backfill |
| Token rotation/revocation | D-2: documented as the next security feature | ~3 h (rotate route + `revoked_at` + tests) |
| Receipt balance snapshots | ADR-12: receipt states the balance is "as at viewing"; snapshots would make it historical | ~1 h table + one write in the payment transaction |

---

# 16. Risks, Dependencies, and Open Questions

## 16.1 Risks, ranked by demo impact

| # | Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- | --- |
| **R-1** | Kora sandbox cannot simulate a successful card payment without a real card | Medium | **Fatal to the demo** | Answer K-8 by Wednesday 09:00; if there is no simulator, make a real ₦100 sandbox charge immediately and escalate to Kora support; keep a recorded fallback run |
| **R-2** | Amount unit/format mismatch (naira string vs kobo), or someone "helpfully" subtracting Kora's fee | Low (rule now fixed) | Every payment under-credited or recorded as failed, on stage | §8.4.1: gross credit, `Decimal` conversion, `fee` never in arithmetic; K-1/K-2 confirmed before any payment code is written |
| **R-3** | Webhook signature canonicalisation mismatch | Medium | Every real webhook rejected | Raw-slice fallback (§8.5.3); K-3 against a captured body; record which strategy matched |
| **R-4** | Public debtor tokens or the Kora key leaking via logs | Low | Credential/data leak | §11.4: HTTPS-only links, path rewriting + key redaction, `no-store`, `no-referrer`, single-transaction scope, secrets only in the platform store |
| **R-5** | Email deliverability (SPF/DKIM not propagated) | Medium | No email on stage | Verify the domain Tuesday, send to a real inbox Wednesday; the debtor page works with zero email since the link is copyable |
| **R-6** | Score does not visibly change (the failure PRD correction 2 fixed) | Medium | The "trust measurable" claim falls flat | Seed variant B + printable pre-demo score + an assertion on the 78→81 transition |
| **R-7** | Hosted schema drift (a `debtors` table already exists, differently shaped) | Low | Migration fails on deploy | §5.8 existence check; refuses `SET NOT NULL` with rows; run `to_regclass` before writing the migration |
| **R-8** | `ck_ct_settled_at` blocks a future reversal/refund flow | Low (out of scope) | A future migration must relax it | Documented in §5.3.3; intentional for MVP |
| **R-9** | `kora_webhook_events` grows unbounded | Very low at MVP | Slower table over months | 90-day delete job post-MVP; rows are small |
| **R-10** | No backup/restore drill | Low | Data loss unrecoverable | Confirm provider snapshots are enabled; the seed can recreate demo data |
| **R-11** | Boot guards block the demo (mode/key mismatch, or `DEMO_MODE` not set) | Medium | Deploy fails Friday morning | §13.3 checks 3–5; verify the exact production env values and boot once before the demo; the failure message names the missing setting |
| **R-12** | Two workers relax the rate limits | Low | Weaker abuse protection | Documented in §11.5; run 2 workers, not 4 |
| **R-13** | Scheduler drift (a 15-min job starting at :07) | None | None — no reminder requires an exact minute | All sends are "≥ `scheduled_for`", never equality |
| **R-14** | Timezone bug (a UTC date used as WAT) | Medium | A "due today" email a day early | Single `core/time.py`, CI grep against naive datetimes, test E-17, R-10 for the 09:00 slot |
| **R-15** | Overpaid / paid-cancelled payments need a human, and the MVP has no ops screen | Medium | Money recorded but unreconciled; nobody notices during the demo week | `ix_pay_review` as a documented one-line query in the demo-day runbook (§13.5); the `payment_received` event carries `review_reason`; Q-13 records the open question of an in-product indicator |
| **R-16** | A sandbox payment mistaken for real money (or the reverse) | Low | Credibility damage, or a live charge during rehearsal | `KORA_MODE` must match the key (§13.3), `payments.provider_mode` per row, test-payment banner, `SANDBOX` receipt marker |
| **R-17** | Business-level audit traceability is bounded by log retention | Low | "Who lowered our limit in October?" becomes unanswerable | Documented limitation (ADR-21); the deferred `business_activities` table is the upgrade, and `businesses.updated_at` survives regardless |
| **R-18** | A client that omits `Idempotency-Key` on `POST /pay` | Medium | A double-tap becomes two charges | The shipped frontend always sends one; attempt numbering keeps the system consistent even without it, and the §12.11 concurrency rows guarantee no money is lost |

## 16.2 External dependencies

| Dependency | Needed by | Status | Owner |
| --- | --- | --- | --- |
| Kora sandbox account + secret key | Wed AM | must confirm it can charge | team |
| Kora webhook URL configured in the dashboard and reachable | Wed AM | needs the deployed URL | team |
| Resend account + **verified sending domain** (SPF/DKIM) | Tue | PRD calls this out explicitly | team |
| Hosted Postgres reachable with migration rights | Tue | exists | team |
| Demo debtor inbox (real, controlled) | Tue | PRD §11 requires it | team |
| Frontend public page `/pay/:token` | Thu | must consume these exact shapes | frontend |
| Frontend `formatNaira(kobo)` helper | Tue | no float math | frontend |

**Contract with the frontend:** every money field is an integer kobo named `*_kobo`; every badge uses `display_status`; every error is `{error:{code,message,fields}}`; every list is `{data,meta}`. If the frontend mocks §6.2 before the routes exist, integration is a switch, not a rewrite (PRD §10).

## 16.3 Open questions requiring your decision

### 16.3.1 Closed by your review

| # | Question | Decision | Recorded in |
| --- | --- | --- | --- |
| **Q-1** | `created_by`: `users` table or business FK? | **Business FK** (`created_by_business_id`) | D-1, ADR-15 |
| **Q-3** | Logo upload endpoint? | **No.** Keep `logo_url` as a display field, no upload, no storage | D-7 |
| **Q-4** | Rotatable public tokens? | **Not in the MVP**; rotation *and* revocation documented as future improvements | D-2, §11.4 |
| **Q-5** | Does `PATCH /business/credit-limit` write an event row? | **No event row, no new table.** One structured audit line + `updated_at` | D-9, ADR-21, §11.9.2 |
| **Q-7** | Payment on a `cancelled` transaction? | **Record, keep cancelled, flag for investigation/refund** — never reopen, never discard | D-3, ADR-18, §8.9.4 |
| **Q-8** | Score with promises but no counted transactions? | **Option A:** `No history yet`, no number, promise facts shown separately | D-6, §10.4 |
| **Q-9** | `payments.idempotency_key` in scope? | **Yes**, with the full five-case contract | D-4, ADR-16, §6.7.3 |
| **Q-11** | Unknown reference: 200 or 404? | **200**, recorded as `unknown_reference`, no money touched | D-8, §6.8.1 |
| **Q-12** | `amount` or `amount_paid`? | **`amount`**, and it is gross — the fee is never deducted | D-11, ADR-17, §8.4.1 |

### 16.3.2 Still open (each has a recommended default; none blocks Day 1)

| # | Question | Options | My recommendation | Impact if you defer |
| --- | --- | --- | --- | --- |
| **Q-2** | Does `POST /transactions` return the full object, or just an id? | (a) full object + `pay_link` + `reminders` (b) id only | **(a)** — the confirmation page needs the schedule immediately (PRD §8.2) | one extra `GET` on the confirm screen |
| **Q-6** | Should `GET /dashboard/summary` include debtor scores? | (a) no (b) yes | **(a)** — the PRD's dashboard spec lists five lists and no scores; it would add three queries | the dashboard is unaffected either way |
| **Q-10** | Should a manual reminder suppress the next automatic one? | (a) no (b) yes | **(a)** — manual is additive; (b) lets a creditor accidentally silence reminders | a creditor could receive two emails close together |
| **Q-13** | Should `overpaid` / `paid_cancelled_transaction` payments be visible **in the product** (a flag on the transaction details / dashboard counter), or only in the ops query? | (a) ops query only, MVP (b) add a read-only `review_required` boolean to the payments list and a dashboard count | **(a)** for the demo week — it is the smallest change and the money is already safe and queryable. **(b)** is a ~1 h additive change if a creditor is expected to act on it themselves | nothing breaks; the flag is in the DB and on the timeline, just not on a screen |

## 16.4 What to look at in this revision

The five items v1 asked you to weigh are all closed. The things worth a second look now are the ones where the design changed shape rather than wording:

1. **§8.6 / §8.6.2 — the money mutation.** The algorithm was re-ordered so the verified sum is read inside the transaction-row lock and excludes the row being applied, and so every settlement side effect is gated on the *transition*. This is the single most important change in v2; if it is wrong, nothing else matters.
2. **§5.7.5 and §8.9.3 — the two-winner overpayment.** Confirm you accept that both charges are recorded, the debt is credited once, and the surplus is flagged rather than refunded automatically.
3. **§8.9.4 — paid-cancelled invoices.** The state machine is preserved and the money is recorded; the only remedy in the MVP is a human one. Confirm you accept that as "flagged for investigation or possible refund".
4. **§9.3.1 — the 09:00-next-day slot.** One rule, five entry points. Confirm "next day" (not "today at 09:00 if it has not passed") is what you meant.
5. **§13.3 / §13.7 — the demo exception.** Two switches, mutually constrained, with the mode stamped on every payment. This is the one place the design deliberately permits something unsafe in production; the fencing is the price of the demo.
6. **§11.9.2 — business traceability.** Confirm that structured log lines (durable, greppable, retention-bound) are "sufficient operational traceability" for the MVP, with the table deferred.

## 16.5 Traceability closing statement

| PRD requirement class | Count | Status in this design |
| --- | --- | --- |
| MUST items (§3) | 11 | all specified, each with an owning component and a test |
| SHOULD items (§3) | 3 | 2 designed, 1 **dropped by decision** (logo upload, D-7); PDF receipts deferred with a costed path |
| API routes (§9) | 24 | all specified (§6.0 index) |
| Tables (§6) | 7 | all specified, plus one recommended addition (`kora_webhook_events`); no other table is added (no `business_activities` — ADR-21) |
| Emails (§8.6) | 8 | all in one template file; contexts enumerated (§9.7) |
| Event types (§8.7) | 14 | all in the CHECK constraint and the render table (§7.3) |
| Stored statuses (§5) | 6 | the enum has exactly six; `overdue` is derived |
| Business rules (§4) | 12 | all mapped to an enforcement mechanism (§2.3) |
| Demo story steps (§2) | 6 | all covered by the end-to-end test (§12.14) |
| Your review decisions (D-1…D-11) | 11 | all implemented, each traced to a section and an ADR (revision log, §16.3.1) |
| Technical corrections (C-A, C-B, C-C) | 3 | all implemented with dedicated tests (§12.10.1, §12.11, §11.9.2) |

**Every PRD MUST has a home. Nothing beyond the PRD is designed except where marked [REC] or decided in review (D-1…D-11), and each of those exists to satisfy a rule the PRD itself states or an edge the PRD leaves undefined** — idempotency, the audit trail, the "over by ₦X" copy, the disabled-button rules, and the two money edges the PRD never mentions (overpayment, a payment on a cancelled invoice).

## 16.6 Response to this round of review

### 1. What changed in this revision

| # | Change | Section |
| --- | --- | --- |
| 1 | Added a revision log + approved-decision register (D-1…D-11) at the top, and a matching closing table | front matter, §16.5 |
| 2 | **Gross amount, payer bears the fee.** New §8.4.1, a rewritten verification rule, fee row in §8.1, `fee` excluded from all arithmetic, ADR-17, worked ₦1,000.45 → `100045` kobo example | §2.4, §8.1, §8.4, §8.6, §8.10.2, ADR-17 |
| 3 | **Rewrote `apply_verified_charge`** (steps 1–17): verified sum excludes the row being applied, gross credit, `status_before` captured, `settled_now` transition gate, review flags, single `payment_received`, exactly one email | §8.6 |
| 4 | Added **§8.6.2**, mapping your six concurrency requirements to mechanisms, and **§5.7.5**, a full two-winner overpayment walk-through | §5.7.5, §8.6.2 |
| 5 | Added `payments.review_reason` (`overpaid` \| `paid_cancelled_transaction`), `payments.provider_mode`, `ix_pay_review`, two CHECKs, and their column documentation | §5.3.4, §5.5, §5.6 |
| 6 | Rewrote **§8.9.4** (cancelled invoices): record, keep cancelled, flag, never reopen, never discard — with a per-aspect table | §8.9.4 |
| 7 | Strengthened **§8.9.3** (overpayment): both recorded, one settle, one email, surplus flagged as an ops item with an explicit "what flagged means" | §8.9.3 |
| 8 | Full **idempotency contract** (five cases) on `POST /pay`, with `409 IDEMPOTENCY_KEY_REUSED`, and a new error-catalogue entry | §6.7.3, §6.1.4, §8.8 |
| 9 | **Replaced `build_schedule`** with a single correct implementation incl. `next_overdue_slot()`; documented the five entry points; corrected the promise-move rule; fixed the "already overdue ⇒ no reminder" defect | §9.3.1, §9.3.2, §9.3.3, §9.5.2, §9.9, ADR-19 |
| 10 | **Unknown references** now record `outcome='unknown_reference'`, return 200, touch nothing; added the outcome→HTTP table | §6.8.1, §5.3.8, §8.14 |
| 11 | **Score Option A** made a decision: no number from promises alone, facts shown separately, zero never rendered | §10.4, §10.6 |
| 12 | **Business audit** rewritten as three trails; log-line contract for `business.credit_limit_changed`; no `transaction_events` row, no new table | §11.9, §6.3.2, ADR-21 |
| 13 | **Demo-only sandbox exception** rebuilt as `KORA_MODE` + `DEMO_MODE` with five boot checks, per-payment `provider_mode`, banner and receipt marker | §13.2, §13.3, §13.7, §11.10, ADR-20 |
| 14 | **Token safeguards** consolidated into one table (HTTPS, CSPRNG, no-logs, `no-store`, `no-referrer`, single-transaction scope, rotation/revocation deferred) | §11.4, §6.7.0, ADR-7 |
| 15 | **Logo upload dropped**; `logo_url` retained as display-only; `python-multipart` removed from the dependency delta | §2.2, §4.4, §15.6 |
| 16 | **Receipt balance** labelled "as at the time of viewing", with fixed copy in §8.10.2 | §6.6.1, §8.10.2, §8.10.3, ADR-12 |
| 17 | New tests: **R-1…R-10** (reminder slots), five concurrency rows, five idempotency rows, **E-21…E-29**; roadmap tasks updated | §12.10.1, §12.11, §12.12, §12.13, §12.15, §15 |
| 18 | Five new ADRs (17–21) and approvals recorded on ADR-7/12/15/16; risks R-15…R-18 added; Q-1…Q-12 statuses split into closed/open | §14, §16.1, §16.3 |

### 2. Decisions that remain unresolved

| # | Question | My default if you say nothing |
| --- | --- | --- |
| Q-2 | Full object vs id-only from `POST /transactions` | full object + `pay_link` + `reminders` |
| Q-6 | Scores on the dashboard summary | not included |
| Q-10 | Does a manual reminder suppress the next automatic one | no — manual is additive |
| Q-13 | Are `overpaid` / `paid_cancelled_transaction` flags visible in the product, or only in the ops query | ops query only for the demo week |

There are no unresolved questions about money, status transitions, idempotency or reminders. Everything in those areas is decided.

### 3. Assumptions still requiring your confirmation

| # | Assumption | Why it matters | If it is wrong |
| --- | --- | --- | --- |
| 1 | `data.amount` from Kora verify is the gross amount and no fee is deducted (your statement, D-11) | The whole credit rule | If a sandbox test shows a net figure, K-1/K-2 must be re-answered before payment code; no schema change needed, but `credited` would need a documented offset |
| 2 | The codebase has **no** existing business-activity/audit mechanism (I found none) | Basis for ADR-21's "defer the table" decision | Tell me the mechanism and §11.9.2 uses it instead of log lines |
| 3 | The frontend sends `Idempotency-Key` on every `POST /pay` | Double-tap protection in practice | Backend stays correct; the risk moves fully to the client |
| 4 | The platform log drain retains lines for at least the demo week + 30 days and can be searched by `business_id` | Business traceability (D-9) | The deferred table becomes necessary sooner |
| 5 | Per-business serialisation on `POST /transactions` (the row lock) is acceptable | §5.7 / ADR-6 | Only relevant at thousands of creates per second |
| 6 | Kora sandbox webhooks are signed exactly like live ones (K-12) | Signature verification in the demo | Would be caught by §8.5.3's fallback and K-3 |
| 7 | NGN is the only currency in the MVP | The `currency_ok` check | Multi-currency is a schema and ADR change, explicitly out of scope |
| 8 | `payments.provider_mode` defaulting to `sandbox` is acceptable | No payments exist yet, so the default never backfills real data | If any rows existed, the migration would need an explicit value |
| 9 | Africa/Lagos has no DST, and Postgres has current tz data | 09:00 WAT is a stable instant (`08:00Z`) | R-10 would fail loudly in CI rather than silently shifting reminders |

### 4. Consistency with the Credence PRD

**Confirmed, with two documented deviations and no silent ones.**

| PRD area | Status |
| --- | --- |
| §3 MUST items (11) | All present, all with an owning component and a test. Nothing MUST-level is deferred |
| §3 SHOULD items (3) | PDF receipts designed (deferred), profile page designed, logo upload **dropped by your decision (D-7)** |
| §4 business rules (12) | All mapped to an enforcement mechanism (§2.3); none weakened |
| §5 statuses (6) | Unchanged; `overdue` still derived, never stored; no status added by this revision |
| §6 data model | All seven tables; one recommended addition (`kora_webhook_events`); this revision adds **columns only** (`payments.review_reason`, `payments.provider_mode`) and one index |
| §7.1 balances/capacity | Still computed on read; no stored balance, no stored capacity; score never cached |
| §7.2 reminders | Schedule rules preserved; the already-overdue case now has one defined answer (C-A) instead of an inconsistency |
| §7.3 promises | One open promise per transaction; supersede semantics unchanged; reminders delay then resume |
| §7.4 score | Formula, weights, categories and rounding unchanged; Option A applies the PRD's own "no counted transactions" row |
| §8 flows / §9 routes (24) | Unchanged route set; two additive response fields (`provider_mode`), one new error code, one new header contract |
| §13 risks | Amount-unit risk resolved and now also fee-safe (§8.4.1) |

**The two deviations, both approved:** the column name `created_by_business_id` instead of `created_by → users` (D-1), and plaintext public tokens (D-2). Everything else follows the PRD literally. Two places where the PRD is *silent* rather than contradicted are filled by decision: payments on cancelled transactions (D-3) and overpayment handling (D-11 / ADR-18) — spec'd as behaviour, not as new features.

### 5. Internal consistency of the payment rules

The rules below are stated once and referenced everywhere; no section contradicts another:

| Rule | Stated in | Referenced by |
| --- | --- | --- |
| Kora takes **naira**; Credence stores **integer kobo**; conversion uses `Decimal` + `ROUND_HALF_UP`, never `float` | §8.4, §8.4.1, §1.2 | §2.4, §3.5, §6.7.3, §7.2.6, §12, ADR-17 |
| The verified amount is **gross**; Kora's fee is borne by the payer and **never** subtracted | §2.4, §8.1, §8.1.1, §8.4.1 | §3.5, §8.6, §8.9.3, §8.10.2, §8.14, ADR-17, §16.3.1 |
| `payments.amount_kobo` = amount requested = amount credited | §5.3.4, §8.4.1 | §8.6, §8.10.2 |
| Balance = `max(amount_kobo − Σ successful payments, 0)`, computed on read, never decremented | §1.2, §5.6, §8.6, ADR-3 | §6.2, §6.7.3, §8.9, §10.3 |
| Only a server-verified charge is `successful`; the redirect and the webhook body are never trusted for money | §3.7, §8.4, §8.5 | §6.8.1, §8.8, §11.6 |
| The same verified payment cannot be applied twice (row lock + status guard + unique reference + event dedupe) | §8.6, §8.6.2, §8.8 | §5.7, §12.11 |
| Two concurrent successful payments are serialised; the surplus is recorded and flagged, never discarded | §5.7.5, §8.6.2, §8.9.3 | §11.11, §12.11, ADR-18 |
| Settlement fires once, gated on the transition; one `settled` event, one reminder cancellation, one grouped email | §8.6, §8.6.2, §8.9.2, §8.11 | §9.5, §12.11, §12.12 |
| Idempotency is layered (client key, attempt number, provider reference, webhook event, payment status, receipt sequence, recompute) with an explicit five-case contract on replay | §8.8, §6.7.3 | §5.3.4, §12.13, ADR-16 |
| A cancelled transaction stays cancelled even when paid; the payment is flagged | §8.6, §8.9.4 | §3.7, §8.6.1 matrix, §8.14, ADR-18 |
| An unknown reference is recorded and acknowledged with 200, touching no money | §6.8.1 | §5.3.8, §8.14 |

**Verification that this is enforced, not merely written:** the equality `credited = expected` is a single `if` in §8.4; `fee` appears nowhere in any arithmetic (only in `raw_webhook`); the balance is a sum, so double-crediting is structurally impossible; the transition gate is the only path to a `settled` side effect; and E-21…E-29 plus §12.11/§12.13 assert each row above. A reviewer can grep the implementation for `fee` and for `balance -=` and expect zero hits outside tests.

---

*End of document — revised (v2) and awaiting final approval before implementation.*
