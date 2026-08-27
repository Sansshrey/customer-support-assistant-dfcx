import logging
import os

from flask import Flask, jsonify, request

from services.outage_service import (
    InvalidZipError,
    OutageServiceTimeout,
    OutageServiceUnavailable,
    check_outage,
)
from services.ticket_service import (
    InvalidTicketIdError,
    TicketNotFoundError,
    TicketServiceUnavailable,
    get_ticket_status,
)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("webhook")

app = Flask(__name__)

WEBHOOK_SHARED_SECRET = os.environ.get("WEBHOOK_SHARED_SECRET")


def _extract_params(req_json: dict) -> dict:
    return (
        req_json.get("sessionInfo", {}).get("parameters", {})
        or {}
    )


def _session_params_response(params: dict, tag: str) -> dict:
    """Build a minimal, valid DFCX WebhookResponse that only sets
    session parameters. Response *text* for the happy path is left to
    DFCX fulfillment messages that reference these parameters — this
    keeps conversational copy editable by non-engineers in the CX
    console instead of being hardcoded in Python."""
    return jsonify({
        "sessionInfo": {"parameters": params},
    })


def _error_response(params: dict, message_text: str):
    """Build a WebhookResponse that both sets an error flag param AND
    supplies fulfillment text directly — used for failure paths so the
    recovery message is guaranteed even if the CX page's static
    responses aren't configured for that branch."""
    payload = {
        "sessionInfo": {"parameters": params},
        "fulfillmentResponse": {
            "messages": [
                {"text": {"text": [message_text]}}
            ]
        },
    }
    return jsonify(payload)


@app.before_request
def _check_shared_secret():
    if WEBHOOK_SHARED_SECRET is None:
        return  # not configured locally; skip
    if request.path == "/healthz":
        return
    provided = request.headers.get("X-Webhook-Secret")
    if provided != WEBHOOK_SHARED_SECRET:
        logger.warning("Rejected webhook call: bad/missing shared secret")
        return jsonify({"error": "unauthorized"}), 401


@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["POST"])
def webhook():
    req_json = request.get_json(silent=True)
    if not req_json:
        logger.error("Received non-JSON or empty webhook request")
        return jsonify({"error": "invalid request body"}), 400

    tag = req_json.get("fulfillmentInfo", {}).get("tag")
    logger.info("Webhook called", extra={"tag": tag})

    if tag == "check-outage":
        return _handle_outage_check(req_json)
    if tag == "get-ticket-status":
        return _handle_ticket_status(req_json)

    logger.warning("Unknown fulfillment tag received", extra={"tag": tag})
    return jsonify({"error": f"no handler for tag '{tag}'"}), 400


def _handle_outage_check(req_json: dict):
    params = _extract_params(req_json)
    zip_code = params.get("zip_code")
    # Only present in dev/test — lets you force a failure path by
    # sending a debug session parameter from the DFCX simulator.
    simulate = params.get("__simulate_failure")

    try:
        result = check_outage(zip_code, simulate=simulate)
    except InvalidZipError as e:
        logger.info("Invalid zip supplied", extra={"error": str(e)})
        params["outage_lookup_status"] = "invalid_input"
        return _error_response(
            params,
            "That doesn't look like a valid postal code — could you send it again as "
            "5 or 6 digits, like 560001?",
        )
    except OutageServiceTimeout as e:
        logger.error("Outage service timeout", extra={"error": str(e)})
        params["outage_lookup_status"] = "timeout"
        return _error_response(
            params,
            "I couldn't check the outage service right now — it's taking too long to "
            "respond. We can try again in a moment, or I can keep helping you "
            "troubleshoot your connection in the meantime.",
        )
    except OutageServiceUnavailable as e:
        logger.error("Outage service unavailable", extra={"error": str(e)})
        params["outage_lookup_status"] = "unavailable"
        return _error_response(
            params,
            "The outage-check service isn't responding right now. We can try again, "
            "or I can continue helping you troubleshoot your connection directly.",
        )
    except Exception:
        # Catch-all for anything unexpected (e.g. malformed downstream
        # payload missing the fields we need) — never leak a stack
        # trace or a bare "something went wrong" to the user.
        logger.exception("Unexpected error during outage check")
        params["outage_lookup_status"] = "error"
        return _error_response(
            params,
            "Something interrupted the outage lookup on our end. We can try again, "
            "or I can continue helping you troubleshoot your connection.",
        )

    # Defensive check for a malformed-but-200 downstream payload
    if "outage" not in result:
        logger.error("Malformed outage service response", extra={"raw": result})
        params["outage_lookup_status"] = "error"
        return _error_response(
            params,
            "I got back an unexpected response from the outage service. We can try "
            "again, or I can continue helping you troubleshoot your connection.",
        )

    params["outage_lookup_status"] = "ok"
    params["outage_found"] = result["outage"]
    params["outage_area"] = result.get("area")
    params["outage_eta"] = result.get("estimatedResolution")
    return _session_params_response(params, "check-outage")


def _handle_ticket_status(req_json: dict):
    params = _extract_params(req_json)
    ticket_id = params.get("ticket_id")
    simulate = params.get("__simulate_failure")

    try:
        result = get_ticket_status(ticket_id, simulate=simulate)
    except InvalidTicketIdError as e:
        logger.info("Invalid ticket id supplied", extra={"error": str(e)})
        params["ticket_lookup_status"] = "invalid_input"
        return _error_response(
            params,
            "That doesn't look like a ticket ID I recognize — it should look like "
            "INC-10291. Could you double-check it?",
        )
    except TicketNotFoundError as e:
        logger.info("Ticket not found", extra={"error": str(e)})
        params["ticket_lookup_status"] = "not_found"
        return _error_response(
            params,
            f"I couldn't find a ticket with that ID. Could you double check the "
            f"number, or would you like me to raise a new one?",
        )
    except TicketServiceUnavailable as e:
        logger.error("Ticket service unavailable", extra={"error": str(e)})
        params["ticket_lookup_status"] = "unavailable"
        return _error_response(
            params,
            "The ticketing system isn't responding right now. We can try again in "
            "a moment, or I can help you with something else in the meantime.",
        )
    except Exception:
        logger.exception("Unexpected error during ticket lookup")
        params["ticket_lookup_status"] = "error"
        return _error_response(
            params,
            "Something interrupted that ticket lookup on our end. Let's try again "
            "in a moment.",
        )

    params["ticket_lookup_status"] = "ok"
    params["ticket_status"] = result["status"]
    params["ticket_eta"] = result.get("estimatedResolution")
    return _session_params_response(params, "get-ticket-status")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
