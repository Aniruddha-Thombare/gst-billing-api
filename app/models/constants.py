# Regex constants - defined once, reference for constraints 
# GSTIN format: 2-digit state | 10 - digit PAN | 1 entity number 
#               | a default 'Z' | 1 checksum
# PAN format: 5 letters | 4 digits | 1 letter
# STATE CODE: 2 digits
# Pincode: 6 digits 

GSTIN_REGEX = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
PAN_REGEX   = r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$"
STATE_CODE_REGEX = r"^[0-9]{2}$"
PIN_CODE_REGEX = r"^[1-9][0-9]{5}$"


# financial year format: "2025-26" = always 7 characters 
FINANCIAL_YEAR_REGEX = r"^[0-9]{4}-[0-9]{2}$"

# prefix format - "INV" or "INV/2024"
# Allowed Characters: Only uppercase letters (A-Z), numbers (0-9), 
# and hyphens (-) are permitted. No spaces, dots, or special symbols.
PREFIX_REGEX = r"^[A-Z0-9\-]{1,20}$"

# HSN codes are 4, 6, or 8 digits. SAC codes are exactly 6 digits. 
# Free text passes silently — "ABCDEFGH" is accepted. 
# For GSTR-1 filing, invalid HSN/SAC codes cause portal rejection.
HSN_SAC_CODE_REGEX = r"^[0-9]{4,8}$"

