"""SECURITY test: role matrix, auth failures, user lifecycle and password change."""

import pytest

from tests.e2e.helpers import (
    PASSWORD,
    assert_error_envelope,
    create_item,
    create_party,
    create_user,
    error_code,
    expect,
    invoice_body,
    item_body,
    login,
    new_key,
    party_body,
    register_tenant,
    unique_email,
)


async def test_no_token_and_bad_token(client):
    missing = await client.get("/api/v1/invoices")
    assert missing.status_code == 401
    assert error_code(missing) == "NO_TOKEN"
    bad = await client.get("/api/v1/invoices", headers={"Authorization": "Bearer not-a-real-token"})
    assert bad.status_code == 401
    assert error_code(bad) == "TOKEN_INVALID"


@pytest.mark.parametrize("role", ["viewer", "auditor"])
async def test_read_only_roles_cannot_write(client, role):
    owner = await register_tenant(client)
    party = await create_party(client, owner)
    reader = await create_user(client, owner, role)

    forbidden = [
        await client.post("/api/v1/parties", headers=reader.auth, json=party_body()),
        await client.post("/api/v1/items", headers=reader.auth, json=item_body()),
        await client.post(
            "/api/v1/invoices/create_invoice",
            headers={**reader.auth, "Idempotency-Key": new_key()},
            json=invoice_body(party["id"]),
        ),
        await client.post(
            f"/api/v1/parties/{party['id']}/deactivate", headers=reader.auth
        ),
    ]
    for response in forbidden:
        assert response.status_code == 403, f"{role}: {response.request.url.path} -> {response.status_code}"
        assert error_code(response) is not None

    for path in ("/api/v1/parties", "/api/v1/invoices", "/api/v1/items"):
        expect(await client.get(path, headers=reader.auth), 200)


async def test_accountant_can_work_but_not_manage_users(client):
    owner = await register_tenant(client)
    accountant = await create_user(client, owner, "accountant")
    party = expect(await client.post("/api/v1/parties", headers=accountant.auth, json=party_body()), 201).json()
    expect(
        await client.post(
            "/api/v1/invoices/create_invoice",
            headers={**accountant.auth, "Idempotency-Key": new_key()},
            json=invoice_body(party["id"]),
        ),
        201,
    )
    assert (await client.get("/api/v1/users", headers=accountant.auth)).status_code == 403
    attempt = await client.post(
        "/api/v1/users",
        headers=accountant.auth,
        json={"email": unique_email("x"), "full_name": "X", "password": PASSWORD, "role": "viewer"},
    )
    assert attempt.status_code == 403


@pytest.mark.parametrize("role", ["viewer", "auditor"])
async def test_read_only_roles_cannot_manage_users(client, role):
    owner = await register_tenant(client)
    reader = await create_user(client, owner, role)
    assert (await client.get("/api/v1/users", headers=reader.auth)).status_code == 403


async def test_owner_role_cannot_be_created(client):
    owner = await register_tenant(client)
    response = await client.post(
        "/api/v1/users",
        headers=owner.auth,
        json={"email": unique_email("x"), "full_name": "X", "password": PASSWORD, "role": "owner"},
    )
    assert response.status_code == 422
    assert error_code(response) == "VALIDATION_ERROR"


async def test_duplicate_user_email_is_rejected(client):
    owner = await register_tenant(client)
    assert_error_envelope(
        await client.post(
            "/api/v1/users",
            headers=owner.auth,
            json={"email": owner.email, "full_name": "Dup", "password": PASSWORD, "role": "viewer"},
        )
    )


async def test_role_change_takes_effect(client):
    owner = await register_tenant(client)
    viewer = await create_user(client, owner, "viewer")
    users = expect(await client.get("/api/v1/users", headers=owner.auth), 200).json()
    viewer_id = next(u["id"] for u in users if u["email"] == viewer.email)
    expect(await client.patch(f"/api/v1/users/{viewer_id}/role", headers=owner.auth, json={"role": "accountant"}), 200)
    fresh = expect(await login(client, viewer.email, viewer.password), 200).json()
    response = await client.post(
        "/api/v1/parties", headers={"Authorization": f"Bearer {fresh['access_token']}"}, json=party_body()
    )
    assert response.status_code == 201, response.text


async def test_deactivated_user_cannot_login_or_refresh_until_reactivated(client):
    owner = await register_tenant(client)
    accountant = await create_user(client, owner, "accountant")
    users = expect(await client.get("/api/v1/users", headers=owner.auth), 200).json()
    user_id = next(u["id"] for u in users if u["email"] == accountant.email)

    expect(await client.post(f"/api/v1/users/{user_id}/deactivate", headers=owner.auth), 200)
    assert (await login(client, accountant.email, accountant.password)).status_code in (401, 403)
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": accountant.refresh_token})
    assert refresh.status_code in (401, 403), refresh.text

    expect(await client.post(f"/api/v1/users/{user_id}/activate", headers=owner.auth), 200)
    assert (await login(client, accountant.email, accountant.password)).status_code == 200


async def test_owner_cannot_deactivate_themselves(client):
    owner = await register_tenant(client)
    users = expect(await client.get("/api/v1/users", headers=owner.auth), 200).json()
    owner_id = next(u["id"] for u in users if u["email"] == owner.email)
    assert_error_envelope(await client.post(f"/api/v1/users/{owner_id}/deactivate", headers=owner.auth))


async def test_password_change(client):
    owner = await register_tenant(client)
    wrong = await client.post(
        "/api/v1/users/me/password",
        headers=owner.auth,
        json={"current_password": "Not-My-Password1!", "new_password": "N3w!Passw0rd#2x"},
    )
    assert wrong.status_code == 400
    assert error_code(wrong) == "CURRENT_PASSWORD_INCORRECT"

    new_password = "N3w!Passw0rd#2x"
    expect(
        await client.post(
            "/api/v1/users/me/password",
            headers=owner.auth,
            json={"current_password": owner.password, "new_password": new_password},
        ),
        204,
    )
    assert (await login(client, owner.email, new_password)).status_code == 200
    assert (await login(client, owner.email, owner.password)).status_code == 401


async def test_logout_revokes_refresh_token(client):
    owner = await register_tenant(client)
    expect(
        await client.post("/api/v1/auth/logout", headers=owner.auth, json={"refresh_token": owner.refresh_token}), 204
    )
    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": owner.refresh_token})
    assert refresh.status_code == 401, refresh.text
