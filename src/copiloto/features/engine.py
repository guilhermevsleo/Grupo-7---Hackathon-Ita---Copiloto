"""Orquestra o motor de features determinístico para o caso ativo (P1)."""
from __future__ import annotations

from dataclasses import dataclass

from .common import CaseData, Measurement
from .credit import (CreditHistoryResult, analyze_credit_history, calculate_credit_utilization,
                     calculate_debt_service_ratio, reconcile_card_transactions)
from .flows import (ExpenseResult, IncomeResult, TransfersResult, calculate_expense_shift,
                    calculate_income_shift, calculate_monthly_cashflow, detect_internal_transfers)
from .history import ContactSummary, analyze_previous_renegotiations, summarize_contact_history
from .quality import DataQualityResult, check_data_quality
from .timeline import TimelineDraft, build_delinquency_timeline


@dataclass
class FeatureResult:
    data: CaseData
    quality: DataQualityResult
    transfers: TransfersResult
    income: IncomeResult
    expense: ExpenseResult
    credit: CreditHistoryResult
    contacts: ContactSummary
    measurements: dict[str, Measurement]
    timeline: list[TimelineDraft]


def run_features(data: CaseData) -> FeatureResult:
    quality = check_data_quality(data)  # qualidade antes de qualquer cálculo narrativo
    transfers = detect_internal_transfers(data)
    income = calculate_income_shift(data, quality)
    expense = calculate_expense_shift(data, quality)
    credit = analyze_credit_history(data, quality)
    contacts = summarize_contact_history(data, quality)
    ordered: list[Measurement] = [
        *quality.measurements,
        *income.measurements,
        *transfers.measurements,
        *expense.measurements,
        *calculate_credit_utilization(data, quality),
        calculate_debt_service_ratio(data, quality),
        *credit.measurements,
        *reconcile_card_transactions(data),
        *analyze_previous_renegotiations(data),
        *contacts.measurements,
        calculate_monthly_cashflow(data, quality),
    ]
    measurements: dict[str, Measurement] = {}
    for m in ordered:
        if m.key in measurements:
            raise ValueError(f"Chave de medição duplicada: {m.key}")
        measurements[m.key] = m
    timeline = build_delinquency_timeline(data, measurements)
    return FeatureResult(data, quality, transfers, income, expense, credit, contacts, measurements, timeline)
