from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum


class DocType(str, Enum):
    TRANSACTION = "transaction"                  # חשבון עסקה
    TAX_INVOICE = "tax_invoice"                  # חשבונית מס
    TAX_INVOICE_RECEIPT = "tax_invoice_receipt"  # חשבונית מס קבלה
    CREDIT = "credit"                            # חשבונית זיכוי
    IGNORED = "ignored"                          # קבלה, הצעת מחיר וכו' – לא נכנס לחישוב


DOC_TYPE_HE = {
    DocType.TRANSACTION: "חשבון עסקה",
    DocType.TAX_INVOICE: "חשבונית מס",
    DocType.TAX_INVOICE_RECEIPT: "חשבונית מס קבלה",
    DocType.CREDIT: "זיכוי",
    DocType.IGNORED: "לא בחישוב",
}


@dataclass
class Document:
    row_ref: str            # מזהה שורה בלוח (item id) או מספר שורה בקובץ
    customer_key: str       # מפתח לקוח מנורמל
    customer_name: str      # שם תצוגה
    doc_type: DocType
    amount: Decimal         # הסכום כפי שנרשם בלוח (לאחר פענוח)
    doc_date: date | None = None
    doc_number: str = ""
    raw_type: str = ""
    contact: str = ""
    group: str = ""
    effect: Decimal | None = None   # ההשפעה בפועל על יתרת החוב (נקבע במנוע)


@dataclass
class Issue:
    severity: str           # error / warning / info
    code: str
    message: str
    row_ref: str = ""
    customer: str = ""


@dataclass
class CustomerBalance:
    customer_key: str
    customer_name: str
    contact: str = ""
    transactions: Decimal = Decimal("0")
    tax_invoices: Decimal = Decimal("0")
    tax_invoice_receipts: Decimal = Decimal("0")
    credits: Decimal = Decimal("0")
    debt: Decimal = Decimal("0")
    counts: dict = field(default_factory=dict)
    oldest_open_date: date | None = None
    oldest_open_days: int | None = None
    aging: dict = field(default_factory=dict)
    open_transactions: list = field(default_factory=list)   # [(Document, open_amount)]
    documents: list = field(default_factory=list)
    priority: str = ""      # דחוף / לטיפול / מעקב / תקין / חריג
    reasons: list = field(default_factory=list)

    @property
    def formula(self) -> str:
        return (f"{self.transactions:,.2f} − {self.tax_invoices:,.2f} − {self.tax_invoice_receipts:,.2f}"
                f" + {self.credits:,.2f} = {self.debt:,.2f}")
