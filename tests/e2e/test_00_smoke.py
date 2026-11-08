"""WORKFLOW test: the happy path of the whole product, end to end."""

from decimal import Decimal

from tests.e2e.helpers import (
    create_item,
    create_party,
    create_invoice,
    expect,
    get_invoice,
    money,
    record_payment,
    register_tenant,
    send_invoice,
    assert_ledger_consistent,
)


async def test_full_happy_path(client):
    owner = await register_tenant(client)
    item = await create_item(client, owner)
    assert item["is_active"] is True

    party = await create_party(client, owner, with_gstin=True)
    invoice = await create_invoice(client, owner, party["id"])
    assert invoice["invoice_status"] == "draft"
    assert money(invoice["total_amount"]) == Decimal("1180.00")
    # 1000 taxable + 18% GST, intra-state -> 90 CGST + 90 SGST, no IGST
    assert money(invoice["taxable_amount"]) == Decimal("1000.00")
    assert money(invoice["cgst_amount"]) == Decimal("90.00")
    assert money(invoice["sgst_amount"]) == Decimal("90.00")
    assert money(invoice["igst_amount"]) == Decimal("0.00")

    sent = await send_invoice(client, owner, invoice["id"])
    assert sent["invoice_status"] == "sent"
    assert sent["is_locked"] is True

    recorded = await record_payment(client, owner, invoice["id"], "1180.00")
    assert recorded["invoice_status"] == "paid"
    assert money(recorded["outstanding_amount"]) == Decimal("0.00")

    final = await get_invoice(client, owner, invoice["id"])
    assert final["invoice_status"] == "paid"
    await assert_ledger_consistent(client, owner, invoice["id"])

    pdf = expect(await client.get(f"/api/v1/invoices/{invoice['id']}/pdf", headers=owner.auth), 200)
    assert pdf.content.startswith(b"%PDF")
    receipt = expect(
        await client.get(f"/api/v1/payments/{recorded['payment']['id']}/pdf", headers=owner.auth), 200
    )
    assert receipt.content.startswith(b"%PDF")

    for path in ("/api/v1/dashboard", "/api/v1/reports/ar-aging", "/api/v1/invoices", "/api/v1/parties"):
        expect(await client.get(path, headers=owner.auth), 200)


async def test_inter_state_invoice_uses_igst(client):
    owner = await register_tenant(client, state_code="27")
    party = await create_party(client, owner, state_code="29", with_gstin=True)
    invoice = await create_invoice(client, owner, party["id"])
    assert money(invoice["igst_amount"]) == Decimal("180.00")
    assert money(invoice["cgst_amount"]) == Decimal("0.00")
    assert money(invoice["sgst_amount"]) == Decimal("0.00")


async def test_wrong_declared_total_is_rejected(client):
    from tests.e2e.helpers import invoice_body, new_key

    owner = await register_tenant(client)
    party = await create_party(client, owner)
    response = await client.post(
        "/api/v1/invoices/create_invoice",
        headers={**owner.auth, "Idempotency-Key": new_key()},
        json=invoice_body(party["id"], total="1000.00"),  # server computes 1180.00
    )
    assert 400 <= response.status_code < 500, response.text
