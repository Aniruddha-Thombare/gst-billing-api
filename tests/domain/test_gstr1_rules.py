"""
Pure unit tests for the GSTR-1 rules and CSV export. No database, no network.
Run:  pytest tests/domain/test_gstr1_rules.py -v
"""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from app.domain.gstr1_rules import (
    B2CL_THRESHOLD,
    OutwardLine,
    OutwardSection,
    build_document_series,
    classify_outward_line,
    financial_year_for,
    parse_return_period,
    sign_for,
    split_document_number,
)
from app.schemas.gstr1 import Gstr1Report, OutwardDocument, RateLine, TenantSummary
from app.services.gstr1_export import render_section_csv


def line(**overrides) -> OutwardLine:
    base = dict(
        invoice_type="sales",
        supply_type="interstate",
        party_gstin=None,
        reverse_charge=False,
        invoice_value=D("100000.00"),
        original_invoice_value=None,
        gst_rate=D("18"),
    )
    base.update(overrides)
    return OutwardLine(**base)


GSTIN = "27DDDDD3333D1Z5"


# ── classification ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "overrides, expected",
    [
        # sales invoices
        (dict(party_gstin=GSTIN), OutwardSection.B2B),
        (dict(party_gstin=GSTIN, reverse_charge=True), OutwardSection.B2B_RCM),
        (dict(supply_type="interstate", invoice_value=D("100000.01")), OutwardSection.B2CL),
        (dict(supply_type="interstate", invoice_value=D("100000.00")), OutwardSection.B2CS),  # not ABOVE the limit
        (dict(supply_type="intrastate", invoice_value=D("900000")), OutwardSection.B2CS),     # intrastate is never B2CL
        (dict(supply_type="export", gst_rate=D("0")), OutwardSection.EXPORT),
        (dict(supply_type="export", gst_rate=D("18")), OutwardSection.EXPORT),
        (dict(supply_type="sez", party_gstin=GSTIN), OutwardSection.SEZ),
        # nil / exempt lines leave Tables 4/5/7 entirely
        (dict(party_gstin=GSTIN, gst_rate=D("0")), OutwardSection.NIL_EXEMPT),
        (dict(gst_rate=D("0")), OutwardSection.NIL_EXEMPT),
        # credit / debit notes
        (dict(invoice_type="credit_note", party_gstin=GSTIN), OutwardSection.CDNR),
        (dict(invoice_type="debit_note", party_gstin=GSTIN), OutwardSection.CDNR),
        (dict(invoice_type="credit_note", supply_type="export", gst_rate=D("0")), OutwardSection.CDNUR),
        (
            dict(invoice_type="credit_note", supply_type="interstate", invoice_value=D("500"),
                 original_invoice_value=D("200000")),
            OutwardSection.CDNUR,  # decided by the ORIGINAL invoice value
        ),
        (
            dict(invoice_type="credit_note", supply_type="interstate", invoice_value=D("500000"),
                 original_invoice_value=D("900")),
            OutwardSection.B2CS,   # small original -> netted into Table 7
        ),
        (dict(invoice_type="credit_note", supply_type="intrastate"), OutwardSection.B2CS),
    ],
)
def test_classification(overrides, expected):
    assert classify_outward_line(line(**overrides)) is expected


def test_threshold_is_configurable_per_call():
    big = line(supply_type="interstate", invoice_value=D("260000"))
    assert classify_outward_line(big, threshold=D("250000")) is OutwardSection.B2CL
    assert classify_outward_line(line(supply_type="interstate", invoice_value=D("240000")),
                                 threshold=D("250000")) is OutwardSection.B2CS
    assert B2CL_THRESHOLD == D("100000.00")


# ── sign convention ───────────────────────────────────────────────────────────

def test_only_credit_notes_are_negative():
    assert sign_for("credit_note") == D("-1")
    assert sign_for("debit_note") == D("1")
    assert sign_for("sales") == D("1")


# ── return period ─────────────────────────────────────────────────────────────

