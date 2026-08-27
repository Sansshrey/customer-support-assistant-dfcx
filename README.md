
Rough as in — this is the shape, not a formal UML export. The exported
agent zip has the exact pages, routes, and conditions if you need the
precise version.

## Interruption handling

There's a route group called "Global Interruptions" attached at the
Troubleshooting flow level, not on any individual page, so `check.outage`
can fire no matter where you are inside that flow — mid router-status
question, looking at a recommendation, wherever. Attaching it per-page
would mean re-adding it every time I added a page, and I'd inevitably
forget one.

When it fires, Troubleshooting's own session params don't get touched —
CX keeps session parameters around across flows in the same session
automatically, so nothing gets lost just by hopping over to Outage Check.
No Outage sends the user back into Troubleshooting where they left off;
Outage Found ends the troubleshooting attempt outright, since there's not
much point continuing to ask about router lights if there's a confirmed
outage in the area. That's the "resume or exit, whichever makes sense"
behavior the assignment asked for.

## Composite-input handling (the "cognitive" requirement)

This came in as a follow-up from the client after the original build was
basically done. The ask: if someone says something like

> "My internet is not working. I've already restarted the modem and my
> laptop, and tried both LAN and Wi-Fi, still broken."

— i.e. one message that already answers both the device-scope and
router-status questions — the agent shouldn't make them repeat all that.
It should skip straight to escalation and acknowledge what they already
tried.

I didn't want to reach for anything generative here — partly because it's
genuinely out of scope for a standard CX agent, and partly because I'd
rather ship something deterministic I can actually demo working the same
way twice. So it's built as:

- a new intent, `report.connectivity_issue.exhausted`, trained on phrasing
  that describes multiple completed troubleshooting steps in one message
- matching it sets a session parameter, `skip_to_escalate = true`
- at the top of Troubleshooting's entry routing — before the normal
  catch-all into Collect Device Scope — there's a route that checks that
  parameter and sends things straight to Escalate if it's set
- Escalate's message is conditional on that same parameter: if it's set,
  it acknowledges the steps already taken instead of the generic
  escalation line

A plain "my internet isn't working" doesn't match that intent, so it
falls through to the normal catch-all and runs the full Q&A exactly like
before — this only kicks in when the composite pattern is actually there.

Worth saying plainly: this is pattern matching against training phrases,
not the model reasoning about the conversation. That's a real limitation
— it'll handle the documented example and things phrased similarly, but
won't generalize to every possible way someone could describe having
already tried everything. Trade-off I made on purpose, and I'd rather be
upfront about it than have it look like more than it is.

## Technical design questions

**Why this flow/page structure?**
Mainly explained above — one flow per journey keeps each conversation's
state and routing self-contained, and the thin start flow means adding a
fourth or fifth journey later doesn't mean touching the existing three.

**What goes in session parameters vs. backend storage?**
Session params: whatever the current turn needs to make its next
decision — device scope, router status, the ticket ID somebody just gave.
Backend storage: anything that needs to outlive the conversation or be
looked up independently of it — actual outage records, actual ticket
data, anything that counts as a customer's real account information.
Session state is disposable by design; if the session ends, nothing of
record should be lost with it.

**How would this scale to 100+ journeys?**
Honestly, I wouldn't keep it as one growing pile of flows in one agent —
I'd split by domain (billing, connectivity, account, etc.) potentially
across multiple agents or at least clearly namespaced flow groups, with a
routing layer in front that classifies broad intent first and only then
hands off to the specific flow. Shared logic (auth checks, common
escalation, logging) would need to live somewhere flows can call into
rather than getting copy-pasted across 100 flows.

**How would you version and deploy this safely?**
Treat `build_agent.py` (or an equivalent declarative definition) as the
source of truth, not the console. Changes go through a normal PR/review
process, get applied to a staging agent first, get tested there, then
promoted. CX supports versions/environments natively — I'd use a
"staging" environment for anything unverified and only point production
traffic at a version once it's been through real testing, with an easy
rollback to the prior version if something regresses.

**No-match rate suddenly spikes after a release — how do you investigate?**
First thing I'd check is whether it's every intent or concentrated on a
few — that alone tells you if it's a broad regression (webhook down,
routing broken) or something narrower (one flow's training phrases got
touched). Then compare timing against the release itself and against any
NLU model retraining that might have happened independently. If it's
concentrated, pull actual transcripts from around the spike and see what
users are actually typing that isn't matching — usually it's either a
wording pattern nobody trained for, or a route that got reordered/removed
in the release.

## What I'd watch in production, and how I'd handle sensitive stuff

Latency and error rate per webhook tag, alerting if p95 gets anywhere
near the CX webhook timeout. No-match rate per intent and per page, since
a jump usually means either a training gap or something broke in a
recent release. Where conversations die — which page people abandon at —
bucketed so it's obvious if one particular step is the problem.
Completion rate against a defined "success" page per journey. And
escalation rate over time, since a sustained rise there might mean an
actual service issue rather than a bot problem, or conversely might mean
the composite-input logic above is misfiring somewhere.

On the security side: no secrets in code, ever — webhook secret and any
downstream API keys belong in Secret Manager or equivalent, injected at
deploy time. Don't collect more customer data than the active journey
needs. Don't log raw parameter values at INFO in prod — hash or truncate
identifiers, save full detail for DEBUG in non-prod only. The
shared-secret header this webhook uses is a floor, not a ceiling — a real
deployment should lean on CX's built-in service-account webhook auth
instead, so there's no static secret sitting around to leak in the first
place.

## Known limitations

- The "backend" is in-memory fake data plus explicit failure flags
  (`simulate="timeout"/"5xx"/"malformed"`), not a real ISP system —
  enough to prove the error-handling paths work without standing up real
  infra.
- `build_agent.py` isn't idempotent. Re-run it against an agent that
  already exists and you'll get duplicates, not an update.
- A couple of pages use CX's conditional-response syntax inline rather
  than as separate per-value response blocks, mostly for brevity — in a
  real console build I'd split those out.
- Nothing here is deployed to Cloud Run or anywhere else — running the
  webhook locally via ngrok is explicitly allowed by the assignment, so
  that's what this is.
- The composite-input detection is intent/pattern-based, so it's solid
  for the documented example and close variants, but it's not going to
  catch every conceivable phrasing of "I already tried everything" —
  that would need either a lot more training phrases over time or a
  genuinely different approach.

## Demo

Video: **[add link here]**

Covers the composite-input example above skipping straight to Escalate,
a simulated backend timeout with graceful recovery, and quick passes
through a normal resolved troubleshooting run, an outage check, and one
interruption mid-flow.
