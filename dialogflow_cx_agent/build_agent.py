from google.cloud import dialogflowcx_v3 as cx

# ----------------------------- CONFIG ------------------------------
PROJECT_ID = "cs-project-lpfner8m"
LOCATION = "global"  
WEBHOOK_URL = "https://8080-cs-79540aba-61ce-45b0-9231-27d46398a6cc.cs-asia-southeast1-seal.cloudshell.dev/webhook"
WEBHOOK_SHARED_SECRET = ""  
AGENT_DISPLAY_NAME = "ISP Customer Support Assistant"
TIME_ZONE = "Asia/Kolkata"


client_options = {"api_endpoint": f"{LOCATION}-dialogflow.googleapis.com"} if LOCATION != "global" else None


def create_agent():
    client = cx.AgentsClient(client_options=client_options)
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
    agent = cx.Agent(
        display_name=AGENT_DISPLAY_NAME,
        default_language_code="en",
        time_zone=TIME_ZONE,
        description=(
            "Customer support assistant for an ISP: connectivity troubleshooting, "
            "outage checks, and ticket status lookups."
        ),
    )
    created = client.create_agent(parent=parent, agent=agent)
    print(f"Created agent: {created.name}")
    return created


def create_webhook(agent_name):
    client = cx.WebhooksClient(client_options=client_options)
    headers = {}
    if WEBHOOK_SHARED_SECRET:
        headers["X-Webhook-Secret"] = WEBHOOK_SHARED_SECRET
    webhook = cx.Webhook(
        display_name="isp-support-webhook",
        generic_web_service=cx.Webhook.GenericWebService(
            uri=WEBHOOK_URL,
            request_headers=headers,
        ),
        timeout={"seconds": 8},  # keep below CX's own webhook timeout ceiling
        disabled=False,
    )
    created = client.create_webhook(parent=agent_name, webhook=webhook)
    print(f"Created webhook: {created.name}")
    return created


def create_entity_types(agent_name):
    client = cx.EntityTypesClient(client_options=client_options)
    results = {}

    device_scope = cx.EntityType(
        display_name="device_scope",
        kind=cx.EntityType.Kind.KIND_MAP,
        entities=[
            cx.EntityType.Entity(value="single", synonyms=["single", "one device", "just my laptop", "just my phone", "only one"]),
            cx.EntityType.Entity(value="multiple", synonyms=["multiple", "all devices", "everything", "every device", "all of them"]),
        ],
    )
    results["device_scope"] = client.create_entity_type(parent=agent_name, entity_type=device_scope)

    router_status = cx.EntityType(
        display_name="router_status",
        kind=cx.EntityType.Kind.KIND_MAP,
        entities=[
            cx.EntityType.Entity(value="normal", synonyms=["green", "solid green", "normal", "on", "steady light", "white light"]),
            cx.EntityType.Entity(value="abnormal", synonyms=["red", "blinking red", "flashing", "off", "no lights", "orange"]),
        ],
    )
    results["router_status"] = client.create_entity_type(parent=agent_name, entity_type=router_status)

    ticket_id = cx.EntityType(
        display_name="ticket_id",
        kind=cx.EntityType.Kind.KIND_REGEXP,
        entities=[cx.EntityType.Entity(value=r"INC-?\d{4,8}", synonyms=[r"INC-?\d{4,8}"])],
        enable_fuzzy_extraction=False,
    )
    results["ticket_id"] = client.create_entity_type(parent=agent_name, entity_type=ticket_id)

    for name, et in results.items():
        print(f"Created entity type '{name}': {et.name}")
    return results


def _training_phrase(*parts_text, entity_types_by_value=None):
    """parts_text: list of (text, entity_type_id_or_None) tuples."""
    parts = []
    for text, entity_type in parts_text:
        if entity_type:
            parts.append(cx.Intent.TrainingPhrase.Part(text=text, parameter_id=entity_type))
        else:
            parts.append(cx.Intent.TrainingPhrase.Part(text=text))
    return cx.Intent.TrainingPhrase(parts=parts, repeat_count=1)


