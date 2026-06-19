from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from dataclasses import dataclass, replace
from typing import Final, Literal


# Decimal ("0.01"): This tells exactly how many decimal places to keep. 
# By passing "0.01", you are instructing Python to strictly format the 
# number to two decimal places (e.g., 10.5 becomes 10.50).
TWOPLACES: Final[Decimal] = Decimal("0.01")

# ZERO and ONE_HUNDRED are module-level constants to avoid creating new
# Decimal instances on every function call. At 1M invoice lines/day, creating
# Decimal("0.00") inside a loop adds measurable GC pressure.
ZERO: Final[Decimal] = Decimal("0.00")
ONE_HUNDRED: Final[Decimal] = Decimal("100")

# Maximum permitted rounding adjustment per GSTN invoicing rules.
# Adjustments beyond ±0.50 rupees are not rounding — they are errors.
MAX_ROUNDING_ADJUSTMENT: Final[Decimal] = Decimal("0.50")


SupplyType = Literal[
    "intrastate",
    "interstate",
    "export",
    "sez",
]

# VALID GST RATE SLABS 
# These are the ONLY legally valid GST rates under the GST Act, 2017.
# Any line item carrying a rate not in this set is statutorily invalid
# and would be rejected by the GSTN portal during GSTR filing.
#
# frozenset is used intentionally:
# - Immutable: cannot be accidentally modified at runtime - "this is a fixed set of legal values"
# - O(1) average lookup: "rate in GST_RATE_SLABS" is a hash check, not a scan
GST_RATE_SLABS: Final[frozenset[Decimal]] = frozenset({
    Decimal("0"),
    Decimal("0.1"),
    Decimal("0.125"),
    Decimal("0.25"),
    Decimal("0.75"),
    Decimal("1"),
    Decimal("1.5"),
    Decimal("2.5"),
    Decimal("3"),
    Decimal("5"),
    Decimal("6"),
    Decimal("7.5"),
    Decimal("9"),
    Decimal("12"),
    Decimal("14"),
    Decimal("18"),
    Decimal("28"),
    Decimal("40"),
})

@dataclass(frozen=True)
class TaxBreakdown:
    """
    Immutable record of complete tax calculation for one invoice line item. 
    
    frozen = True makes this dataclass immutable after creation. 
    - Once the tax is calculated at invoice creation time, they must be mutated
    - these figures are persisted to the invoice_items table 
    - 
    """

    # INPUT FIELDS 
    taxable_amount: Decimal         # quantity × unit_price − discount_amount
    gst_rate: Decimal               # the applicable GST slab (e.g., Decimal("18"))
    supply_type: SupplyType         # determines CGST+SGST vs IGST routing

    # INTRASTATE SUPPLIES (CGST + SGST)
    # These are non-zero ONLY for intra-state supplies.
    # CGST and SGST are always equal (each = gst_rate / 2).
    
    # gst_rate / 2 for intra-state, 0 for inter-state
    # taxable_value × cgst_rate / 100, rounded
    cgst_rate : Decimal 
    cgst_amount : Decimal 

    # gst_rate / 2 for intra-state, 0 for inter-state
    # taxable_value × sgst_rate / 100, rounded
    sgst_rate : Decimal 
    sgst_amount : Decimal 

    # INTERSTATE SUPPLIES(IGST)
    # These are non-zero ONLY for interstate_supplies 
    # IGST = full gst_rate applied as a single tax.
    
    # gst_rate for inter-state, 0 for intra-state
    # taxable_value × igst_rate / 100, rounded
    igst_rate : Decimal 
    igst_amount: Decimal 

    # CESS - GST Compensation Cess = applicable to specific luxury/sin goods. 
    # Applied on taxable_value(NOT on the GST amount)
    # The GST (Compensation to States) Act, 2017, Section 8.
    # Most invoices will have cess_rate = Decimal("0") and cess_amount = ZERO
    
    cess_rate: Decimal          # e.g., Decimal("12") for luxury cars
    cess_amount: Decimal        # taxable_value × cess_rate / 100, rounded

    # TOTALS
    total_tax_amount: Decimal   # cgst_amount + sgst_amount + igst_amount + cess_amount
    line_total: Decimal         # taxable_value + total_tax_amount


