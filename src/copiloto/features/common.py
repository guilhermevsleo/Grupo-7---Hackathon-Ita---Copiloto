"""Tipos e utilidades do motor de features determinístico (briefing §14–§15).

As funções de feature são puras: recebem um CaseData já carregado do cliente ativo
(pelo ScopedRepository) e devolvem Measurements com proveniência. Nenhuma toca o banco.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from ..repository import ScopedRepository
from ..schema_map import SchemaMap
from ..settings import FEATURE_ENGINE_VERSION, PRIOR_WINDOW, RECENT_WINDOW, WINDOW_END, WINDOW_START

MONTH_NAMES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
               "setembro", "outubro", "novembro", "dezembro"]
MONTH_ABBR = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def months_between(start: date, end: date) -> list[date]:
    out, cur = [], month_start(start)
    while cur <= end:
        out.append(cur)
        cur = month_end(cur) + timedelta(days=1)
    return out


WINDOW_MONTHS = months_between(WINDOW_START, WINDOW_END)
PRIOR_MONTHS = months_between(*PRIOR_WINDOW)
RECENT_MONTHS = months_between(*RECENT_WINDOW)


def fmt_month(d: date) -> str:
    return f"{MONTH_ABBR[d.month - 1]}/{d.year}"


def fmt_period(start: date, end: date) -> str:
    if start.year == end.year:
        return f"{MONTH_ABBR[start.month - 1]}–{MONTH_ABBR[end.month - 1]}/{end.year}"
    return f"{fmt_month(start)}–{fmt_month(end)}"


def fmt_date(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "sem data"


class Unit(str, Enum):
    BRL = "BRL_cents"
    PCT = "pct"
    COUNT = "count"
    DATE = "date"
    MONTH = "month"
    STATUS = "status"
    TABLE = "table"


class QualityStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


_ORDER = {QualityStatus.SUFFICIENT: 0, QualityStatus.PARTIAL: 1, QualityStatus.INSUFFICIENT: 2}


def worst(*statuses: QualityStatus) -> QualityStatus:
    return max(statuses, key=_ORDER.__getitem__) if statuses else QualityStatus.SUFFICIENT


@dataclass(frozen=True)
class Measurement:
    """Resultado determinístico com proveniência. Vira Evidence no P2."""
    key: str                      # identificador estável dentro do caso
    metric: str                   # código da métrica
    label: str                    # rótulo em português para o colaborador
    value: Any                    # int (centavos/contagem), Decimal (pct), date, str ou None
    unit: Unit
    period_start: date | None
    period_end: date | None
    source: str
    source_row_ids: tuple[str, ...]
    formula: str
    quality_metric: str           # métrica de qualidade que governa este valor
    limitations: tuple[str, ...] = ()
    sensitive: bool = False
    detail: tuple[dict, ...] = ()  # linhas de tabela, quando unit == TABLE
    formula_version: str = FEATURE_ENGINE_VERSION


class TxClass(str, Enum):
    OWN_TRANSFER = "OWN_TRANSFER"
    INVESTMENT_MOVEMENT = "INVESTMENT_MOVEMENT"
    EXTERNAL_INFLOW = "EXTERNAL_INFLOW"
    CARD_BILL_PAYMENT = "CARD_BILL_PAYMENT"
    LOAN_PAYMENT = "LOAN_PAYMENT"
    CASH_WITHDRAWAL = "CASH_WITHDRAWAL"
    ECONOMIC_EXPENSE = "ECONOMIC_EXPENSE"


@dataclass
class CaseData:
    """Todos os registros do cliente ativo, lidos uma vez pelo repositório com escopo."""
    customer_id: str
    case: dict
    profile: dict
    accounts: list[dict]
    transactions: list[dict]
    credit_cards: list[dict]
    card_transactions: list[dict]
    card_statements: list[dict]
    loans: list[dict]
    installments: list[dict]
    consents: list[dict]
    contacts: list[dict]
    renegotiations: list[dict]
    source_quality: list[dict]
    vocab: SchemaMap
    sensitive_categories: frozenset[str] = frozenset()
    sensitive_label: str = "categoria potencialmente sensível"
    _classes: dict[str, TxClass] = field(default_factory=dict)

    @classmethod
    def load(cls, repo: ScopedRepository, schema: SchemaMap, customer_id: str,
             sensitive_categories: frozenset[str] = frozenset(),
             sensitive_label: str = "categoria potencialmente sensível") -> "CaseData":
        data = cls(
            customer_id=customer_id,
            case=repo.get_case(),
            profile=repo.get_customer_profile(),
            accounts=repo.get_accounts(),
            transactions=[t for t in repo.get_transactions() if t["date"] and WINDOW_START <= t["date"] <= WINDOW_END],
            credit_cards=repo.get_credit_cards(),
            card_transactions=[t for t in repo.get_card_transactions() if t["date"] and WINDOW_START <= t["date"] <= WINDOW_END],
            card_statements=repo.get_card_statements(),
            loans=repo.get_loans(),
            installments=repo.get_installments(),
            consents=repo.get_consents(),
            contacts=repo.get_contacts(),
            renegotiations=repo.get_renegotiations(),
            source_quality=repo.get_source_quality(),
            vocab=schema,
            sensitive_categories=sensitive_categories,
            sensitive_label=sensitive_label,
        )
        data.classify_all()
        return data

    # ------------------------------------------------------------------ classificação
    def v(self, concept: str) -> frozenset[str]:
        return self.vocab.values(concept)

    @property
    def own_account_ids(self) -> set[str]:
        return {a["account_id"] for a in self.accounts}

    def classify_all(self) -> None:
        own = self.own_account_ids
        for t in self.transactions:
            self._classes[t["transaction_id"]] = self._classify(t, own)

    def _classify(self, t: dict, own: set[str]) -> TxClass:
        is_credit = t["direction"] in self.v("direction_credit")
        ttype, cat = t["transaction_type"], t["category"]
        own_flag = bool(t["own_transfer_flag"]) or (t.get("counterparty_id") or "") in own
        if ttype in self.v("investment_redemption") or (own_flag and cat == "INVESTMENT"):
            return TxClass.INVESTMENT_MOVEMENT
        if own_flag:
            return TxClass.OWN_TRANSFER
        if is_credit:
            return TxClass.EXTERNAL_INFLOW
        if ttype in self.v("card_bill_payment"):
            return TxClass.CARD_BILL_PAYMENT
        if ttype in self.v("loan_payment"):
            return TxClass.LOAN_PAYMENT
        if ttype in self.v("cash_withdrawal"):
            return TxClass.CASH_WITHDRAWAL
        return TxClass.ECONOMIC_EXPENSE

    def tx_class(self, t: dict) -> TxClass:
        return self._classes[t["transaction_id"]]

    def is_credit(self, t: dict) -> bool:
        return t["direction"] in self.v("direction_credit")

    def account(self, account_id: str) -> dict | None:
        return next((a for a in self.accounts if a["account_id"] == account_id), None)

    def is_open_finance(self, account: dict) -> bool:
        return account.get("source") in self.v("source_open_finance")

    def primary_account(self) -> dict | None:
        flagged = [a for a in self.accounts if a.get("is_primary")]
        if flagged:
            return flagged[0]
        core = [a for a in self.accounts if a.get("source") in self.v("source_core")]
        return core[0] if core else None

    def quality_row(self, logical_source: str) -> dict | None:
        for row in self.source_quality:
            if self.vocab.quality_source_for(row["source_name"]) == logical_source:
                return row
        return None

    def consent(self) -> dict | None:
        return self.consents[0] if self.consents else None

    def is_sensitive(self, category: str | None) -> bool:
        return (category or "").upper() in self.sensitive_categories


def ids(rows) -> tuple[str, ...]:
    out = []
    for r in rows:
        for key in ("transaction_id", "card_transaction_id", "statement_id", "installment_id",
                    "contract_id", "agreement_id", "contact_id", "card_id", "account_id", "consent_id"):
            if r.get(key):
                out.append(r[key])
                break
    return tuple(out)


def dec(value) -> Decimal | None:
    return None if value is None else Decimal(value)
