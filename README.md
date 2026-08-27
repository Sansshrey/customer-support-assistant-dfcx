
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

**Alternatively**, `exported_agent_ISP Customer Support Assistant.zip` in
the repo root is a direct JSON Package export of the live agent (Draft
environment, taken after all fixes and the composite-input enhancement
below). It can be imported directly via **Dialogflow CX console → Agent
selector → Import** without running `build_agent.py` at all — this is the
fastest way to get the exact, final agent state running.

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

## 7. Composite-input / context-aware escalation

A follow-up requirement asked the agent to handle a single message that
already answers several troubleshooting questions at once, e.g.:

> "My internet is not working. I have already restarted the modem and my
> laptop/mobile, and tested the connection using both LAN and Wi-Fi, but
> the issue is still not resolved."

Rather than re-asking device scope and router status, the agent should
recognize that these steps are already exhausted and route straight to a
human agent (Escalate), acknowledging what the user already tried.

**How this is implemented — intent-based, not generative:** this is
deliberately **not** open-ended LLM reasoning, which is out of scope for a
classic Dialogflow CX agent (and harder to test/verify for a case like
this). Instead:

1. A dedicated intent, **`report.connectivity_issue.exhausted`**, is
   trained on phrasings that describe having already completed multiple
   troubleshooting steps in one message (modem/device restart *and*
   LAN/Wi-Fi already tested, still broken).
2. When that intent matches, its route sets a session parameter preset,
   `skip_to_escalate = true`.
3. At the **top of the Connectivity Troubleshooting flow's entry
   routing** — checked *before* the catch-all route into **Collect Device
   Scope** — a conditioned route checks `skip_to_escalate`. If true, the
   conversation is sent straight to the **Escalate** page, bypassing the
   device-scope and router-status questions entirely.
4. The **Escalate** page's fulfillment message is now conditional: when
   `skip_to_escalate` is true, it acknowledges the steps the user already
   described instead of showing the generic escalation message.

A normal short complaint ("My internet isn't working") does **not** match
`report.connectivity_issue.exhausted`, so it still falls through to the
original catch-all route and runs the full step-by-step Q&A — the new
logic only short-circuits when the composite pattern is actually present,
and doesn't change behavior for the standard journey.

Being explicit that this is pattern/intent matching rather than
open-ended reasoning is a deliberate choice: it's deterministic, testable,
and reviewable in the same way as the rest of the agent, rather than
depending on a model's judgment call at runtime.

## 8. Production considerations

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
  regression in the troubleshooting steps themselves (including the new
  composite-input path in section 7 above).

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

## 9. Known limitations

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
- The composite-input detection in section 7 is intent/pattern-based, so
  it covers the documented example and similarly-phrased variants well,
  but — unlike a generative approach — it won't generalize to arbitrarily
  worded composite complaints outside its training phrases without adding
  more phrases over time.

## 10. Demo

A short recorded demo is available here: **[ADD YOUR VIDEO LINK HERE]**

It covers:
- The composite-input example from section 7 above, showing the
  troubleshooting questions skipped and direct routing to Escalate with
  the acknowledgment message.
- A backend-failure scenario (simulated outage-service timeout) with
  graceful recovery, per the assignment's error-handling requirement.
- A standard Troubleshooting journey (resolved path), an Outage Check,
  and one interruption scenario, for completeness.
