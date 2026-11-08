"""WORKFLOW test: pay -> credit note -> refund due -> refund, with ledger checks at each step."""

from decimal import Decimal

from tests.e2e.helpers import (
    assert_error_envelope,
    assert_ledger_consistent,
    expect,
    get_invoice,
    make_sent_invoice,
    make_overpaid_invoice,
    money,
    post_payment,
    post_refund,
    record_payment,
    register_tenant,
)


async def test_credit_note_after_full_payment_creates_refund_due(client):
    owner = await register_tenant(client)
    world = await make_overpaid_invoice(client, owner)
    invoice = await get_invoice(client, owner, world["invoice"]["id"])
    assert money(invoice["paid_amount"]) == Decimal("1180.00")
    assert money(invoice["credited_amount"]) == Decimal("590.00")
    assert money(invoice["outstanding_amount"]) == Decimal("0.00")
    assert money(invoice["refund_due_amount"]) == Decimal("590.00")
    await assert_ledger_consistent(client, owner, invoice["id"])


async def test_refund_lifecycle(client):
    owner = await register_tenant(client)
    world = await make_overpaid_invoice(client, owner)
    invoice_id = world["invoice"]["id"]

    partial = expect(await post_refund(client, owner, invoice_id, "200.00"), 201).json()
    assert money(partial["refunded_amount"]) == Decimal("200.00")
    assert money(partial["refund_due_amount"]) == Decimal("390.00")

    over = await post_refund(client, owner, invoice_id, "400.00")  # only 390 is due
    assert_error_envelope(over)

    rest = expect(await post_refund(client, owner, invoice_id, "390.00"), 201).json()
    assert money(rest["refund_due_amount"]) == Decimal("0.00")
    assert money(rest["refunded_amount"]) == Decimal("590.00")
    await assert_ledger_consistent(client, owner, invoice_id)

    voucher = expect(await client.get(f"/api/v1/refunds/{rest['refund']['id']}/pdf", headers=owner.auth), 200)
    assert voucher.content.startswith(b"%PDF")

    expect(
        await client.post(
            f"/api/v1/refunds/{rest['refund']['id']}/cancel",
            headers=owner.auth,
            json={"cancellation_reason": "bank returned the transfer"},
        ),
        204,
    )
    after = await get_invoice(client, owner, invoice_id)
    assert money(after["refunded_amount"]) == Decimal("200.00")
    assert money(after["refund_due_amount"]) == Decimal("390.00")
    await assert_ledger_consistent(client, owner, invoice_id)


async def test_refund_with_nothing_due_is_rejected(client):
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)
    await record_payment(client, owner, invoice["id"], "1180.00")
    assert_error_envelope(await post_refund(client, owner, invoice["id"], "10.00"))


async def test_cancel_payment_restores_outstanding(client):
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)
    recorded = await record_payment(client, owner, invoice["id"], "1180.00")
    assert recorded["invoice_status"] == "paid"

    expect(
        await client.post(
            f"/api/v1/payments/{recorded['payment']['id']}/cancel",
            headers=owner.auth,
            json={"cancellation_reason": "cheque bounced"},
        ),
        204,
    )
    after = await get_invoice(client, owner, invoice["id"])
    assert money(after["paid_amount"]) == Decimal("0.00")
    assert money(after["outstanding_amount"]) == Decimal("1180.00")
    assert after["invoice_status"] != "paid"
    await assert_ledger_consistent(client, owner, invoice["id"])

    # the cancelled payment cannot be cancelled twice
    again = await client.post(
        f"/api/v1/payments/{recorded['payment']['id']}/cancel",
        headers=owner.auth,
        json={"cancellation_reason": "second attempt"},
    )
    assert_error_envelope(again)


async def test_partial_payments_then_full(client):
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)
    first = await record_payment(client, owner, invoice["id"], "480.00")
    assert first["invoice_status"] == "partial"
    assert money(first["outstanding_amount"]) == Decimal("700.00")
    second = await record_payment(client, owner, invoice["id"], "700.00")
    assert second["invoice_status"] == "paid"
    await assert_ledger_consistent(client, owner, invoice["id"])


async def test_sent_invoice_cannot_be_edited_only_voided(client):
    """Immutability: a locked invoice has no update endpoint; void is the only exit."""
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)
    assert invoice["is_locked"] is True
    for method in ("PUT", "PATCH", "DELETE"):
        response = await client.request(method, f"/api/v1/invoices/{invoice['id']}", headers=owner.auth, json={})
        assert response.status_code in (404, 405), f"{method} returned {response.status_code}"

    voided = expect(
        await client.post(
            f"/api/v1/invoices/{invoice['id']}/void", headers=owner.auth, json={"void_reason": "entered by mistake"}
        ),
        200,
    ).json()
    assert voided["invoice_status"] == "void"
    assert_error_envelope(await post_payment(client, owner, invoice["id"], "100.00"))
