import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.ticket_service import (
    get_ticket_status,
    InvalidTicketIdError,
    TicketNotFoundError,
    TicketServiceUnavailable,
)


def test_known_ticket_in_progress():
    result = get_ticket_status("INC-10291")
    assert result["ticketId"] == "INC-10291"
    assert result["status"] == "IN_PROGRESS"
    assert result["estimatedResolution"] == "2 hours"


def test_ticket_id_is_case_and_format_insensitive():
    result = get_ticket_status("inc10291")
    assert result["ticketId"] == "INC-10291"


def test_unknown_ticket_raises_not_found():
    with pytest.raises(TicketNotFoundError):
        get_ticket_status("INC-99999")


def test_malformed_ticket_id_raises_invalid():
    with pytest.raises(InvalidTicketIdError):
        get_ticket_status("banana")


def test_simulated_5xx():
    with pytest.raises(TicketServiceUnavailable):
        get_ticket_status("INC-10291", simulate="5xx")
