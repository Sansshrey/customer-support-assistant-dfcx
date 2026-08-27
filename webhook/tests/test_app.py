import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _cx_request(tag, params):
    return {
        "fulfillmentInfo": {"tag": tag},
        "sessionInfo": {"parameters": params},
    }


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200


def test_outage_check_happy_path(client):
    resp = client.post("/webhook", json=_cx_request("check-outage", {"zip_code": "560001"}))
    body = resp.get_json()
    assert resp.status_code == 200
    params = body["sessionInfo"]["parameters"]
    assert params["outage_lookup_status"] == "ok"
    assert params["outage_found"] is True
    assert params["outage_eta"] == "18:30"


def test_outage_check_no_outage(client):
    resp = client.post("/webhook", json=_cx_request("check-outage", {"zip_code": "111111"}))
    params = resp.get_json()["sessionInfo"]["parameters"]
    assert params["outage_found"] is False


def test_outage_check_invalid_zip(client):
    resp = client.post("/webhook", json=_cx_request("check-outage", {"zip_code": "xx"}))
    body = resp.get_json()
    params = body["sessionInfo"]["parameters"]
    assert params["outage_lookup_status"] == "invalid_input"
    assert "postal code" in body["fulfillmentResponse"]["messages"][0]["text"]["text"][0]


def test_outage_check_simulated_timeout(client):
    resp = client.post(
        "/webhook",
        json=_cx_request("check-outage", {"zip_code": "560001", "__simulate_failure": "timeout"}),
    )
    body = resp.get_json()
    params = body["sessionInfo"]["parameters"]
    assert params["outage_lookup_status"] == "timeout"
    assert "try again" in body["fulfillmentResponse"]["messages"][0]["text"]["text"][0]


def test_outage_check_simulated_5xx(client):
    resp = client.post(
        "/webhook",
        json=_cx_request("check-outage", {"zip_code": "560001", "__simulate_failure": "5xx"}),
    )
    params = resp.get_json()["sessionInfo"]["parameters"]
    assert params["outage_lookup_status"] == "unavailable"


def test_ticket_status_happy_path(client):
    resp = client.post("/webhook", json=_cx_request("get-ticket-status", {"ticket_id": "INC-10291"}))
    params = resp.get_json()["sessionInfo"]["parameters"]
    assert params["ticket_lookup_status"] == "ok"
    assert params["ticket_status"] == "IN_PROGRESS"


def test_ticket_status_not_found(client):
    resp = client.post("/webhook", json=_cx_request("get-ticket-status", {"ticket_id": "INC-00000"}))
    params = resp.get_json()["sessionInfo"]["parameters"]
    assert params["ticket_lookup_status"] == "not_found"


def test_unknown_tag_returns_400(client):
    resp = client.post("/webhook", json=_cx_request("not-a-real-tag", {}))
    assert resp.status_code == 400


def test_empty_body_returns_400(client):
    resp = client.post("/webhook", data="not json", content_type="text/plain")
    assert resp.status_code == 400
