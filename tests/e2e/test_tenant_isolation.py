"""SECURITY test: tenant B must never see or touch tenant A's data (always 404)."""

from tests.e2e.helpers import (
    create_item,
    create_party,
    invoice_body,
    item_body,
    list_all,
    make_overpaid_invoice,
    new_key,
    party_body,
    refund_body,
    register_tenant,
    post_refund,
    expect,
    error_code,
)


async def _tenant_a_world(client):
    owner_a = await register_tenant(client)
    world = await make_overpaid_invoice(client, owner_a)
    refund = expect(await post_refund(client, owner_a, world["invoice"]["id"], "100.00"), 201).json()["refund"]
    item = await create_item(client, owner_a)
    users = expect(await client.get("/api/v1/users", headers=owner_a.auth), 200).json()
    return owner_a, {**world, "refund": refund, "item": item, "user_id": users[0]["id"]}


async def test_tenant_b_gets_404_on_every_tenant_a_resource(client):
    owner_a, world = await _tenant_a_world(client)
    owner_b = await register_tenant(client)
    key = lambda: {"Idempotency-Key": new_key()}  # noqa: E731

    invoice_id = world["invoice"]["id"]
    party_id = world["party"]["id"]
    payment_id = world["payment"]["id"]
    refund_id = world["refund"]["id"]
    item_id = world["item"]["id"]
    reason = {"cancellation_reason": "isolation probe"}

    attempts = [
        ("GET", f"/api/v1/parties/{party_id}", None, {}),
        ("PUT", f"/api/v1/parties/{party_id}", party_body(), {}),
        ("POST", f"/api/v1/parties/{party_id}/deactivate", None, {}),
        ("POST", f"/api/v1/parties/{party_id}/activate", None, {}),
        ("GET", f"/api/v1/items/{item_id}", None, {}),
        ("PUT", f"/api/v1/items/{item_id}", item_body(), {}),
        ("POST", f"/api/v1/items/{item_id}/deactivate", None, {}),
        ("POST", f"/api/v1/items/{item_id}/activate", None, {}),
        ("GET", f"/api/v1/invoices/{invoice_id}", None, {}),
        ("GET", f"/api/v1/invoices/{invoice_id}/pdf", None, {}),
        ("POST", f"/api/v1/invoices/{invoice_id}/send", None, key()),
        ("POST", f"/api/v1/invoices/{invoice_id}/void", {"void_reason": "isolation probe"}, {}),
        ("GET", f"/api/v1/invoices/{invoice_id}/refunds", None, {}),
        ("POST", f"/api/v1/invoices/{invoice_id}/refunds", refund_body("10.00"), key()),
        ("POST", f"/api/v1/invoices/{invoice_id}/payments", {
            "payment_date": "2020-01-01", "amount": "10.00", "payment_mode": "cash"}, key()),
        ("GET", f"/api/v1/payments/{payment_id}/pdf", None, {}),
        ("POST", f"/api/v1/payments/{payment_id}/cancel", reason, {}),
        ("GET", f"/api/v1/refunds/{refund_id}/pdf", None, {}),
        ("POST", f"/api/v1/refunds/{refund_id}/cancel", reason, {}),
        ("PATCH", f"/api/v1/users/{world['user_id']}/role", {"role": "viewer"}, {}),
        ("POST", f"/api/v1/users/{world['user_id']}/deactivate", None, {}),
        ("POST", f"/api/v1/users/{world['user_id']}/activate", None, {}),
    ]
    leaks = []
    for method, path, body, extra in attempts:
        response = await client.request(method, path, headers={**owner_b.auth, **extra}, json=body)
        if response.status_code != 404:
            leaks.append(f"{method} {path} -> {response.status_code} {response.text[:120]}")
    assert not leaks, "Cross-tenant access was not a 404:\n" + "\n".join(leaks)

    # and A's data is untouched
    assert expect(await client.get(f"/api/v1/invoices/{invoice_id}", headers=owner_a.auth), 200).json()["id"] == invoice_id


async def test_tenant_b_cannot_invoice_tenant_a_party(client):
    owner_a = await register_tenant(client)
    owner_b = await register_tenant(client)
    party_a = await create_party(client, owner_a)
    response = await client.post(
        "/api/v1/invoices/create_invoice",
        headers={**owner_b.auth, "Idempotency-Key": new_key()},
        json=invoice_body(party_a["id"]),
    )
    assert response.status_code == 404, response.text
    assert error_code(response) is not None


async def test_list_endpoints_do_not_leak(client):
    owner_a, world = await _tenant_a_world(client)
    owner_b = await register_tenant(client)

    for path, id_value in [
        ("/api/v1/parties", world["party"]["id"]),
        ("/api/v1/items", world["item"]["id"]),
        ("/api/v1/invoices", world["invoice"]["id"]),
        ("/api/v1/payments", world["payment"]["id"]),
    ]:
        rows = await list_all(client, owner_b, path)
        assert id_value not in {row["id"] for row in rows}, f"{path} leaked tenant A data"
        assert rows == [], f"{path} should be empty for a fresh tenant, got {len(rows)} rows"

    users_b = expect(await client.get("/api/v1/users", headers=owner_b.auth), 200).json()
    assert world["user_id"] not in {u["id"] for u in users_b}


async def test_dashboard_is_per_tenant(client):
    owner_a, _world = await _tenant_a_world(client)
    owner_b = await register_tenant(client)
    dash_a = expect(await client.get("/api/v1/dashboard", headers=owner_a.auth), 200).json()
    dash_b = expect(await client.get("/api/v1/dashboard", headers=owner_b.auth), 200).json()
    assert dash_a["collections_this_month"]["payments_count"] >= 1
    assert dash_b["collections_this_month"]["payments_count"] == 0
    assert dash_b["top_customers_by_outstanding"] == []