def create_intents(agent_name, entity_types):
    client = cx.IntentsClient(client_options=client_options)
    intents = {}

    def make_intent(display_name, phrases, parameters=None):
        intent = cx.Intent(
            display_name=display_name,
            training_phrases=[cx.Intent.TrainingPhrase(parts=[cx.Intent.TrainingPhrase.Part(text=p)], repeat_count=1) for p in phrases],
            parameters=parameters or [],
        )
        created = client.create_intent(parent=agent_name, intent=intent)
        print(f"Created intent '{display_name}': {created.name}")
        intents[display_name] = created
        return created

    make_intent("report.connectivity_issue", [
        "My internet isn't working",
        "The internet is down",
        "I have no internet connection",
        "My wifi is not working",
        "The router light is blinking red",
        "I can't connect to the internet",
    ])

    make_intent("check.outage", [
        "Is there an outage in my area?",
        "Is there an outage near me?",
        "Is the internet down in my area",
        "outage check",
        "Are there any known outages?",
    ])

    make_intent("check.ticket_status", [
        "What's happening with INC-10291?",
        "Check ticket INC-10291",
        "Status of my ticket",
        "What is the status of INC-10450",
        "Can you check my support ticket?",
    ])

    make_intent("confirm.yes", ["yes", "yeah", "it's fixed", "that worked", "resolved", "it's working now"])
    make_intent("confirm.no", ["no", "still not working", "that didn't help", "nope", "still broken"])

    return intents


