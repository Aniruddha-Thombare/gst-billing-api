"""
Pure formatting helpers for printed documents (invoices, receipts, vouchers).

No DB, no clock, no I/O. Every function takes values that are ALREADY stored
and only changes how they are written down. Nothing here computes tax.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

_TWO_PLACES = Decimal("0.01")

_ONES = (
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def quantize_money(value: Decimal) -> Decimal:
    """Two decimal places, half-up. Stored amounts already have 2dp, so this is display-only."""
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def format_inr(value: Decimal) -> str:
    """1234567.5 -> '12,34,567.50' (Indian digit grouping)."""
    amount = quantize_money(value)
    sign = "-" if amount < 0 else ""
    whole, fraction = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}{whole}.{fraction}"


def format_plain(value: Decimal, min_places: int = 0) -> str:
    """
    Decimal without trailing zeros but with at least `min_places` decimals.
    Never rounds: 2.500 -> '2.5', 100.000 -> '100', 99.9999 stays '99.9999'.
    """
    exponent = value.normalize().as_tuple().exponent
    places = max(min_places, -exponent if exponent < 0 else 0)
    return f"{value:.{places}f}"


def _words_below_100(number: int) -> str:
    if number < 20:
        return _ONES[number]
    tens, ones = divmod(number, 10)
    return _TENS[tens] + (f" {_ONES[ones]}" if ones else "")


def _words_below_1000(number: int) -> str:
    hundreds, rest = divmod(number, 100)
    parts: list[str] = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_words_below_100(rest))
    return " ".join(parts)


def _indian_words(number: int) -> str:
    """Whole number in the Indian system: thousand, lakh, crore."""
    if number == 0:
        return "Zero"
    crore, remainder = divmod(number, 10_000_000)
    lakh, remainder = divmod(remainder, 100_000)
    thousand, remainder = divmod(remainder, 1_000)
    parts: list[str] = []
    if crore:
        parts.append(f"{_indian_words(crore)} Crore")
    if lakh:
        parts.append(f"{_words_below_100(lakh)} Lakh")
    if thousand:
        parts.append(f"{_words_below_100(thousand)} Thousand")
    if remainder:
        parts.append(_words_below_1000(remainder))
    return " ".join(parts)


def amount_in_words(value: Decimal) -> str:
    """1234.50 -> 'Rupees One Thousand Two Hundred Thirty Four and Fifty Paise Only'."""
    amount = quantize_money(value)
    if amount < 0:
        raise ValueError("amount_in_words() does not accept negative amounts")
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    words = f"Rupees {_indian_words(rupees)}"
    if paise:
        words += f" and {_words_below_100(paise)} Paise"
    return f"{words} Only"


def safe_filename(document_number: str) -> str:
    """'INV/2025-26/0001' -> 'INV-2025-26-0001'. Safe inside a Content-Disposition header."""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("-", document_number).strip("-")
    return cleaned or "document"
