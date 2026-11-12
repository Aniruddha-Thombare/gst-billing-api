/**
 * Money maths WITHOUT floating point (port of the verified plain-JS version).
 *
 * JavaScript numbers are floats: 0.1 + 0.2 = 0.30000000000000004. Money must never touch them.
 * Every amount here is a BigInt holding value x 10^SCALE, the same idea as keeping paise instead of rupees.
 * The rounding rules mirror backend app/domain/tax_engine.py (ROUND_HALF_UP to 0.01 per line), so the
 * total the form SENDS matches what the server computes. The server stays the authority; this is a preview.
 */
const SCALE = 10;
const UNIT = 10n ** BigInt(SCALE);
const PAISE = 10n ** BigInt(SCALE - 2);

/** "1234.5" -> working-precision BigInt. Throws on junk or too many decimal places. */
export function parseDecimal(text: string | null | undefined, maxPlaces = 4): bigint {
  const clean = String(text ?? "").trim();
  if (!/^\d+(\.\d+)?$/.test(clean)) throw new Error(`"${clean}" is not a valid number`);
  const [whole, frac = ""] = clean.split(".");
  if (frac.length > maxPlaces) throw new Error(`"${clean}" has more than ${maxPlaces} decimal places`);
  return BigInt(whole) * UNIT + BigInt(frac.padEnd(SCALE, "0"));
}

/** Round to 2 places, half-up (same as Python ROUND_HALF_UP). */
export const roundMoney = (value: bigint): bigint => ((value + PAISE / 2n) / PAISE) * PAISE;

/** Working-precision value (already rounded to 2 places) -> "1234.50". */
export function toPlain(value: bigint): string {
  const negative = value < 0n;
  const paise = (negative ? -value : value) / PAISE;
  return `${negative ? "-" : ""}${paise / 100n}.${String(paise % 100n).padStart(2, "0")}`;
}

export interface LineInput { quantity: string; rate: string; discount_percent: string; gst_rate: string; cess_rate: string; }
export interface LineResult { gross: bigint; discount: bigint; taxable: bigint; cgst: bigint; sgst: bigint; igst: bigint; cess: bigint; total: bigint; }

/** One line, exactly as the backend computes it. intrastate = CGST + SGST (half rate each); otherwise IGST. */
export function calcLine(line: LineInput, intrastate: boolean): LineResult {
  const quantity = parseDecimal(line.quantity, 3);
  const rate = parseDecimal(line.rate, 4);
  const discountPercent = parseDecimal(line.discount_percent || "0", 2);
  const gstRate = parseDecimal(line.gst_rate || "0", 3);
  const cessRate = parseDecimal(line.cess_rate || "0", 2);

  const grossExact = (rate * quantity) / UNIT;
  const discount = roundMoney((grossExact * discountPercent) / (100n * UNIT));
  const gross = roundMoney(grossExact);
  const taxable = roundMoney(gross - discount);

  const percentOf = (base: bigint, pct: bigint) => roundMoney((base * pct) / (100n * UNIT));
  let cgst = 0n, sgst = 0n, igst = 0n;
  if (intrastate) {
    const half = gstRate / 2n; // 18 -> 9 ; 0.25 -> 0.125 (exact)
    cgst = percentOf(taxable, half);
    sgst = percentOf(taxable, half);
  } else {
    igst = percentOf(taxable, gstRate);
  }
  const cess = percentOf(taxable, cessRate);
  return { gross, discount, taxable, cgst, sgst, igst, cess, total: roundMoney(taxable + cgst + sgst + igst + cess) };
}

export interface InvoiceResult { rows: LineResult[]; subtotal: bigint; discount: bigint; taxable: bigint; gst: bigint; cess: bigint; grand: bigint; }

/** Whole invoice: sums per-line results, as the backend does. `gst` is CGST+SGST+IGST together. */
export function calcInvoice(lines: LineInput[], intrastate: boolean): InvoiceResult {
  const rows = lines.map((l) => calcLine(l, intrastate));
  const sum = (pick: (r: LineResult) => bigint) => rows.reduce((acc, r) => acc + pick(r), 0n);
  const taxable = roundMoney(sum((r) => r.taxable));
  const gst = roundMoney(sum((r) => r.cgst + r.sgst + r.igst));
  const cess = roundMoney(sum((r) => r.cess));
  return { rows, subtotal: sum((r) => r.gross), discount: sum((r) => r.discount), taxable, gst, cess, grand: roundMoney(taxable + gst + cess) };
}