def create_flows_and_pages(agent_name, webhook, intents, entity_types):
    flows_client = cx.FlowsClient(client_options=client_options)
    pages_client = cx.PagesClient(client_options=client_options)

    # --- Get the Default Start Flow (already exists on every agent) ---
    start_flows = list(flows_client.list_flows(parent=agent_name))
    default_start_flow = next(f for f in start_flows if f.display_name == "Default Start Flow")

    # ============ TROUBLESHOOTING FLOW ============
    troubleshooting_flow = flows_client.create_flow(
        parent=agent_name,
        flow=cx.Flow(display_name="Connectivity Troubleshooting"),
    )
    print(f"Created flow: {troubleshooting_flow.name}")

    page_device_scope = pages_client.create_page(
        parent=troubleshooting_flow.name,
        page=cx.Page(
            display_name="Collect Device Scope",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(
                    text=["Is this affecting just one device, or all of your devices?"]))
            ]),
        ),
    )

    page_router_status = pages_client.create_page(
        parent=troubleshooting_flow.name,
        page=cx.Page(
            display_name="Collect Router Status",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(
                    text=["Are you seeing any warning lights on your router — is it solid green, or red/blinking?"]))
            ]),
        ),
    )

    page_recommendation = pages_client.create_page(
        parent=troubleshooting_flow.name,
        page=cx.Page(
            display_name="Give Recommendation",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(text=[
                    "$session.params.router_status = abnormal -> Please power-cycle your router: "
                    "unplug it for 10 seconds, then plug it back in and wait 2 minutes. "
                    "$session.params.router_status = normal -> Let's try restarting the device "
                    "that's having trouble and reconnecting to wifi."
                ])),
                cx.ResponseMessage(text=cx.ResponseMessage.Text(
                    text=["Did that resolve the issue?"]))
            ]),
        ),
    )

    page_escalate = pages_client.create_page(
        parent=troubleshooting_flow.name,
        page=cx.Page(
            display_name="Escalate",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(
                    text=["I'll need to escalate this to our support team. I'm opening a ticket for you now."]))
            ]),
        ),
    )

    page_resolved = pages_client.create_page(
        parent=troubleshooting_flow.name,
        page=cx.Page(
            display_name="Resolved",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(
                    text=["Glad that's sorted! Anything else I can help with?"]))
            ]),
        ),
    )

    # Troubleshooting flow: start page routes into device scope collection,
    # then a linear chain with conditional routing at the recommendation step.
    troubleshooting_flow.transition_routes = [
        cx.TransitionRoute(condition="true", target_page=page_device_scope.name),
    ]
    flows_client.update_flow(flow=troubleshooting_flow, update_mask={"paths": ["transition_routes"]})

    page_device_scope.transition_routes = [
        cx.TransitionRoute(condition="true", target_page=page_router_status.name),
    ]
    pages_client.update_page(page=page_device_scope, update_mask={"paths": ["transition_routes"]})

    page_router_status.transition_routes = [
        cx.TransitionRoute(condition="true", target_page=page_recommendation.name),
    ]
    pages_client.update_page(page=page_router_status, update_mask={"paths": ["transition_routes"]})

    page_recommendation.transition_routes = [
        cx.TransitionRoute(intent=intents["confirm.yes"].name, target_page=page_resolved.name),
        cx.TransitionRoute(intent=intents["confirm.no"].name, target_page=page_escalate.name),
    ]
    pages_client.update_page(page=page_recommendation, update_mask={"paths": ["transition_routes"]})

    # ---- INTERRUPTION HANDLING ----
    # A route group attached at the FLOW level (not a single page) means
    # "is there an outage?" is reachable from every page inside this flow.
    # target_flow points at Outage Check; we rely on session parameters
    # (see app.py / README) to remember where troubleshooting left off so
    # we can route back to the same page afterward instead of restarting.
    route_groups_client = cx.TransitionRouteGroupsClient(client_options=client_options)
    interruption_group = route_groups_client.create_transition_route_group(
        parent=troubleshooting_flow.name,
        transition_route_group=cx.TransitionRouteGroup(
            display_name="Global Interruptions",
            transition_routes=[
                cx.TransitionRoute(
                    intent=intents["check.outage"].name,
                    # target_flow set below once Outage Check flow exists
                    target_page=page_recommendation.name,
                ),
            ],
        ),
    )
    print(f"Created route group: {interruption_group.name}")

    # ============ OUTAGE CHECK FLOW ============
    outage_flow = flows_client.create_flow(
        parent=agent_name,
        flow=cx.Flow(display_name="Outage Check"),
    )
    print(f"Created flow: {outage_flow.name}")

    page_collect_zip = pages_client.create_page(
        parent=outage_flow.name,
        page=cx.Page(
            display_name="Collect Zip",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(text=["What's your ZIP or postal code?"]))
            ]),
            form=cx.Form(parameters=[
                cx.Form.Parameter(
                    display_name="zip_code",
                    entity_type="projects/-/locations/-/agents/-/entityTypes/sys.zip-code",
                    required=True,
                    fill_behavior=cx.Form.Parameter.FillBehavior(
                        initial_prompt_fulfillment=cx.Fulfillment(messages=[
                            cx.ResponseMessage(text=cx.ResponseMessage.Text(text=["What's your ZIP or postal code?"]))
                        ])
                    ),
                )
            ]),
        ),
    )

    page_call_outage_webhook = pages_client.create_page(
        parent=outage_flow.name,
        page=cx.Page(
            display_name="Call Outage Webhook",
            entry_fulfillment=cx.Fulfillment(
                webhook=webhook.name,
                tag="check-outage",
            ),
        ),
    )

    page_outage_found = pages_client.create_page(
        parent=outage_flow.name,
        page=cx.Page(
            display_name="Outage Found",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(text=[
                    "Yes — there's a known outage in $session.params.outage_area, "
                    "expected to be resolved by $session.params.outage_eta."
                ]))
            ]),
        ),
    )

    page_no_outage = pages_client.create_page(
        parent=outage_flow.name,
        page=cx.Page(
            display_name="No Outage",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(text=[
                    "No reported outages in that area — let's look at what might be "
                    "happening with your specific connection instead."
                ]))
            ]),
        ),
    )

    outage_flow.transition_routes = [
        cx.TransitionRoute(condition="true", target_page=page_collect_zip.name),
    ]
    flows_client.update_flow(flow=outage_flow, update_mask={"paths": ["transition_routes"]})

    page_collect_zip.transition_routes = [
        cx.TransitionRoute(condition="$page.params.status = \"FINAL\"", target_page=page_call_outage_webhook.name),
    ]
    pages_client.update_page(page=page_collect_zip, update_mask={"paths": ["transition_routes"]})

    page_call_outage_webhook.transition_routes = [
        cx.TransitionRoute(condition="$session.params.outage_found = true", target_page=page_outage_found.name),
        cx.TransitionRoute(condition="$session.params.outage_found = false", target_page=page_no_outage.name),
        cx.TransitionRoute(
            condition="$session.params.outage_lookup_status != \"ok\"",
            target_page=page_collect_zip.name,  # simple retry loop on any failure status
        ),
    ]
    pages_client.update_page(page=page_call_outage_webhook, update_mask={"paths": ["transition_routes"]})

    # Now that Outage Check flow exists, point the interruption route group at it,
    # and point No Outage back to the troubleshooting resume page.
    interruption_group.transition_routes[0].target_flow = outage_flow.name
    route_groups_client.update_transition_route_group(
        transition_route_group=interruption_group,
        update_mask={"paths": ["transition_routes"]},
    )
    # Attach the route group to the troubleshooting flow so it's globally reachable there.
    troubleshooting_flow.transition_route_groups = [interruption_group.name]
    flows_client.update_flow(flow=troubleshooting_flow, update_mask={"paths": ["transition_route_groups"]})

    page_no_outage.transition_routes = [
        # Resume troubleshooting: route back into the flow. In the console,
        # set this target to whichever troubleshooting page the session was
        # on before interruption — see README for the $session.params
        # approach to tracking "current step".
        cx.TransitionRoute(condition="true", target_flow=troubleshooting_flow.name),
    ]
    pages_client.update_page(page=page_no_outage, update_mask={"paths": ["transition_routes"]})

    # ============ TICKET STATUS FLOW ============
    ticket_flow = flows_client.create_flow(
        parent=agent_name,
        flow=cx.Flow(display_name="Ticket Status"),
    )
    print(f"Created flow: {ticket_flow.name}")

    page_collect_ticket = pages_client.create_page(
        parent=ticket_flow.name,
        page=cx.Page(
            display_name="Collect Ticket ID",
            form=cx.Form(parameters=[
                cx.Form.Parameter(
                    display_name="ticket_id",
                    entity_type=entity_types["ticket_id"].name,
                    required=True,
                    fill_behavior=cx.Form.Parameter.FillBehavior(
                        initial_prompt_fulfillment=cx.Fulfillment(messages=[
                            cx.ResponseMessage(text=cx.ResponseMessage.Text(
                                text=["What's the ticket ID? (e.g. INC-10291)"]))
                        ])
                    ),
                )
            ]),
        ),
    )

    page_call_ticket_webhook = pages_client.create_page(
        parent=ticket_flow.name,
        page=cx.Page(
            display_name="Call Ticket Webhook",
            entry_fulfillment=cx.Fulfillment(webhook=webhook.name, tag="get-ticket-status"),
        ),
    )

    page_show_ticket_status = pages_client.create_page(
        parent=ticket_flow.name,
        page=cx.Page(
            display_name="Show Ticket Status",
            entry_fulfillment=cx.Fulfillment(messages=[
                cx.ResponseMessage(text=cx.ResponseMessage.Text(text=[
                    "Ticket $session.params.ticket_id is currently "
                    "$session.params.ticket_status, with an estimated resolution "
                    "of $session.params.ticket_eta."
                ]))
            ]),
        ),
    )

    ticket_flow.transition_routes = [
        cx.TransitionRoute(condition="true", target_page=page_collect_ticket.name),
    ]
    flows_client.update_flow(flow=ticket_flow, update_mask={"paths": ["transition_routes"]})

    page_collect_ticket.transition_routes = [
        cx.TransitionRoute(condition="$page.params.status = \"FINAL\"", target_page=page_call_ticket_webhook.name),
    ]
    pages_client.update_page(page=page_collect_ticket, update_mask={"paths": ["transition_routes"]})

    page_call_ticket_webhook.transition_routes = [
        cx.TransitionRoute(condition="$session.params.ticket_lookup_status = \"ok\"", target_page=page_show_ticket_status.name),
        cx.TransitionRoute(
            condition="$session.params.ticket_lookup_status != \"ok\"",
            target_page=page_collect_ticket.name,
        ),
    ]
    pages_client.update_page(page=page_call_ticket_webhook, update_mask={"paths": ["transition_routes"]})

    # ============ WIRE UP MAIN / ROUTING (Default Start Flow) ============
    default_start_flow.transition_routes.extend([
        cx.TransitionRoute(intent=intents["report.connectivity_issue"].name, target_flow=troubleshooting_flow.name),
        cx.TransitionRoute(intent=intents["check.outage"].name, target_flow=outage_flow.name),
        cx.TransitionRoute(intent=intents["check.ticket_status"].name, target_flow=ticket_flow.name),
    ])
    flows_client.update_flow(flow=default_start_flow, update_mask={"paths": ["transition_routes"]})

    print("\nAll flows wired up. Open the CX console to review pages/routes visually.")


def main():
    agent = create_agent()
    webhook = create_webhook(agent.name)
    entity_types = create_entity_types(agent.name)
    intents = create_intents(agent.name, entity_types)
    create_flows_and_pages(agent.name, webhook, intents, entity_types)
    print(f"\nDone. Agent console URL:\n"
          f"https://dialogflow.cloud.google.com/cx/projects/{PROJECT_ID}/locations/{LOCATION}/agents/"
          f"{agent.name.split('/')[-1]}")


if __name__ == "__main__":
    main()