@dataclass(frozen=True)
class InvoiceTaxSummary: 
    """
    Aggregated tax totals across ALL line items in an invoice 

    Produced by aggregate_invoice_taxes() from a list[TaxBreakdown].
    Stored at the invoice header level in the invoices table.

    WHY STORE BOTH LINE-LEVEL AND HEADER-LEVEL TOTALS?
    Line-level (TaxBreakdown) → required for GSTR-1 HSN-wise summary
    Header-level (InvoiceTaxSummary) → required for invoice PDF generation
    and GSTR-3B monthly return filing.
    Storing both avoids recomputation at report generation time.
    """

    total_taxable_value: Decimal
    total_cgst: Decimal
    total_sgst: Decimal
    total_igst: Decimal
    total_cess: Decimal
    total_tax: Decimal              # total_cgst + total_sgst + total_igst + total_cess
    grand_total: Decimal            # total_taxable_value + total_tax
    rounded_off: Decimal            # Optional ±0.50 rounding adjustment
    payable_amount: Decimal         # grand_total + round_off

# PRIVATE ROUNDING HELPER 
def _round(value:Decimal) -> Decimal:
    """
    Rounding a decimal upto Two decimal places using ROUND_HALF_UP 

    WHY ROUND AT LINE LEVEL (not only at invoice level)?
    GSTN validates each invoice line independently. Per-line rounding matches
    the portal's validation logic. Accumulating unrounded values and rounding
    once at the end can produce a 1-paisa difference per line (N lines = N paisa
    potential discrepancy), which GSTN flags as arithmetic errors.
    """
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)

# VALIDATION FUNCTIONS 

def validate_gst_rate(rate:Decimal) -> bool:
    """
    Returns True if the rate is a legally valid GST slab.

    Called by the invoice service before computing tax. If this returns False,
    the service raises InvalidGSTRateError (422) rather than computing a tax
    figure that would be rejected during GSTR filing.
    """
    try: 
        return rate in GST_RATE_SLABS
    except InvalidOperation:
        return False 

def determine_supply_type(
    supplier_state_code: str,
    place_of_supply_state_code: str
) -> SupplyType:
    """
    Determines whether a supply is intra-state or inter-state.

    STATUTORY RULE (IGST Act, 2017, Sections 7 and 8):
      Same state (supplier == place of supply) - intra-state → CGST + SGST
      Different states/Countries/Union Territories - inter-state → IGST
    
    """
    return (
        "intrastate"
        if supplier_state_code.strip() == place_of_supply_state_code.strip() 
        else "interstate"
    )
    

#  CORE CALCULATION FUNCTIONS

def calculate_taxable_amount(
        quantity: Decimal,
        unit_price: Decimal,
        discount_amount: Decimal = ZERO,
)-> Decimal:
    """
    Calculates the pre-tax line item value (the base on which GST is levied).

    FORMULA: taxable_value = (quantity × unit_price) − discount_amount

    WHY SUBTRACT DISCOUNT BEFORE TAX?
    Under Section 15 of the CGST Act, the value of supply (taxable value)
    excludes discounts that are:
      (a) established in terms of an agreement entered into at or before the
          time of supply, AND
      (b) specifically linked to relevant invoices, AND
      (c) the input tax credit attributable has been reversed by the recipient.

    This system enforces (a) and (b) by requiring discounts to be stated on
    the invoice itself. Post-supply discounts require a Credit Note instead.
    """
    if quantity <= ZERO:
        # There must be atleast one quantity involved in a transaction
        raise ValueError("Quantity must be positive.")

    if unit_price < ZERO:
        raise ValueError("Unit price cannot be negative.")
    
    gross_value = unit_price * quantity

    if discount_amount > gross_value:
        raise ValueError("Discount cannot exceed gross value.")
    
    taxable_value = gross_value - discount_amount
    return _round(taxable_value)


