import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from services.outage_service import (
    check_outage,
    InvalidZipError,
    OutageServiceTimeout,
    OutageServiceUnavailable,
)


def test_known_outage_returns_true_with_eta():
    result = check_outage("560001")
    assert result["outage"] is True
    assert result["area"] == "560001"
    assert result["estimatedResolution"] == "18:30"


def test_unknown_zip_returns_no_outage():
    result = check_outage("400099")
    assert result["outage"] is False
    assert result["estimatedResolution"] is None


def test_invalid_zip_raises():
    with pytest.raises(InvalidZipError):
        check_outage("abc")


def test_empty_zip_raises():
    with pytest.raises(InvalidZipError):
        check_outage("")


def test_simulated_timeout():
    with pytest.raises(OutageServiceTimeout):
        check_outage("560001", simulate="timeout")


def test_simulated_5xx():
    with pytest.raises(OutageServiceUnavailable):
        check_outage("560001", simulate="5xx")


def test_simulated_malformed_response_missing_outage_key():
    result = check_outage("560001", simulate="malformed")
    assert "outage" not in result
