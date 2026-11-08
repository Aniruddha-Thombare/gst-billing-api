"""Builders and thin API wrappers shared by the e2e tests."""

import asyncio
import random
import string
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx

PASSWORD = "Str0ng!Passw0rd1"
STATE_CODE = "27"
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# ---------- identifiers -------------------------------------------------

def gstin_checksum(first_fourteen: str) -> str:
    total = 0
    for position, char in enumerate(first_fourteen):
        product = _CHARS.index(char) * (1 if position % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36]


def random_pan() -> str:
    letters = "".join(random.choices(string.ascii_uppercase, k=5))
    digits = "".join(random.choices(string.digits, k=4))
    return f"{letters}{digits}{random.choice(string.ascii_uppercase)}"


def random_gstin(state_code: str = STATE_CODE) -> str:
    first_fourteen = f"{state_code}{random_pan()}1Z"
    return first_fourteen + gstin_checksum(first_fourteen)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@gstbilling-e2e.dev"


def new_key() -> str:
    return uuid.uuid4().hex


def yesterday_utc() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def money(value: object) -> Decimal:
    return Decimal(str(value))


# ---------- assertions --------------------------------------------------

def expect(response: httpx.Response, *statuses: int) -> httpx.Response:
    assert response.status_code in statuses, (
        f"{response.request.method} {response.request.url.path} -> "
        f"{response.status_code}, expected {statuses}. Body: {response.text[:600]}"
    )
    return response


def error_code(response: httpx.Response) -> str | None:
    try:
        return response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None


def assert_error_envelope(response: httpx.Response) -> None:
    assert 400 <= response.status_code < 500, f"expected 4xx, got {response.status_code}: {response.text[:300]}"
    assert error_code(response) is not None, f"no error envelope: {response.text[:300]}"


# ---------- tenant + users ----------------------------------------------

@dataclass
class Account:
    """One logged-in user of one tenant."""

    email: str
    password: str
    tenant_id: str
    access_token: str
    refresh_token: str

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def register_tenant(client: httpx.AsyncClient, *, state_code: str = STATE_CODE) -> Account:
    email = unique_email("owner")
    payload = {
        "business_name": "E2E Traders",
        "legal_name": "E2E Traders Private Limited",
        "gstin": random_gstin(state_code),
        "address_line": "12 Test Street, Industrial Area",
        "city": "Pune",
        "pincode": "411001",
        "state_code": state_code,
        "registration_type": "regular",
        "email": email,
        "password": PASSWORD,
        "full_name": "E2E Owner",
    }
    registered = expect(await client.post("/api/v1/auth/register", json=payload), 201).json()
    logged_in = await login(client, email, PASSWORD)
    assert logged_in.status_code == 200, (
        f"Login right after register failed ({logged_in.status_code}): {logged_in.text[:300]}. "
        f"Register said next_step={registered.get('next_step')!r}"
    )
    tokens = logged_in.json()
    return Account(email, PASSWORD, registered["tenant_id"], tokens["access_token"], tokens["refresh_token"])


async def create_user(client: httpx.AsyncClient, owner: Account, role: str) -> Account:
    email = unique_email(role)
    expect(
        await client.post(
            "/api/v1/users",
            headers=owner.auth,
            json={"email": email, "full_name": f"E2E {role}", "password": PASSWORD, "role": role},
        ),
        201,
    )
    tokens = expect(await login(client, email, PASSWORD), 200).json()
    return Account(email, PASSWORD, owner.tenant_id, tokens["access_token"], tokens["refresh_token"])


# ---------- masters -----------------------------------------------------

def party_body(*, with_gstin: bool = False, state_code: str = STATE_CODE) -> dict[str, object]:
    body: dict[str, object] = {
        "name": f"Customer {uuid.uuid4().hex[:8]}",
        "address_line1": "45 Market Road",
        "city": "Mumbai",
        "pincode": "400001",
        "state_code": state_code,
        "email": unique_email("cust"),
        "phone": "9876543210",
        "party_type": "customer",
    }
    if with_gstin:
        body["gstin"] = random_gstin(state_code)
    return body


async def create_party(client: httpx.AsyncClient, account: Account, **kwargs: object) -> dict:
    body = party_body(**kwargs)  # type: ignore[arg-type]
    return expect(await client.post("/api/v1/parties", headers=account.auth, json=body), 201).json()


def item_body() -> dict[str, object]:
    return {
        "name": f"Item {uuid.uuid4().hex[:8]}",
        "hsn_sac_code": "998314",
        "unit": "NOS",
        "rate": "500.00",
        "gst_rate": "18",
        "cess_rate": "0",
        "is_service": False,
    }


async def create_item(client: httpx.AsyncClient, account: Account) -> dict:
    return expect(await client.post("/api/v1/items", headers=account.auth, json=item_body()), 201).json()


# ---------- invoices ----------------------------------------------------

def line_item(quantity: str = "2", rate: str = "500.00", gst_rate: str = "18") -> dict[str, object]:
    return {
        "description": "Consulting service",
        "hsn_sac_code": "998314",
        "quantity": quantity,
        "unit": "NOS",
        "rate": rate,
        "discount_percent": "0",
        "gst_rate": gst_rate,
        "cess_rate": "0",
    }


def invoice_body(
    party_id: str,
    *,
    invoice_type: str = "sales",
    quantity: str = "2",
    rate: str = "500.00",
    total: str = "1180.00",
    original_invoice_id: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "invoice_type": invoice_type,
        "invoice_date": yesterday_utc(),
        "party_id": party_id,
        "is_service": True,
        "line_items": [line_item(quantity, rate)],
        "declared_grand_total": total,
        "confirm_duplicate": True,
    }
    if original_invoice_id:
        body["original_invoice_id"] = original_invoice_id
    return body


