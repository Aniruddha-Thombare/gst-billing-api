"""INTEGRATION test: Idempotency-Key behaviour on invoices, payments and send."""

import asyncio

from tests.e2e.audit_db import count_audit_rows
from tests.e2e.helpers import (
    create_invoice,
    create_party,
    error_code,
    expect,
    invoice_body,
    list_all,
    make_sent_invoice,
    money,
    new_key,
    post_payment,
    register_tenant,
    send_invoice,
    get_invoice,
)
from decimal import Decimal


async def test_missing_key_is_a_validation_error(client):
    owner = await register_tenant(client)
    party = await create_party(client, owner)
    response = await client.post(
        "/api/v1/invoices/create_invoice", headers=owner.auth, json=invoice_body(party["id"])
    )
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


async def test_invoice_create_replay_returns_same_invoice(client):
    owner = await register_tenant(client)
    party = await create_party(client, owner)
    key = new_key()
    first = await create_invoice(client, owner, party["id"], key=key)
    second = expect(
        await client.post(
            "/api/v1/invoices/create_invoice",
            headers={**owner.auth, "Idempotency-Key": key},
            json=invoice_body(party["id"]),
        ),
        200,
        201,
    ).json()
    assert second["id"] == first["id"]
    assert second["invoice_number"] == first["invoice_number"]
    invoices = await list_all(client, owner, "/api/v1/invoices")
    assert len(invoices) == 1


async def test_same_key_with_different_payload_is_rejected(client):
    owner = await register_tenant(client)
    party = await create_party(client, owner)
    key = new_key()
    await create_invoice(client, owner, party["id"], key=key)
    response = await client.post(
        "/api/v1/invoices/create_invoice",
        headers={**owner.auth, "Idempotency-Key": key},
        json=invoice_body(party["id"], quantity="3", total="1770.00"),
    )
    assert 400 <= response.status_code < 500
    assert error_code(response) == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"


async def test_payment_replay_creates_exactly_one_payment(client):
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)
    key = new_key()
    first = expect(await post_payment(client, owner, invoice["id"], "500.00", key=key), 201).json()
    from tests.e2e.helpers import payment_body

    second = expect(
        await post_payment(client, owner, invoice["id"], "500.00", key=key, body=_same_body(first)),
        200,
        201,
    ).json()
    assert second["payment"]["id"] == first["payment"]["id"]
    payments = await list_all(client, owner, "/api/v1/payments", invoice_id=invoice["id"])
    assert len(payments) == 1
    assert money((await get_invoice(client, owner, invoice["id"]))["paid_amount"]) == Decimal("500.00")


def _same_body(first_response: dict) -> dict:
    """Rebuild the exact body of the first request from its response."""
    payment = first_response["payment"]
    return {
        "payment_date": payment["payment_date"],
        "amount": payment["amount"],
        "payment_mode": payment["payment_mode"],
        "reference_number": payment["reference_number"],
        "bank_name": payment["bank_name"],
        "confirm_duplicate": True,
    }


async def test_concurrent_requests_with_one_key_create_one_payment(client):
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)
    key = new_key()
    from tests.e2e.helpers import payment_body

    body = payment_body("300.00")
    responses = await asyncio.gather(
        *(post_payment(client, owner, invoice["id"], "300.00", key=key, body=body) for _ in range(5))
    )
    assert not [r for r in responses if r.status_code >= 500], [r.text for r in responses]
    ids = {r.json()["payment"]["id"] for r in responses if r.status_code in (200, 201)}
    assert len(ids) == 1, f"expected a single payment id, got {ids}"
    payments = await list_all(client, owner, "/api/v1/payments", invoice_id=invoice["id"])
    assert len(payments) == 1


async def test_send_replay_is_safe(client):
    owner = await register_tenant(client)
    party = await create_party(client, owner)
    invoice = await create_invoice(client, owner, party["id"])
    key = new_key()
    first = await send_invoice(client, owner, invoice["id"], key=key)
    second = await send_invoice(client, owner, invoice["id"], key=key)
    assert first["invoice_status"] == second["invoice_status"] == "sent"
    assert first["invoice_number"] == second["invoice_number"]


async def test_same_key_in_two_tenants_does_not_collide(client):
    tenant_a = await register_tenant(client)
    tenant_b = await register_tenant(client)
    party_a = await create_party(client, tenant_a)
    party_b = await create_party(client, tenant_b)
    key = new_key()
    invoice_a = await create_invoice(client, tenant_a, party_a["id"], key=key)
    invoice_b = await create_invoice(client, tenant_b, party_b["id"], key=key)
    assert invoice_a["id"] != invoice_b["id"]
    assert invoice_a["tenant_id"] != invoice_b["tenant_id"]


async def test_replay_writes_no_new_audit_row(client, db):
    owner = await register_tenant(client)
    party = await create_party(client, owner)
    key = new_key()
    await create_invoice(client, owner, party["id"], key=key)
    before = await count_audit_rows(db, owner.tenant_id)
    await client.post(
        "/api/v1/invoices/create_invoice",
        headers={**owner.auth, "Idempotency-Key": key},
        json=invoice_body(party["id"]),
    )
    assert await count_audit_rows(db, owner.tenant_id) == before
