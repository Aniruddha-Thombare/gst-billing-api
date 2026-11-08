"""CONCURRENCY test: simultaneous payments must never over-collect an invoice."""

import asyncio
from decimal import Decimal

import pytest

from tests.e2e.helpers import (
    assert_error_envelope,
    assert_ledger_consistent,
    get_invoice,
    make_sent_invoice,
    money,
    post_payment,
    register_tenant,
)


@pytest.mark.parametrize(
    "attempts, amount, expected_successes",
    [
        (8, "1180.00", 1),  # only one full payment fits
        (5, "400.00", 2),  # 400 + 400 fits; a third would reach 1200 > 1180
    ],
)
async def test_concurrent_payments_never_exceed_invoice_total(client, attempts, amount, expected_successes):
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)

    responses = await asyncio.gather(
        *(post_payment(client, owner, invoice["id"], amount) for _ in range(attempts))
    )

    successes = [r for r in responses if r.status_code == 201]
    failures = [r for r in responses if r.status_code != 201]
    assert not [r for r in responses if r.status_code >= 500], [r.text for r in responses if r.status_code >= 500]
    assert len(successes) == expected_successes, [r.status_code for r in responses]
    for rejected in failures:
        assert_error_envelope(rejected)

    final = await get_invoice(client, owner, invoice["id"])
    assert money(final["paid_amount"]) == Decimal(amount) * expected_successes
    assert money(final["paid_amount"]) <= money(final["total_amount"])
    assert money(final["outstanding_amount"]) == money(final["total_amount"]) - money(final["paid_amount"])
    await assert_ledger_consistent(client, owner, invoice["id"])
    if expected_successes == 1:
        assert final["invoice_status"] == "paid"
    else:
        assert final["invoice_status"] == "partial"


async def test_payment_larger_than_outstanding_is_rejected(client):
    owner = await register_tenant(client)
    _party, invoice = await make_sent_invoice(client, owner)
    response = await post_payment(client, owner, invoice["id"], "1180.01")
    assert_error_envelope(response)
    assert money((await get_invoice(client, owner, invoice["id"]))["paid_amount"]) == Decimal("0.00")


async def test_payment_on_draft_invoice_is_rejected(client):
    from tests.e2e.helpers import create_invoice, create_party

    owner = await register_tenant(client)
    party = await create_party(client, owner)
    draft = await create_invoice(client, owner, party["id"])
    assert_error_envelope(await post_payment(client, owner, draft["id"], "100.00"))