async def create_invoice(
    client: httpx.AsyncClient, account: Account, party_id: str, *, key: str | None = None, **kwargs: object
) -> dict:
    response = await client.post(
        "/api/v1/invoices/create_invoice",
        headers={**account.auth, "Idempotency-Key": key or new_key()},
        json=invoice_body(party_id, **kwargs),  # type: ignore[arg-type]
    )
    return expect(response, 201).json()


async def send_invoice(
    client: httpx.AsyncClient, account: Account, invoice_id: str, *, key: str | None = None
) -> dict:
    response = await client.post(
        f"/api/v1/invoices/{invoice_id}/send", headers={**account.auth, "Idempotency-Key": key or new_key()}
    )
    return expect(response, 200).json()


async def get_invoice(client: httpx.AsyncClient, account: Account, invoice_id: str) -> dict:
    return expect(await client.get(f"/api/v1/invoices/{invoice_id}", headers=account.auth), 200).json()


async def make_sent_invoice(client: httpx.AsyncClient, account: Account) -> tuple[dict, dict]:
    """Returns (party, sent invoice of 1180.00)."""
    party = await create_party(client, account)
    invoice = await create_invoice(client, account, party["id"])
    sent = await send_invoice(client, account, invoice["id"])
    return party, sent


# ---------- payments / refunds ------------------------------------------

def payment_body(amount: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "payment_date": today_utc(),
        "amount": amount,
        "payment_mode": "bank_transfer",
        "reference_number": f"UTR{uuid.uuid4().hex[:12].upper()}",
        "bank_name": "HDFC Bank",
        "confirm_duplicate": True,
    }
    body.update(overrides)
    return body


async def post_payment(
    client: httpx.AsyncClient,
    account: Account,
    invoice_id: str,
    amount: str,
    *,
    key: str | None = None,
    body: dict[str, object] | None = None,
) -> httpx.Response:
    return await client.post(
        f"/api/v1/invoices/{invoice_id}/payments",
        headers={**account.auth, "Idempotency-Key": key or new_key()},
        json=body or payment_body(amount),
    )


async def record_payment(client: httpx.AsyncClient, account: Account, invoice_id: str, amount: str) -> dict:
    return expect(await post_payment(client, account, invoice_id, amount), 201).json()


def refund_body(amount: str) -> dict[str, object]:
    return {
        "refund_date": today_utc(),
        "amount": amount,
        "refund_mode": "bank_transfer",
        "reference_number": f"RFN{uuid.uuid4().hex[:12].upper()}",
        "bank_name": "HDFC Bank",
    }


async def post_refund(
    client: httpx.AsyncClient, account: Account, invoice_id: str, amount: str, *, key: str | None = None
) -> httpx.Response:
    return await client.post(
        f"/api/v1/invoices/{invoice_id}/refunds",
        headers={**account.auth, "Idempotency-Key": key or new_key()},
        json=refund_body(amount),
    )


async def make_overpaid_invoice(client: httpx.AsyncClient, account: Account) -> dict:
    """
    Pay 1180.00 in full, then issue and send a 590.00 credit note against it.
    Result: credited_amount 590.00 and refund_due_amount 590.00 on the invoice.
    Returns {"party", "invoice", "payment", "credit_note"}.
    """
    party, invoice = await make_sent_invoice(client, account)
    payment = await record_payment(client, account, invoice["id"], "1180.00")
    credit_note = await create_invoice(
        client,
        account,
        party["id"],
        invoice_type="credit_note",
        quantity="1",
        rate="500.00",
        total="590.00",
        original_invoice_id=invoice["id"],
    )
    await send_invoice(client, account, credit_note["id"])
    return {"party": party, "invoice": invoice, "payment": payment["payment"], "credit_note": credit_note}


# ---------- ledger check (API only, no DB knowledge needed) -------------

async def list_all(client: httpx.AsyncClient, account: Account, path: str, **params: object) -> list[dict]:
    items: list[dict] = []
    cursor: str | None = None
    while True:
        query = {**params, "limit": 100}
        if cursor:
            query["cursor"] = cursor
        page = expect(await client.get(path, headers=account.auth, params=query), 200).json()
        items.extend(page["items"])
        cursor = page.get("next_cursor")
        if not cursor:
            return items


async def assert_ledger_consistent(client: httpx.AsyncClient, account: Account, invoice_id: str) -> None:
    """paid_amount must equal the sum of non-cancelled payments; refunded likewise."""
    invoice = await get_invoice(client, account, invoice_id)
    payments = await list_all(client, account, "/api/v1/payments", invoice_id=invoice_id)
    refunds = expect(await client.get(f"/api/v1/invoices/{invoice_id}/refunds", headers=account.auth), 200).json()
    live_paid = sum((money(p["amount"]) for p in payments if p["status"] != "cancelled"), Decimal("0"))
    live_refunded = sum((money(r["amount"]) for r in refunds if r["status"] != "cancelled"), Decimal("0"))
    assert money(invoice["paid_amount"]) == live_paid, f"paid_amount {invoice['paid_amount']} != payments {live_paid}"
    assert money(invoice["refunded_amount"]) == live_refunded, (
        f"refunded_amount {invoice['refunded_amount']} != refunds {live_refunded}"
    )


async def gather_limited(*coroutines):  # small alias so tests read clearly
    return await asyncio.gather(*coroutines)
