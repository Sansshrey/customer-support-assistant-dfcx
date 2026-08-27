# Technical Design Questions

### Q1 — Why did you choose your Flow/Page structure?

One flow per customer journey (Troubleshooting, Outage Check, Ticket
Status), with a thin Default Start Flow that only routes on intent. This
isolates each journey's pages/parameters/fulfillment so it can be
iterated on independently, keeps the interruption logic (a flow-level
route group) reusable across every page of a flow instead of duplicated
per page, and scales cleanly as more journeys are added — see Q3.

### Q2 — What should live in session parameters vs. backend storage?

**Session parameters** (Dialogflow CX): anything needed to drive the
*current* conversation's routing and phrasing — `device_scope`,
`router_status`, `zip_code`, `ticket_id`, and the transient results of a
webhook call (`outage_found`, `outage_eta`, `ticket_status`,
`*_lookup_status`). These are short-lived, scoped to the session, and
disappear when the session ends — they're conversational working memory,
not records.

**Backend storage** (the ISP's own systems, behind the webhook): the
actual ticket record, its full history/notes, customer account and
contact details, outage incident data, and any audit trail of what the
assistant did on the customer's behalf (e.g. "escalated ticket X for
customer Y at time Z"). Anything that needs to outlive the conversation,
be queried later, or feed reporting/analytics belongs in backend storage,
not in Dialogflow CX session state — CX is not a system of record.

### Q3 — How would you structure this for 100+ customer journeys?

- **Group flows by domain**, not one-flow-per-micro-intent — e.g. a
  "Billing" flow with multiple pages/journeys inside it, rather than 20
  billing-related top-level flows. Keeps the flow list navigable.
- **Push routing logic into route groups and page groups** shared across
  domains (auth checks, "talk to a human" escalation, common
  clarification patterns) instead of re-implementing them per flow.
- **Split webhooks by domain service**, not one monolith Flask app —
  e.g. separate deployable services for billing, connectivity, and
  account management, each independently scalable and ownable by a
  different team.
- **Invest in a shared entity/intent library** and naming convention
  early (e.g. `domain.action` intent names as used here) so 100+ journeys
  don't collide or duplicate near-identical intents.
- **Treat the agent config as code** (as `build_agent.py` does here) so
  changes go through the same review/test process as the webhook, rather
  than being manual, undocumented console edits.

### Q4 — How would you safely version and deploy CX and webhook changes?

- **Webhook**: normal software deploy pipeline — version-controlled,
  tested (as in `webhook/tests/`), deployed behind a versioned URL or
  with blue/green revisions (e.g. Cloud Run revisions with gradual
  traffic shifting), so a bad deploy can be rolled back by shifting
  traffic back to the previous revision.
- **Dialogflow CX agent**: use CX **environments** (e.g. `draft` →
  `staging` → `production`) with **versions** — build and test changes in
  draft, cut a version, promote it to staging for scripted/manual
  regression testing, then promote the same version to production. Never
  edit production's live draft directly.
- **Config as code**: keep the agent build script (or an exported
  agent JSON) in the same repo as the webhook, so a CX change and the
  webhook change it depends on (e.g. a new tag) are reviewed and released
  together, avoiding a webhook expecting a tag the agent doesn't send yet
  (or vice versa).
- **Canary by traffic percentage** where the platform supports it (CX
  environments support experiment/version traffic splitting) to validate
  a new version on a small percentage of real traffic before full
  rollout.

### Q5 — No-match rate suddenly increases after a release — how do you investigate?

1. **Correlate the timing** — confirm the spike started right at (or
   shortly after) the release, not from an unrelated cause (marketing
   push driving unusual traffic, a webhook outage causing users to
   rephrase, etc.).
2. **Check what changed in the release** — new/edited intents,
   training phrases, entity types, or a webhook contract change that
   silently altered what the agent can now match.
3. **Break down no-match by flow/page and by intent** — a spike
   concentrated in one flow points at that flow's recent changes; a
   broad spike across all flows points at something more systemic (NLU
   model update, agent-wide setting change, or a webhook failure
   producing a bad fallback loop that looks like no-match).
4. **Sample actual no-matched utterances** — read a batch of them to see
   if there's a real language/phrasing pattern the training phrases
   don't cover (e.g. a new device name, new slang) vs. users bumping into
   a broken feature and asking around it.
5. **Check webhook health for the same window** — a webhook outage or
   change to its response format can indirectly cause no-matches if a
   page loops back into asking the same question ineffectively.
6. **Roll back if it's a bad release**, or ship a targeted training-phrase
   fix if it's a genuine language gap — then confirm the no-match rate
   returns to baseline before closing the incident.
