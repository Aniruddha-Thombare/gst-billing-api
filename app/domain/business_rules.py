import re
from datetime import date
from decimal import Decimal
from typing import Final


# COMPILED REGEX PATTERNS
# All patterns are compiled at Module run time - not inside function bodies 

# re.compile() executes the regex parser and produces a compiled pattern object.

# GSTIN: 2-digit state code + 5 uppercase letters (PAN alphabetic prefix) +
#        4 digits (PAN numeric) + 1 uppercase letter (PAN check) +
#        1 alphanumeric (entity count, 1-9 or A-Z) + literal 'Z' +
#        1 alphanumeric (check digit)
_GSTIN_PATTERN: Final[re.Pattern] = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)

# PAN: 5 uppercase letters + 4 digits + 1 uppercase letter (10 chars total)
# The 4th letter indicates entity type:
#   P = Individual, H = Hindu Undivided Family, F = Firm,
#   C = Company, A = AOP, B = BOI, L = Local Authority,
#   J = Artificial Juridical Person, G = Government
_PAN_PATTERN: Final[re.Pattern] = re.compile(
    r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"
)

# HSN codes must be purely numeric (2, 4, 6, or 8 digits)
_HSN_NUMERIC_PATTERN: Final[re.Pattern] = re.compile(
    r"^([0-9]{2}|[0-9]{4}|[0-9]{6}|[0-9]{8})$"
)

# SAC codes for services: exactly 6 digits, must start with "99"
# The "99" prefix distinguishes services from goods (HSN) universally
_SAC_PATTERN: Final[re.Pattern] = re.compile(r"^99[0-9]{4}$")

# Invoice number: alphanumeric + hyphen + slash only, 1-16 characters
# Per CGST Rules, 2017, Rule 46(b)
_INVOICE_NUMBER_PATTERN: Final[re.Pattern] = re.compile(
    r"^[A-Za-z0-9\-/]{1,16}$"
)


# STATUTORY CONSTANTS

# E-invoice threshold: aggregate annual turnover exceeding ₹5 crore in any
# preceding financial year triggers mandatory e-invoice for B2B transactions.
# Source: GST Notification No. 17/2022-Central Tax, effective 01-Oct-2022.
_E_INVOICE_THRESHOLD: Final[Decimal] = Decimal("50000000")  # ₹5 crore

# HSN digit requirement thresholds (Notification No. 78/2020-Central Tax,
# effective 01-Apr-2021):
#   Annual turnover > ₹5 crore  → minimum 6-digit HSN mandatory
#   Annual turnover > ₹1.5 crore → minimum 4-digit HSN mandatory (B2B)
#   Annual turnover <= ₹1.5 crore → no mandatory digit count
_HSN_SIX_DIGIT_THRESHOLD: Final[Decimal]  = Decimal("50000000")   # ₹5 crore
_HSN_FOUR_DIGIT_THRESHOLD: Final[Decimal] = Decimal("15000000")   # ₹1.5 crore

# Complete set of valid Indian state and Union Territory GST codes.
# Source: GSTN State Code Master (includes states 01-38 + UT codes 97, 99).
# Using frozenset for O(1) membership check — validated on every invoice.
VALID_STATE_CODES: Final[frozenset[str]] = frozenset({
    "01",  # Jammu & Kashmir
    "02",  # Himachal Pradesh
    "03",  # Punjab
    "04",  # Chandigarh (UT)
    "05",  # Uttarakhand
    "06",  # Haryana
    "07",  # Delhi
    "08",  # Rajasthan
    "09",  # Uttar Pradesh
    "10",  # Bihar
    "11",  # Sikkim
    "12",  # Arunachal Pradesh
    "13",  # Nagaland
    "14",  # Manipur
    "15",  # Mizoram
    "16",  # Tripura
    "17",  # Meghalaya
    "18",  # Assam
    "19",  # West Bengal
    "20",  # Jharkhand
    "21",  # Orissa
    "22",  # Chhattisgarh
    "23",  # Madhya Pradesh
    "24",  # Gujarat
    "26",  # Dadra & Nagar Haveli & Daman and Diu (UT)
    "27",  # Maharashtra
    "29",  # Karnataka
    "30",  # Goa
    "31",  # Lakshadweep (UT)
    "32",  # Kerala
    "33",  # Tamil Nadu
    "34",  # Puducherry (UT)
    "35",  # Andaman & Nicobar Islands (UT)
    "36",  # Telangana
    "37",  # Andhra Pradesh 
    "38",  # Ladakh (UT)
    "97",  # Other Territory
    "99",  # Centre Jurisdiction (CGST commissionerate)
})