def test_parse_return_period_boundaries():
    p = parse_return_period("2026-09")
    assert (p.start, p.end, p.financial_year) == (date(2026, 9, 1), date(2026, 9, 30), "2026-27")
    assert parse_return_period("2024-02").end == date(2024, 2, 29)      # leap year
    assert parse_return_period("2025-12").end == date(2025, 12, 31)     # year rollover
    assert parse_return_period("2026-03").financial_year == "2025-26"   # March belongs to the previous FY
    assert parse_return_period("2017-07").financial_year == "2017-18"


@pytest.mark.parametrize("bad", ["", "2026-13", "2026-00", "2026-9", "26-09", "2017-06", "abcd-ef", "2026-09-01"])
def test_parse_return_period_rejects(bad):
    with pytest.raises(ValueError):
        parse_return_period(bad)


def test_financial_year_for():
    assert financial_year_for(date(2026, 4, 1)) == "2026-27"
    assert financial_year_for(date(2027, 3, 31)) == "2026-27"
    assert financial_year_for(date(2099, 12, 31)) == "2099-00"


# ── document series ──────────────────────────────────────────────────────────

def test_split_document_number():
    assert split_document_number("INV/2026-27/0042") == ("INV/2026-27/", 42)
    assert split_document_number("NODIGITS") == ("NODIGITS", 0)


def test_series_orders_numerically_and_counts_cancelled():
    rows = [
        ("sales", "INV/2026-27/10000", "sent"),
        ("sales", "INV/2026-27/9999", "paid"),
        ("sales", "INV/2026-27/9998", "void"),
        ("credit_note", "CN/2026-27/0001", "sent"),
    ]
    by_type = {s.document_type: s for s in build_document_series(rows)}
    invoices = by_type["Invoices for outward supply"]
    assert invoices.first_number == "INV/2026-27/9998"      # string order would wrongly pick 10000
    assert invoices.last_number == "INV/2026-27/10000"
    assert (invoices.total_numbers, invoices.cancelled, invoices.net_issued) == (3, 1, 2)
    assert by_type["Credit Note"].net_issued == 1


# ── CSV export ───────────────────────────────────────────────────────────────

def _report_with_party(name: str) -> Gstr1Report:
    document = OutwardDocument(
        invoice_id="00000000-0000-0000-0000-000000000001",
        document_number="INV/2026-27/0001",
        document_date=date(2026, 9, 10),
        document_type="sales",
        party_name=name,
        party_gstin=GSTIN,
        place_of_supply="27",
        supply_type="intrastate",
        reverse_charge=False,
        document_value=D("1180"),
        items=[RateLine(gst_rate=D("18"), taxable_amount=D("1000"), cgst_amount=D("90"), sgst_amount=D("90"))],
    )
    return Gstr1Report(
        return_period="2026-09", financial_year="2026-27",
        tenant=TenantSummary(gstin="27AAAAA0000A1Z5", legal_name="T", state_code="27"),
        generated_at=datetime.now(timezone.utc), b2cl_threshold=B2CL_THRESHOLD, is_period_open=False,
        b2b=[document],
    )


@pytest.mark.parametrize("name", ['=HYPERLINK("http://evil")', "+1+1", "-2", "@SUM(A1)"])
def test_csv_neutralises_formula_injection(name):
    rows = list(csv.reader(io.StringIO(render_section_csv(_report_with_party(name), "b2b"))))
    receiver_name = rows[1][1]                      # column 'Receiver Name'
    assert receiver_name == "'" + name              # a leading quote makes spreadsheets treat it as text


def test_csv_money_has_two_decimals_and_rate_has_none_trailing():
    csv_text = render_section_csv(_report_with_party("Acme"), "b2b")
    assert "1180.00" in csv_text and ",18," in csv_text and "90.00" in csv_text


def test_unregistered_interstate_exactly_at_limit_is_b2cs():
    # ARRANGE: build the input
    row = line(supply_type="interstate", party_gstin=None, invoice_value=D("100000.00"))

    # ACT: call the function we are testing
    section = classify_outward_line(row)

    # ASSERT: compare with the answer we decided in Step 2
    assert section is OutwardSection.B2CS

def test_february_2025_ends_on_28th():
    period = parse_return_period("2025-02")
    assert period.end == date(2025,2,28)