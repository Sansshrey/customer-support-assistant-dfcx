# ISP Customer Support Assistant — Dialogflow CX

A support assistant for an ISP, built on Dialogflow CX. It handles
connectivity troubleshooting, outage checks through a webhook, and
ticket status lookups through a webhook, with interruption handling and
proper failure recovery.

## What is in here

```
.
├── README.md
├── architecture.md               (flow diagram and design decisions)
├── answers.md                    (technical design question answers)
├── dialogflow_cx_agent/
│   ├── build_agent.py            (builds the agent through the CX API)
│   └── requirements.txt
├── exported_agent_ISP Customer Support Assistant.zip
└── webhook/
    ├── app.py
    ├── services/
    │   ├── outage_service.py
    │   └── ticket_service.py
    ├── tests/
    ├── requirements.txt
    └── .env.example
```

## How to run the webhook

```bash
cd webhook
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

This starts the webhook at `http://localhost:8080/webhook`. Check it is
running with `curl http://localhost:8080/healthz`, which should return
`{"status": "ok"}`.

Dialogflow CX needs an HTTPS URL, not localhost, so during development I
expose it with ngrok:

```bash
ngrok http 8080
```

Use the ngrok URL as the webhook URI, either in the CX console under
Manage, Webhooks, or as `WEBHOOK_URL` in `build_agent.py`.

## How to configure or import the agent

Two options:

**Import the export directly.** `exported_agent_ISP Customer Support
Assistant.zip` is a full export of the finished agent. In the CX
console, go to the agent selector, choose Import, and select the zip.
This gives you the exact final state right away.

**Or run the build script.** `dialogflow_cx_agent/build_agent.py`
creates the whole agent from scratch through the Python client. Set
`PROJECT_ID` and `WEBHOOK_URL` at the top of the file, then:

```bash
cd dialogflow_cx_agent
pip install -r requirements.txt
gcloud auth application-default login
python build_agent.py
```

The script is useful because it is reviewable and version controlled,
unlike a raw export file. It also acts as the answer to the deployment
question in `answers.md`. Note that it is not built to run twice on the
same project, running it again will create duplicate flows.

## Required environment variables

Webhook (`webhook/.env`):

| Variable | Required | Purpose |
|---|---|---|
| `PORT` | No, defaults to 8080 | local port |
| `LOG_LEVEL` | No | logging level |
| `WEBHOOK_SHARED_SECRET` | No | if set, requests must include a matching `X Webhook Secret` header |

Agent build script (set directly in `build_agent.py`): `PROJECT_ID`,
`LOCATION`, `WEBHOOK_URL`, `WEBHOOK_SHARED_SECRET`.

## How to run tests

```bash
cd webhook
python -m pytest tests/ -v
```

22 tests total. They cover the outage service (normal lookup, unknown
zip, invalid zip, and the three simulated failures), the ticket service
(normal lookup, not found, invalid ID, simulated failure), and the Flask
layer end to end (correct session parameters, correct status codes,
correct fallback messages).

## Architectural decisions

Full detail and diagram are in [architecture.md](./architecture.md). In
short: each customer journey (Troubleshooting, Outage Check, Ticket
Status) has its own flow, with a thin Default Start Flow that only
routes based on intent. This keeps each journey's logic separate and
easy to change on its own. Session parameters only ever hold what the
current conversation needs, and the webhook keeps Dialogflow parsing
separate from the actual business logic in `services/`.

## Interruption and resumption approach

A route group called Global Interruptions is attached at the
Troubleshooting flow level, not on one page, so the outage check intent
works from any page inside that flow. Troubleshooting's session
parameters stay intact while this happens, since CX keeps session state
across flows automatically. If no outage is found, the user returns to
where they left off in Troubleshooting. If an outage is found, the
conversation exits Troubleshooting and goes to Escalate instead, since
continuing to troubleshoot would not help at that point.

## Composite input handling (the cognitive requirement)

The client asked for a case where one message already answers several
troubleshooting questions at once, for example saying the modem was
already restarted and both LAN and Wifi were already tested. In that
case, the agent should skip the remaining questions and go straight to
escalation.

This is built using intent matching rather than open ended reasoning, on
purpose, so it stays predictable and testable. A new intent called
`report.connectivity_issue.exhausted` is trained on this kind of
composite message. When it matches, it sets a session parameter,
`skip_to_escalate = true`. A route at the top of the Troubleshooting
flow checks this parameter before the normal questions run, and sends
the user straight to Escalate if it is set. The Escalate message itself
also changes in this case, acknowledging what the user already tried
instead of showing the normal escalation text.

A normal short message like "my internet is not working" does not match
this intent, so the full step by step flow still runs as before.

## Technical design questions

Answered in full in [answers.md](./answers.md).

## Production considerations

What I would monitor:

* Webhook latency and error rate, alerting if response times get close
  to the CX timeout.
* No match rate, broken down by intent and page.
* Where conversations get abandoned, meaning they end outside a
  Resolved or Escalated page.
* Task completion rate, meaning how many sessions reach a defined
  success page.
* Escalation rate over time, and whether a rise is from a real issue or
  from the composite input logic firing too often.

Credentials and secrets, such as the webhook shared secret and any
downstream API keys, should live in a secret manager and be injected as
environment variables, never committed or logged.

Sensitive customer information should be limited to what the current
journey needs, such as a zip code or ticket ID. Raw values should not be
logged at info level in production.

For webhook authentication, the shared secret used here is a minimum. In
a real deployment I would use CX's built in service account webhook
authentication instead, so no static secret needs to exist at all.

For logging, I would use structured logs with a request ID and avoid
writing raw customer data into log lines, along with a retention policy
matching whatever privacy rules apply.

## Known limitations

* The backend is simulated with in memory data and manual failure flags
  (`simulate="timeout"`, `"5xx"`, `"malformed"`), not a real system.
* `build_agent.py` is not safe to run twice against the same project.
* A couple of pages use inline conditional responses for brevity, rather
  than fully separate response blocks.
* The webhook runs locally through ngrok, there is no cloud deployment,
  which the assignment allows.
* The composite input detection only covers phrasing close to what it
  was trained on. It will not catch every possible way someone could
  describe having already tried everything.

## Demo

Video: **https://share.vidyard.com/watch/1j9g3h3agoqi7FzHxzTZqA**

Shows the composite input example going straight to Escalate, a
simulated backend failure with graceful recovery, and short clips of a
normal resolved troubleshooting run, an outage check, and one
interruption.
