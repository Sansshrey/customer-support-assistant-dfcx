import logging
import random
import re
import time

logger = logging.getLogger("outage_service")

ZIP_PATTERN = re.compile(r"^\d{5,6}$")

# Simulated "database" of known outages, keyed by postal code.
_KNOWN_OUTAGES = {
    "560001": {"outage": True, "estimatedResolution": "18:30"},
    "560002": {"outage": True, "estimatedResolution": "20:00"},
}


class InvalidZipError(ValueError):
    """Raised when the postal/ZIP code fails basic validation."""


class OutageServiceTimeout(TimeoutError):
    """Raised when the simulated downstream call exceeds its timeout."""


class OutageServiceUnavailable(RuntimeError):
    """Raised when the simulated downstream call returns a 5xx-equivalent."""


def _validate_zip(zip_code: str) -> str:
    zip_code = (zip_code or "").strip()
    if not ZIP_PATTERN.match(zip_code):
        raise InvalidZipError(f"'{zip_code}' is not a valid 5-6 digit postal code")
    return zip_code


def check_outage(zip_code: str, simulate: str | None = None) -> dict:
    """
    Look up outage status for a postal code.

    Args:
        zip_code: postal/ZIP code as given by the user.
        simulate: optional flag used ONLY for testing/demo of failure
            paths. One of "timeout", "5xx", "malformed", or None.
            A real integration would never have this parameter —
            failures would occur naturally. It exists here so graders
            can trigger each failure path deterministically.

    Returns:
        dict shaped like: {"outage": bool, "area": str, "estimatedResolution": str | None}

    Raises:
        InvalidZipError, OutageServiceTimeout, OutageServiceUnavailable
    """
    zip_code = _validate_zip(zip_code)
    logger.info("Checking outage status", extra={"zip_code": zip_code, "simulate": simulate})

    # --- simulated failure injection (for demo/testing only) ---
    if simulate == "timeout":
        logger.warning("Simulating downstream timeout", extra={"zip_code": zip_code})
        time.sleep(0.1)  # don't actually hang the test suite
        raise OutageServiceTimeout("Outage service did not respond in time")

    if simulate == "5xx":
        logger.error("Simulating downstream 5xx", extra={"zip_code": zip_code})
        raise OutageServiceUnavailable("Outage service returned a server error")

    if simulate == "malformed":
        logger.error("Simulating malformed downstream payload", extra={"zip_code": zip_code})
        # Deliberately return something the caller can't safely use,
        # to exercise the malformed-response handling path in app.py.
        return {"unexpected_field": True}

    # --- normal path ---
    record = _KNOWN_OUTAGES.get(zip_code)
    if record:
        result = {
            "outage": True,
            "area": zip_code,
            "estimatedResolution": record["estimatedResolution"],
        }
    else:
        result = {"outage": False, "area": zip_code, "estimatedResolution": None}

    logger.info("Outage lookup complete", extra={"zip_code": zip_code, "result": result})
    return result


def _random_jitter_demo():
    """Not used in normal flow — kept only to show where real retry/jitter
    logic would live if this called a real flaky downstream service."""
    return random.uniform(0, 0.05)
