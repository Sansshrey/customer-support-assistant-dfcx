import logging
import re

logger = logging.getLogger("ticket_service")

# Matches ticket IDs like INC-10291, INC10291, inc-10291 (case-insensitive)
TICKET_PATTERN = re.compile(r"^(INC-?\d{4,8})$", re.IGNORECASE)

_KNOWN_TICKETS = {
    "INC-10291": {"status": "IN_PROGRESS", "estimatedResolution": "2 hours"},
    "INC-10450": {"status": "RESOLVED", "estimatedResolution": None},
    "INC-10999": {"status": "ESCALATED", "estimatedResolution": "4 hours"},
}


class InvalidTicketIdError(ValueError):
    """Raised when the ticket ID doesn't match the expected format."""


class TicketNotFoundError(LookupError):
    """Raised when the ticket ID is well-formed but not found."""


class TicketServiceUnavailable(RuntimeError):
    """Raised when the simulated downstream call fails (5xx-equivalent)."""


def _normalize_ticket_id(raw: str) -> str:
    raw = (raw or "").strip().upper().replace(" ", "")
    match = TICKET_PATTERN.match(raw)
    if not match:
        raise InvalidTicketIdError(f"'{raw}' is not a valid ticket ID (expected e.g. INC-10291)")
    digits = re.sub(r"\D", "", match.group(1))
    return f"INC-{digits}"


def get_ticket_status(ticket_id: str, simulate: str | None = None) -> dict:
    """
    Look up a ticket's status.

    Args:
        ticket_id: raw ticket identifier extracted by Dialogflow CX
            (e.g. "INC-10291", "inc10291").
        simulate: optional failure-injection flag for demos/tests:
            "5xx" or None.

    Returns:
        dict shaped like: {"ticketId": str, "status": str, "estimatedResolution": str | None}

    Raises:
        InvalidTicketIdError, TicketNotFoundError, TicketServiceUnavailable
    """
    normalized_id = _normalize_ticket_id(ticket_id)
    logger.info("Looking up ticket", extra={"ticket_id": normalized_id, "simulate": simulate})

    if simulate == "5xx":
        logger.error("Simulating downstream 5xx", extra={"ticket_id": normalized_id})
        raise TicketServiceUnavailable("Ticket service returned a server error")

    record = _KNOWN_TICKETS.get(normalized_id)
    if not record:
        logger.info("Ticket not found", extra={"ticket_id": normalized_id})
        raise TicketNotFoundError(f"No ticket found with ID {normalized_id}")

    result = {
        "ticketId": normalized_id,
        "status": record["status"],
        "estimatedResolution": record["estimatedResolution"],
    }
    logger.info("Ticket lookup complete", extra={"ticket_id": normalized_id, "result": result})
    return result
