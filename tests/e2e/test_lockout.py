"""SECURITY test: 5 failed logins in 15 minutes lock the account (429 ACCOUNT_LOCKED)."""

from tests.e2e.helpers import create_user, error_code, login, register_tenant

WRONG = "Wrong!Passw0rd#9"


async def test_five_failures_lock_the_account(client):
    owner = await register_tenant(client)
    for attempt in range(5):
        response = await login(client, owner.email, WRONG)
        assert response.status_code == 401, f"attempt {attempt + 1}: {response.status_code} {response.text[:200]}"

    locked = await login(client, owner.email, owner.password)  # even the CORRECT password is refused
    assert locked.status_code == 429, locked.text
    assert error_code(locked) == "ACCOUNT_LOCKED"


async def test_lockout_is_per_account(client):
    owner = await register_tenant(client)
    accountant = await create_user(client, owner, "accountant")
    for _ in range(5):
        await login(client, owner.email, WRONG)
    assert (await login(client, owner.email, owner.password)).status_code == 429
    assert (await login(client, accountant.email, accountant.password)).status_code == 200


async def test_success_resets_the_failure_count(client):
    owner = await register_tenant(client)
    for _ in range(4):
        assert (await login(client, owner.email, WRONG)).status_code == 401
    assert (await login(client, owner.email, owner.password)).status_code == 200
    for _ in range(4):
        assert (await login(client, owner.email, WRONG)).status_code == 401
    assert (await login(client, owner.email, owner.password)).status_code == 200


async def test_unknown_email_gets_same_status_as_wrong_password(client):
    """No account enumeration: unknown user and wrong password look the same."""
    owner = await register_tenant(client)
    wrong_password = await login(client, owner.email, WRONG)
    unknown_user = await login(client, "nobody-here@gstbilling-e2e.dev", WRONG)
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert error_code(wrong_password) == error_code(unknown_user)