def calculate_line_item_tax(
        taxable_value: Decimal,
        gst_rate: Decimal,
        supply_type: SupplyType,
        cess_rate: Decimal = ZERO,
) -> TaxBreakdown:
    """
    Core GST calculation function. Produces an immutable TaxBreakdown.

    This is the most critical function in the entire domain layer.
    Every rupee of GST on this platform flows through this calculation.

    Returns:
        TaxBreakdown: Immutable record of all tax components for this line item.
    """
    if not validate_gst_rate(gst_rate):
        raise ValueError("GST rate is not a valid rate")
    
    if taxable_value < ZERO:
        raise ValueError("Taxable value cannot be zero")

    if supply_type == "intrastate":
        cgst_rate = gst_rate / 2 
        sgst_rate = gst_rate / 2 
        cgst_amount = _round(taxable_value * cgst_rate / ONE_HUNDRED)
        sgst_amount = _round(taxable_value * sgst_rate / ONE_HUNDRED)
        igst_rate = ZERO
        igst_amount = ZERO
    else:
        igst_rate = gst_rate
        igst_amount = _round(taxable_value * igst_rate / ONE_HUNDRED)
        cgst_rate = ZERO
        sgst_rate = ZERO
        cgst_amount = ZERO
        sgst_amount = ZERO

    if cess_rate < ZERO:
        raise ValueError("cess rate should be alwaus positive")
    cess_amount = _round(taxable_value * cess_rate /ONE_HUNDRED)

    total_tax_amount = cgst_amount + sgst_amount + igst_amount + cess_amount

    line_total = _round(taxable_value + total_tax_amount)

    return TaxBreakdown(
        taxable_value = taxable_value,
        gst_rate = gst_rate,
        supply_type = supply_type,
        cgst_rate = cgst_rate,
        cgst_amount = cgst_amount,
        sgst_rate = sgst_rate,
        sgst_amount = sgst_amount,
        igst_rate = igst_rate,
        igst_amount = igst_amount,
        cess_rate = cess_rate,
        cess_amount = cess_amount,
        total_tax_amount = total_tax_amount,
        line_total = line_total,
    )


def aggregate_invoice_taxes(line_items: list[TaxBreakdown]) -> InvoiceTaxSummary:
    """
    Aggregates TaxBreakdown objects from all line items into an invoice summary.

    Called once per invoice, after all line items are calculated.
    The result is persisted at the invoice header level.
    """
    total_taxable = _round(sum((li.taxable_value for li in line_items), ZERO))
    total_cgst = _round(sum((li.cgst_amount for li in line_items), ZERO))
    total_sgst = _round(sum((li.sgst_amount for li in line_items), ZERO))
    total_igst = _round(sum((li.igst_amount for li in line_items), ZERO))
    total_cess = _round(sum((li.cess_amount for li in line_items), ZERO))

    total_tax = _round(total_cgst + total_sgst + total_igst + total_cess)
    grand_total = _round(total_taxable + total_tax)

    # Default: no rounding adjustment. Seller can apply via apply_rounded_off().
    rounded_off = ZERO
    payable_amount = grand_total

    return InvoiceTaxSummary(
        total_taxable_value = total_taxable,
        total_cgst = total_cgst,
        total_sgst = total_sgst,
        total_igst = total_igst,
        total_cess = total_cess,
        total_tax  = total_tax,
        grand_total = grand_total,
        rounded_off = rounded_off,
        payable_amount = payable_amount,
    )

def apply_rounded_off(
        summary: InvoiceTaxSummary,
        rounded_off: Decimal,
)-> InvoiceTaxSummary:
    """
    Applies a rounding adjustment to an existing InvoiceTaxSummary.

    WHY A SEPARATE FUNCTION?
    aggregate_invoice_taxes() produces the mathematically precise total.
    The decision to round to the nearest rupee is a BUSINESS PREFERENCE,
    not a tax calculation. Separating this concern means aggregate_invoice_taxes()
    remains a pure arithmetic function that is always independently testable.
    """
    if abs(rounded_off) > MAX_ROUNDING_ADJUSTMENT:
        raise ValueError(
            f"Rounding adjustment cannot exceed ±{MAX_ROUNDING_ADJUSTMENT}"
            f"Received: {rounded_off}"
        )
    new_payable = _round(summary.grand_total + rounded_off)
    return replace(summary, rounded_off=rounded_off, payable_amount=new_payable)