# GSTIN VALIDATION 

def validate_gstin(gstin: str) -> bool:
    """
    Validates a GSTIN against the statutory 15-character regex format pattern.
    """
    if not isinstance(gstin,str) or len(gstin) != 15:
        return False 
    return bool(_GSTIN_PATTERN.match(gstin.upper()))


def validate_gstin_pan_alignment(gstin: str, pan: str) -> bool:
    """
    Validates that the PAN embedded in the GSTIN matches the provided PAN.

    STATUTORY REQUIREMENT (CGST Act, 2017):
    Every GSTIN is directly derived from the entity's PAN.
    Chars 3-12 of the GSTIN (1-indexed, i.e., Python index [2:12]) must be
    identical to the entity's 10-character PAN.
    """

    clean_gstin = gstin.strip().upper()
    clean_pan = pan.strip().upper()

    if len(clean_gstin) != 15 or len(clean_pan) != 10:
        return False 
    
    # 2. Validate the strict legal formats
    if not _GSTIN_PATTERN.match(clean_gstin):
        return False
    if not _PAN_PATTERN.match(clean_pan):
        return False

    # 3. If formats are perfect, verify alignment
    embedded_pan = clean_gstin[2:12]
    return embedded_pan == clean_pan


def validate_gstin_state_code_alignment(gstin: str, state_code: str) -> bool:
    """
    Validates that the state prefix in the GSTIN matches the declared state.

    STATUTORY REQUIREMENT:
    The first 2 characters of a GSTIN are the state code of the state
    where the business is GST-registered. The tenant's declared state_code
    must match these characters exactly.
    """
    if not isinstance(gstin, str) or not isinstance(state_code, str):
        return False
    if len(gstin) < 2:
        return False
    return gstin[:2] == state_code.strip().zfill(2)


def validate_state_code(state_code: str) -> bool:
    """
    Validates that a state code is a known Indian GST state or UT code.

    Uses the VALID_STATE_CODES frozenset for O(1) lookup.
    """
    if not isinstance(state_code,str):
        return False 
    return state_code.strip().zfill(2) in VALID_STATE_CODES


# PLACE OF SUPPLY 
def determine_place_of_supply(
        supplier_state_code: str,
        buyer_gstin: str | None,
        delivery_state_code: str,
        is_service: bool = False,
) ->  str:
    """
    Determines the Place of Supply (PoS) state code for a transaction.

    The PoS drives two downstream calculations:
      1. determine_supply_type() in tax_engine.py → intra vs inter state
      2. Which state government receives the SGST revenue
    """
    if is_service:
        if buyer_gstin and len(buyer_gstin) >= 2:
            # B2B service: PoS = state of registered recipient
            # GSTIN first 2 chars = state code (no DB lookup needed)
            if not validate_gstin(buyer_gstin):
                raise ValueError("Invalid GSTIN")

            return buyer_gstin[:2].strip()
        else: 
            # B2C service: PoS = state of supplier
            return supplier_state_code.strip()
    else: 
        # Goods: PoS = delivery state
        return delivery_state_code.strip()
    

# HSN / SAC VALIDATION
def get_required_hsn_digit_count(annual_turnover: Decimal) -> int:
    """
    Returns the MINIMUM HSN digit count required for the given annual turnover.

    Annual turnover > ₹5 Crore:   6-digit HSN mandatory on ALL invoices
    Annual turnover > ₹1.5 Crore: 4-digit HSN mandatory on B2B invoices
    Annual turnover ≤ ₹1.5 Crore: No mandatory count (4-digit encouraged)
    """
    if annual_turnover < 0:
        raise ValueError("Annual turnover cannot be negative")
    
    if annual_turnover > _HSN_SIX_DIGIT_THRESHOLD:
        return 6
    elif annual_turnover > _HSN_FOUR_DIGIT_THRESHOLD:
        return 4
    else:
        return 0
    

