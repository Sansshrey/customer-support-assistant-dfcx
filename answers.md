# Technical Design Questions

### Q1 Why did you choose your Flow/Page structure?

Each customer journey (Troubleshooting, Outage Check, Ticket Status) gets
its own flow, with a small Default Start Flow that just routes based on
intent. They don't share much data, so keeping them separate keeps each
one easy to read and change without breaking the others. It also let me
add the outage interruption once at the flow level instead of repeating
it on every page. Adding a new journey later just means adding a new
flow, not touching the existing ones.

### Q2 What should live in session parameters vs. backend storage?

**Session parameters** hold what the current conversation needs right
now: `device_scope`, `router_status`, `zip_code`, `ticket_id`, and
webhook results like `outage_found` or `ticket_status`. This is short
term and disappears when the session ends, which is fine since it's not
meant to be a record of anything.

**Backend storage** holds the real data: the actual ticket, customer
account info, outage records, and a log of what the assistant did on the
customer's behalf. Anything that needs to exist after the chat ends or
get looked up later belongs there, not in Dialogflow CX.

### Q3 How would you structure this for 100+ customer journeys?

* Group flows by domain (Billing, Connectivity, Accounts) instead of one
  flow per tiny journey, so the flow list stays manageable.
* Put repeated logic (auth checks, escalation, common fallback handling)
  into shared route groups instead of rebuilding it in every flow.
* Split the webhook by domain too, so each service can scale and be
  owned by a different team.
* Keep a consistent naming pattern for intents (like `domain.action`
  here) so things don't get duplicated by accident.
* Treat the agent as code, same as `build_agent.py` does now, so changes
  go through review and testing like the webhook does.

### Q4 How would you safely version and deploy CX and webhook changes?

For the webhook, it is a normal deploy pipeline: version control, tests,
and something like Cloud Run revisions so traffic can shift gradually
and roll back if needed.

For the CX agent, use environments (draft, staging, production) with
versions. Build and test in draft, cut a version, test it in staging,
then promote the same version to production. Never edit production's
draft directly.

Keep the agent definition in the same repo as the webhook so related
changes get reviewed and released together. Where possible, send a new
version to a small percentage of traffic first before full rollout.

### Q5 A release causes the no match rate to jump. How do you investigate?

1. Check if the timing lines up with the release, not something
   unrelated like a traffic spike or webhook outage.
2. Look at what changed in that release: intents, training phrases,
   entities, or the webhook response format.
3. Break the no match numbers down by flow and intent. One flow affected
   points to that flow's changes; a broad spike points to something
   bigger, like an NLU update or a webhook issue.
4. Read a sample of the actual no matched messages to see if it is a
   real phrasing gap or people reacting to something broken.
5. Check webhook health for the same window, since a webhook problem can
   look like a no match issue from the outside.
6. Roll back if the release caused it, or add training phrases if it is
   a real gap, then confirm the rate drops back to normal.
