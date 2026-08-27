# ISP Customer Support Assistant — Dialogflow CX

A small, production-oriented customer support assistant for an ISP, built on
Dialogflow CX. Handles connectivity troubleshooting, outage checks (via
webhook), and ticket status lookups (via webhook), with interruption
handling and explicit failure-recovery paths.

## Repository layout

```
.
├── README.md                     ← you are here
├── docs/
│   └── architecture.md           ← flow/page diagram + design rationale
│   └── answers.md                ← technical design questions
├── dialogflow_cx_agent/
│   ├── build_agent.py            ← creates the whole CX agent via API
│   └── requirements.txt
└── webhook/
    ├── app.py                    ← Flask webhook (Dialogflow-facing layer)
    ├── services/
    │   ├── outage_service.py     ← outage business logic
    │   └── ticket_service.py     ← ticket business logic
    ├── tests/
    ├── requirements.txt
    └── .env.example
```

## 1. How to run the webhook

```bash
cd webhook
python -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
cp .env.example .env                               # edit if you want a shared secret
python app.py
# Webhook is now listening on http://localhost:8080/webhook
```

Health check: `curl http://localhost:8080/healthz` → `{"status": "ok"}`

Dialogflow CX needs to reach this over HTTPS. During development, expose it
with [ngrok](https://ngrok.com/):

```bash
ngrok http 8080
```

Use the `https://...ngrok-free.app/webhook` URL as the webhook URI in the CX
console (or in `build_agent.py`'s `WEBHOOK_URL` config).

## 2. How to configure/import the Dialogflow CX agent

**Recommended path (fast, reproducible):**

```bash
cd dialogflow_cx_agent
pip install -r requirements.txt
gcloud auth application-default login
# edit build_agent.py: set PROJECT_ID, WEBHOOK_URL (your ngrok URL)
python build_agent.py
```

This creates the agent, entity types, intents, all four flows, their pages,
transition routes, and the webhook resource — end to end — using the
Dialogflow CX Python client. It prints the console URL at the end.

**Why script the agent instead of a manual export?** Dialogflow CX agent
exports are binary-ish ZIPs that don't diff cleanly in git and don't show
*why* something was built a certain way. A Python build script is
reviewable, versionable, and re-runnable — which is also the answer to
Question 4 (safe deploys) below: this script *is* the deployable artifact.

**If you'd rather build by hand in the console**, use `docs/architecture.md`
as your blueprint — it lists every flow, page, intent, and transition this
script creates, so you can recreate it by clicking instead.

## 3. Required environment variables

Webhook (`webhook/.env`):
| Variable | Required | Purpose |
|---|---|---|
| `PORT` | no (default 8080) | local port |
| `LOG_LEVEL` | no | Python logging level |
| `WEBHOOK_SHARED_SECRET` | no | if set, `/webhook` requires header `X-Webhook-Secret` to match |

Agent build script (`dialogflow_cx_agent/build_agent.py`, edited in-file
rather than env vars since it's a one-time setup script):
`PROJECT_ID`, `LOCATION`, `WEBHOOK_URL`, `WEBHOOK_SHARED_SECRET`

## 4. How to run tests

```bash
cd webhook
pip install -r requirements.txt
python -m pytest tests/ -v
```

22 tests covering: outage lookup (happy path, unknown zip, invalid zip,
simulated timeout, simulated 5xx, simulated malformed response), ticket
lookup (happy path, not found, invalid ID, simulated 5xx), and the Flask
layer end-to-end (correct session parameters set, correct HTTP status
codes, correct fallback error text).

## 5. Architectural decisions (brief — see `docs/architecture.md` for detail)

- **One flow per journey** (Troubleshooting / Outage Check / Ticket Status),
  with a thin **Default Start Flow** doing nothing but intent-based routing.
  This keeps each flow's pages, parameters, and routes scoped to a single
  conversational job — easier to reason about, test, and hand to another
  engineer.
- **Session parameters carry conversational state only** (what device
  scope, what router status, what ticket ID) — never PII beyond what's
  needed for the active turn, and never the definitive record of anything
  (see `docs/answers.md` Q2 for the full session-vs-backend split).
- **Two webhook tags, one Flask app**: `check-outage` and
  `get-ticket-status`. Dialogflow-facing parsing lives only in `app.py`;
  all actual logic lives in `services/`, independently unit-testable.

## 6. Interruption/resumption approach

A **route group** ("Global Interruptions") is attached at the
**Troubleshooting flow level** (not a single page), so the `check.outage`
intent is reachable from *every* page inside that flow — the user can ask
"is there an outage?" whether they're mid router-status question or looking
at a recommendation, without Dialogflow CX no-matching on it.

When that interruption fires, control passes to the Outage Check flow.
Troubleshooting's own session parameters (`device_scope`, `router_status`,
etc.) are untouched — Dialogflow CX session parameters persist across
flows in the same session by default, so nothing is lost. Once the outage
check resolves, the **No Outage** page returns the user to the
Troubleshooting flow; the **Outage Found** page instead ends the
troubleshooting attempt, since a confirmed outage makes further
troubleshooting steps pointless — that's the "exit when appropriate"
branch the assignment calls for.

## 7. Production considerations

**What I'd monitor:**
- **Webhook latency/failures** — p50/p95/p99 latency and error rate per
  tag (`check-outage`, `get-ticket-status`), alerting on error-rate
  spikes or p95 breaching the CX webhook timeout.
- **No-match rate** — per intent and per page, since a spike usually means
  a training-phrase gap or a wording change in a recent release.
- **Conversation abandonment** — sessions ending outside a "resolved" or
  "escalated" terminal page, bucketed by which flow/page they dropped at.
- **Task completion rate** — % of sessions that reach a defined success
  page (Resolved / Outage Found+acknowledged / Ticket status delivered).
- **Escalation rate** — how often Troubleshooting ends at "Escalate" over
  time; a sustained increase suggests either a real outage/incident or a
  regression in the troubleshooting steps themselves.

**Credentials/secrets:** webhook URL's shared secret and any downstream
API keys go in a secret manager (e.g. GCP Secret Manager), injected as
env vars at deploy time — never committed, never logged.

**Sensitive customer info:** avoid collecting more than the active
journey needs (ZIP code, ticket ID); don't log raw parameter values at
INFO in production — log hashed/truncated identifiers, full detail only
at DEBUG in non-prod.

**Webhook authentication:** the shared-secret header shown in `app.py` is
the minimum; for a real deployment prefer Dialogflow CX's built-in
service-account-based webhook auth (OIDC token) fronted by Cloud Run/Cloud
Functions IAM, so no static secret is needed at all.

**Logging of customer data:** structured logs with a request ID, no raw
PII in log lines (ZIP codes are borderline-sensitive at scale — treat like
PII), and a retention/rotation policy in line with whatever data-privacy
regime applies to the ISP's customers.

## 8. Known limitations

- The webhook's "backend" is simulated in-memory data plus explicit
  failure-injection flags (`simulate="timeout"/"5xx"/"malformed"`) rather
  than a real ISP system — sufficient to demonstrate the required error
  paths without needing real infrastructure.
- `build_agent.py` is a first-run script, not idempotent — re-running it
  against an existing agent will create duplicate resources. For iterative
  development, delete-and-recreate the agent, or extend the script to
  check for existing resources by display name first.
- Fulfillment text in a couple of pages uses Dialogflow CX's conditional
  response syntax inline for brevity; in the real console you'd normally
  split these into separate conditioned response messages per parameter
  value rather than one string with embedded conditions.
- No Cloud Run/Cloud Functions deployment config is included — the
  assignment explicitly allows running the webhook locally via ngrok.