def validate_hsn_sac_code(
    hsn_code: str,
    annual_turnover: Decimal,
    is_service: bool = False,
) -> bool:
    """
    Validates an HSN (goods) or SAC (services) code.

    HSN CODES (Harmonised System of Nomenclature) — for GOODS:
      Purely numeric. Valid lengths: 2, 4, 6, or 8 digits.
      Organised as: Chapter (2); Heading (4); Sub-heading (6); Tariff (8).
      Example: 8471 = Automatic data-processing machines (computers)
               847130 = Portable ADP machines, weight ≤ 10 kg (laptops)

    SAC CODES (Services Accounting Code) — for SERVICES:
      Always exactly 6 digits, always starting with "99".
      Example: 998314 = Management consulting services
               997212 = Rental or leasing services involving own property
    """
    if not isinstance(hsn_code, str) or not hsn_code.strip():
        return False

    code = hsn_code.strip()

    if is_service:
        # SAC: exactly 6 digits, starting with 99
        return bool(_SAC_PATTERN.match(code))
    else:
        # HSN: must be numeric
        if not _HSN_NUMERIC_PATTERN.match(code):
            return False

        required_digits = get_required_hsn_digit_count(annual_turnover)

        if required_digits == 0:
            # Below ₹1.5 crore threshold: any numeric code ≥ 2 digits is valid
            return len(code) >= 2

        return len(code) >= required_digits
    

# E-Invoice Applicability 
def is_e_invoice_applicable(annual_turnover: Decimal) -> bool:
    """
    Determines whether a tenant must generate e-invoices for B2B transactions.

    STATUTORY MANDATE:
    E-invoice (electronic invoicing via GSTN's Invoice Registration Portal)
    is mandatory for any GST-registered person whose aggregate annual turnover
    exceeds ₹5 crore in ANY preceding financial year.
    
    """
    if annual_turnover < 0:
        raise ValueError("Annual Turnover cannot be negative")
    return annual_turnover > _E_INVOICE_THRESHOLD


# FINANCIAL YEAR
def get_financial_year(for_date: date) -> str:
    """
    Returns the Indian Financial Year string for a given date.

    INDIAN FINANCIAL YEAR: April 1 to March 31.
    FY 2023-24 = April 1, 2023 to March 31, 2024.

    REPRESENTATION FORMAT: "YYYY-YY"
    Example: "2023-24" (start year, hyphen, last 2 digits of end year)
    This is the standard GSTN format used in GSTR filings and invoice sequences.
    """
    # April-December: the FY started this calendar year
    # January-March:  the FY started in the PREVIOUS calendar year
    fy_start = for_date.year if for_date.month >= 4 else for_date.year - 1
    fy_end = fy_start + 1

    # Format: "2023-24" — end year as 2 digits using last 2 chars of the string
    return f"{fy_start}-{str(fy_end)[2:]}"


def validate_invoice_date_in_financial_year(
    invoice_date: date,
    expected_financial_year: str,
) -> bool:
    """
    Validates that an invoice date falls within the expected financial year.

    If a client submits an invoice which is previous financial year dated then 
    the invoice_service calls this and logs a warning on mismatch. 
    """
    return get_financial_year(invoice_date) == expected_financial_year


# INVOICE NUMBER VALIDATION 
def validate_invoice_number_format(invoice_number:str) -> bool:
    """
    Validates an invoice number against GSTN portal format requirements.

    GSTN INVOICE NUMBER RULES (CGST Rules, 2017, Rule 46(b)):
      - Maximum 16 characters
      - Allowed characters: alphanumeric (A-Z, a-z, 0-9), hyphen (-), slash (/)
      - Case-insensitive (GSTN normalises to uppercase during upload)
      - Must be non-empty

    EXAMPLES OF VALID FORMATS:
      "INV/23-24/00001"   → Series/FY/Sequence (recommended)
      "GST-2024-001"        → Alternative with hyphens
      "A001"                → Minimal valid format
      "INV001"              → Simple numeric series
    """
    if not isinstance(invoice_number, str) or not invoice_number.strip():
        return False
    return bool(_INVOICE_NUMBER_PATTERN.match(invoice_number.strip()))

