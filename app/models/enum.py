from enum import Enum

# Belongs to Tenant table 
class RegistrationType(str,Enum):
    """
    Defining strict choices for Registration Type. 
    Enforcing a Business should belong to these three type of registration. 
    Values provided should exactly match the requirement. 

    Threshold limit (Rs. 40 lakhs for goods, Rs. 20 lakhs for services - it varies by state)
    - Regular: Standard Tax Payers. With turnover > Threshold limit(usually more than 1.5 cr). 
            Pay a standard GST rate - from 0%, 5%,12%, 18%, etc - based on goods/services.
            Collect taxes and ELigible for ITC claim.  Eg: B2B, maufacturers,etc
    - Composition: Small Tax Payers.With turnover (upto 1.5 cr for goods or Rs. 50 lakhs for services) 
            Pay a fixed 1% - 6% on turnover 
            No collection of tax and ITC claim. Eg: Local cafes, neighbourhood Kirana shops. 
    - Unregistered: Businesses with turnover less than threshold limit or dealing in exempted goods. 
            Pay 0% tax rate and don't need to collect or pay GST. No ITC claim 
            Eg: Small artisans, small traders, new startups. 
    
    """
    REGULAR = "regular"
    COMPOSITION = "composition"
    UNREGISTERED = "unregistered"

# Beliongs to User Table 
class UserRole(str, Enum):
    """
    Defines strict constants to different types of Owner
    Enforcing the role of the Authenticated user must belong to these four constants

    - OWNER: Full access of the Saas platform - manages users, locks invoices, delete records.
    - ACCOUNTANT: Operational Access - create/edit the invoices, records payments.
    - VIEWER: Read Only - view invoices, partiess, reports. Cannot mutate.
    - AUDITOR: Restricted read - view only invoices and audit logs only. 
            Cannot view party contact details or financial settings. 
    """
    OWNER = "owner"
    ACCOUNTANT = "accountant"
    VIEWER = "viewer"
    AUDITOR = "auditor"

# Belongs to Party Table 
class PartyType(str, Enum):
    """
    Determines the direction of transactions for this party.

    CUSTOMER: appears on sales invoices (outward supply)
    VENDOR: appears on purchase invoices (inward supply / ITC claims)
    """
    CUSTOMER = "customer" 
    VENDOR = "vendor"  

# Belongs to Payment Table 
class PaymentMode(str, Enum):
    """
    Defines Constants for the legally recognized methods of payment settlement.
    A list of allowed ways a customer can pay their bill.

    It ensures the system only accepts standard payment types like cash, UPI, 
    Bank Transfer, cheques and cards. This is critical for generating "Mode - wise"
    collections reports at the end of the day.

    """
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    UPI = "upi"
    CHEQUE = "cheque"
    CREDIT_CARD = "credit_card"

# Belongs to Invoice, Sequence Table 
class InvoiceType(str, Enum):
    """
    It Identifies the direction and nature of the document.
    - SALES = Outward supply - representing transfer of goods and services
    - PURCHASE = Inward Supply - representing receipt of goods and services 
    - Credit_note and Debit_note = Adjustments to above documents 
        Issued to ammend original tax invoices.
    """
    SALES = "sales"
    PURCHASE = "purchase"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"

# Belongs to Invoice Table 
class SupplyType(str, Enum):
    """
    It drives the GST logic. Compare Tenant state VS Party state to trigger either CGST + SGST or IGST.
    - Intrastate = When Tenant state code is same as Party state code.
        That means the transaction between both parties has taken place within same state or Union territory 
        It attracts CGST (Central GST) and SGST/UTGST (State/ Union territory GST)
    - Interstate = When Tenant state code is not same as Party state code.
        That means the transaction between both parties has taken place within two diff state.
        It attracts Integrated GST (IGST)
    - Export = When the place of supply is outside India 
        That means the transaction has taken place between two parties located at diff countries. 
        It attracts Zero tax rate  
    """
    INTRASTATE = "intrastate"   
    INTERSTATE = "interstate"   
    EXPORT = "export" 
    SEZ = "sez"     

# Belongs to Invoice Table 
class InvoiceStatus(str, Enum):
    """
    Tracks the legal and operational lifecycle of a financial document.

    This status dictates whether a document is editable, legally issued, or 
    invalidated for audit purposes.

    Attributes:
        DRAFT: Initial state; the document is editable and has no legal standing.
        SENT: The invoice has been formally issued to the counterparty.
        PARTIAL: The document is active, and a portion of the balance has been cleared.
        PAID: The financial obligation for this invoice is fully settled.
        OVERDUE: The document remains unpaid past its designated due_date.
        CANCELLED: The document was stopped before it became a final legal record.
        VOID: A legally issued document that has been invalidated while preserving the audit trail.
    """
    DRAFT = "draft"
    SENT = "sent"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    VOID = "void"

# Belongs to Invoice Table 
class PaymentStatus(str, Enum):
    """
    Categorizes the specific state of fund collection or disbursement.

    PaymentStatus focuses strictly on the reconciliation of the total_amount.

    Attributes:
        UNPAID: No payments have been recorded or processed for this invoice.
        PARTIAL: Some payments have been applied, but an outstanding balance remains.
        PAID: The total_amount has been fully reconciled and matched by payment records.
    """
    UNPAID = "unpaid"
    PARTIAL = "partial"
    PAID = "paid"

# Belongs to Audit_log Table 
class EntityType(str, Enum):
    """
    Defining the strict constants to different types of Entities. 

    Classifies the specific database model or business object being audited.
    
    This Enum identifies which part of the system the 'entity_id' refers to, 
    allowing the audit trail to distinguish between changes to an invoice, 
    a payment, or a user profile.
    """
    TENANT = "tenant"
    USER = "user"
    PARTY = "party"
    INVOICE = "invoice"
    ITEM = "invoice_item"
    SEQUENCE = "sequence"
    PAYMENT = "payment"

# Belongs to Audit_log Table 
class AuditAction(str, Enum):
    """
    Defining the strict constants to the action taken for audit trail

    Defines the specific operation performed during a logged event.
    
    These constants capture the 'verb' of the transaction, distinguishing 
    between data mutations (CREATE/UPDATE/DELETE), security events (LOGIN), 
    and sensitive data access (EXPORT).
    """
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    EXPORT = "export"

