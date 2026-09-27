"""Fluxos da conta: transferências próprias, fluxo de caixa, entradas e despesas (briefing §14–§15).

Regras obrigatórias:
- Transferência própria não é renda nem consumo.
- Resgate de investimento é movimentação patrimonial/liquidez, não renda recorrente.
- Compra no cartão + pagamento de fatura não são duas despesas: despesa econômica conta as
  compras; o pagamento aparece só no fluxo de caixa.
- Pix de terceiro é entrada observada, não renda recorrente.
- Renda declarada não é tratada como atual.
- Ausência de dado nunca vira zero: janelas sem visibilidade constante não são comparadas.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from ..money import avg_cents, fmt_brl, pct_change
from ..settings import PRIOR_WINDOW, RECENT_WINDOW, WINDOW_END, WINDOW_START
from .common import (PRIOR_MONTHS, RECENT_MONTHS, WINDOW_MONTHS, CaseData, Measurement, QualityStatus,
                     TxClass, Unit, fmt_month, ids)
from .quality import DataQualityResult

I = QualityStatus.INSUFFICIENT
RECURRING_MIN_MONTHS = 3  # DECISIONS.md D-01


def _in(months: list[date], d: date) -> bool:
    return d.replace(day=1) in months


# ---------------------------------------------------------------------- transferências próprias
@dataclass
class TransfersResult:
    pairs: list[tuple[str, str]]
    unmatched: list[dict]
    own_transfers: list[dict]
    redemptions_in: list[dict]
    measurements: list[Measurement]


def detect_internal_transfers(data: CaseData) -> TransfersResult:
    own = [t for t in data.transactions if data.tx_class(t) == TxClass.OWN_TRANSFER]
    redemptions = [t for t in data.transactions
                   if data.tx_class(t) == TxClass.INVESTMENT_MOVEMENT and data.is_credit(t)]
    pairs, used = [], set()
    debits = [t for t in own if not data.is_credit(t)]
    credits = [t for t in own if data.is_credit(t)]
    for out in debits:
        match = next((c for c in credits if c["transaction_id"] not in used and c["date"] == out["date"]
                      and c["amount"] == out["amount"] and c["account_id"] == out.get("counterparty_id")
                      and c.get("counterparty_id") == out["account_id"]), None)
        if match:
            used.add(match["transaction_id"])
            pairs.append((out["transaction_id"], match["transaction_id"]))
    paired_ids = {i for p in pairs for i in p}
    unmatched = [t for t in own if t["transaction_id"] not in paired_ids]
    total_out = sum(t["amount"] for t in debits)
    ms: list[Measurement] = []
    if own:
        ms.append(Measurement(
            "own_transfer_pairs", "own_transfer_pairs", "Pares de transferência entre contas próprias",
            len(pairs), Unit.COUNT, WINDOW_START, WINDOW_END, "transactions", tuple(paired_ids),
            "pares com mesma data e valor, sentidos opostos e contas invertidas", "income_shift",
            ("Não são renda nem consumo; excluídos das entradas e das despesas.",)))
    if debits:
        ms.append(Measurement(
            "own_transfer_out_total", "own_transfer_out_total",
            "Total enviado entre contas próprias (excluído de despesas)", total_out, Unit.BRL,
            WINDOW_START, WINDOW_END, "transactions", ids(debits),
            "soma dos débitos marcados como transferência própria", "expense_shift"))
    if unmatched:
        ms.append(Measurement(
            "own_transfer_unmatched", "own_transfer_unmatched",
            "Transferências próprias sem contrapartida observada", len(unmatched), Unit.COUNT,
            WINDOW_START, WINDOW_END, "transactions", ids(unmatched),
            "lançamentos marcados como próprios sem par de sentido oposto", "income_shift",
            ("A ausência do outro lado não os transforma em consumo ou renda.",)))
    if redemptions:
        ms.append(Measurement(
            "investment_redemptions", "investment_redemptions_total", "Resgates de investimento recebidos",
            sum(t["amount"] for t in redemptions), Unit.BRL, WINDOW_START, WINDOW_END, "transactions",
            ids(redemptions), "soma dos créditos de resgate de aplicação própria", "income_shift",
            ("Movimentação patrimonial (liquidez); não é renda recorrente.",)))
    return TransfersResult(pairs, unmatched, own, redemptions, ms)


# ---------------------------------------------------------------------- fluxo de caixa mensal
def calculate_monthly_cashflow(data: CaseData, quality: DataQualityResult) -> Measurement:
    rows = []
    ever_visible = [a for a, months in quality.visibility.items() if any(months.values())]
    for m in WINDOW_MONTHS:
        acc = defaultdict(int)
        for t in data.transactions:
            if t["date"].replace(day=1) != m:
                continue
            cls = data.tx_class(t)
            if cls == TxClass.OWN_TRANSFER:
                continue
            acc[(cls, data.is_credit(t))] += t["amount"]
        # Visibilidade constante: toda conta que é visível em algum mês precisa estar visível neste mês
        # (contas nunca visíveis ficam fora do escopo em todos os meses, como na regra D-04).
        visible = all(quality.visibility[a].get(m, False) for a in ever_visible) if ever_visible else False
        card = sum(t["amount"] for t in data.card_transactions
                   if t["date"].replace(day=1) == m and (not t.get("status") or t["status"] in data.v("card_posted")))
        row = {
            "mes": fmt_month(m),
            "entradas_externas": acc[(TxClass.EXTERNAL_INFLOW, True)],
            "resgates": acc[(TxClass.INVESTMENT_MOVEMENT, True)],
            "despesas_debito": acc[(TxClass.ECONOMIC_EXPENSE, False)],
            "compras_cartao": card,
            "despesa_economica": acc[(TxClass.ECONOMIC_EXPENSE, False)] + card,
            "pagamento_fatura": acc[(TxClass.CARD_BILL_PAYMENT, False)],
            "parcelas_emprestimo": acc[(TxClass.LOAN_PAYMENT, False)],
            "saques": acc[(TxClass.CASH_WITHDRAWAL, False)],
            "fontes_visiveis": visible,
        }
        row["saldo_do_mes"] = (row["entradas_externas"] + row["resgates"] - row["despesas_debito"]
                               - row["pagamento_fatura"] - row["parcelas_emprestimo"] - row["saques"])
        rows.append(row)
    return Measurement(
        "monthly_cashflow", "monthly_cashflow", "Fluxo de caixa mensal das contas visíveis", None, Unit.TABLE,
        WINDOW_START, WINDOW_END, "transactions", ids(data.transactions),
        "saldo do mês = entradas externas + resgates − débitos de consumo − fatura − parcelas − saques "
        "(transferências entre contas próprias excluídas); despesa econômica = débitos de consumo + compras no cartão",
        "income_shift",
        ("Fluxo de caixa ≠ despesa econômica: o saldo usa o pagamento da fatura; a despesa econômica usa as compras.",
         "Meses sem visibilidade constante das fontes não devem ser lidos como valor zero."),
        detail=tuple(rows))


# ---------------------------------------------------------------------- entradas
def _recurring_groups(data: CaseData, inflows: list[dict]) -> set[str]:
    months_by_group: dict[str, set[date]] = defaultdict(set)
    for t in inflows:
        months_by_group[_group_key(t)].add(t["date"].replace(day=1))
    return {g for g, ms in months_by_group.items() if len(ms) >= RECURRING_MIN_MONTHS}


def _group_key(t: dict) -> str:
    cp = (t.get("counterparty_id") or "").strip()
    return cp or f'{t.get("counterparty_type") or "?"}:{t.get("category") or "?"}'


@dataclass
class IncomeResult:
    status: QualityStatus
    change_pct: object
    recurring_change_pct: object
    drop_start_month: date | None
    measurements: list[Measurement]


def calculate_income_shift(data: CaseData, quality: DataQualityResult) -> IncomeResult:
    mq = quality.metrics["income_shift"]
    inflows = [t for t in data.transactions if data.tx_class(t) == TxClass.EXTERNAL_INFLOW]
    prior = [t for t in inflows if _in(PRIOR_MONTHS, t["date"])]
    recent = [t for t in inflows if _in(RECENT_MONTHS, t["date"])]
    third = [t for t in inflows if t.get("counterparty_type") in data.v("person_counterparty")]
    lims = tuple(mq.limitations) + ("Queda de entradas observadas não prova perda de emprego ou de renda.",)
    ms: list[Measurement] = []

    declared = data.profile.get("declared_income")
    if declared is not None:
        ms.append(Measurement(
            "declared_income", "declared_monthly_income", "Renda mensal declarada no cadastro", declared,
            Unit.BRL, None, None, "customers", (data.customer_id,), "valor declarado no cadastro",
            "income_shift", ("Sem data de atualização nem fonte; não é tratada como renda atual observada.",)))

    if third:
        ms.append(Measurement(
            "third_party_pix", "third_party_inflows_total", "Entradas de pessoas físicas (Pix de terceiros)",
            sum(t["amount"] for t in third), Unit.BRL, WINDOW_START, WINDOW_END, "transactions", ids(third),
            "soma dos créditos de contraparte pessoa física, não próprios", "income_shift",
            ("Entrada observada; não significa salário nem renda recorrente.",)))

    if mq.status == I:
        ms.append(Measurement(
            "income_shift_unavailable", "external_inflow_change_3m", "Variação das entradas externas observadas",
            None, Unit.PCT, PRIOR_WINDOW[0], RECENT_WINDOW[1], "transactions + consents", ids(inflows),
            "comparação não realizada: visibilidade das fontes mudou entre as janelas", "income_shift",
            (mq.reason,) + lims))
        return IncomeResult(mq.status, None, None, None, ms)

    prior_avg = avg_cents(sum(t["amount"] for t in prior), len(PRIOR_MONTHS))
    recent_avg = avg_cents(sum(t["amount"] for t in recent), len(RECENT_MONTHS))
    change = pct_change(recent_avg, prior_avg)
    formula = "média mensal = soma dos créditos externos (não próprios, sem resgates) na janela ÷ 3"
    ms += [
        Measurement("inflow_prior", "external_inflow_avg_prior", "Entradas externas observadas — média mensal",
                    prior_avg, Unit.BRL, *PRIOR_WINDOW, "transactions", ids(prior), formula, "income_shift", lims),
        Measurement("inflow_recent", "external_inflow_avg_recent", "Entradas externas observadas — média mensal",
                    recent_avg, Unit.BRL, *RECENT_WINDOW, "transactions", ids(recent), formula, "income_shift", lims),
        Measurement("inflow_change", "external_inflow_change_3m", "Variação das entradas externas observadas",
                    change, Unit.PCT, PRIOR_WINDOW[0], RECENT_WINDOW[1], "transactions", ids(prior + recent),
                    "100 × (média jun–ago − média mar–mai) ÷ média mar–mai", "income_shift", lims),
    ]

    recurring_change, drop_month = None, None
    primary_uncertain = any("não são tratados como renda comprovada" in l for l in mq.limitations)
    groups = _recurring_groups(data, inflows)
    rec_prior = [t for t in prior if _group_key(t) in groups]
    rec_recent = [t for t in recent if _group_key(t) in groups]
    if groups and not primary_uncertain:
        rp = avg_cents(sum(t["amount"] for t in rec_prior), len(PRIOR_MONTHS))
        rr = avg_cents(sum(t["amount"] for t in rec_recent), len(RECENT_MONTHS))
        recurring_change = pct_change(rr, rp)
        rec_formula = (f"entradas de contrapartes presentes em ≥ {RECURRING_MIN_MONTHS} meses distintos da janela "
                       "de 12 meses; média mensal por janela")
        rec_lims = lims + ("Recorrência identificada por padrão de contraparte, não por comprovação de vínculo.",)
        ms += [
            Measurement("recurring_prior", "recurring_inflow_avg_prior", "Entradas recorrentes identificáveis — média mensal",
                        rp, Unit.BRL, *PRIOR_WINDOW, "transactions", ids(rec_prior), rec_formula, "income_shift", rec_lims),
            Measurement("recurring_recent", "recurring_inflow_avg_recent", "Entradas recorrentes identificáveis — média mensal",
                        rr, Unit.BRL, *RECENT_WINDOW, "transactions", ids(rec_recent), rec_formula, "income_shift", rec_lims),
            Measurement("recurring_change", "recurring_inflow_change_3m", "Variação das entradas recorrentes identificáveis",
                        recurring_change, Unit.PCT, PRIOR_WINDOW[0], RECENT_WINDOW[1], "transactions",
                        ids(rec_prior + rec_recent), "100 × (média jun–ago − média mar–mai) ÷ média mar–mai",
                        "income_shift", rec_lims),
        ]
        by_month = defaultdict(int)
        for t in rec_recent:
            by_month[t["date"].replace(day=1)] += t["amount"]
        drop_month = next((m for m in RECENT_MONTHS if rp and by_month[m] < rp * 0.8), None)
    elif primary_uncertain:
        ms.append(Measurement(
            "recurring_unavailable", "recurring_inflow_change_3m", "Entradas recorrentes identificáveis",
            None, Unit.PCT, PRIOR_WINDOW[0], RECENT_WINDOW[1], "transactions + data_quality", ids(inflows),
            "não calculado: classificação de renda da conta principal é incerta", "income_shift", lims))

    if drop_month is None and change is not None and change <= -20:
        by_month = defaultdict(int)
        for t in recent:
            by_month[t["date"].replace(day=1)] += t["amount"]
        drop_month = next((m for m in RECENT_MONTHS if by_month[m] < prior_avg * 0.8), None)
    if drop_month:
        ms.append(Measurement(
            "inflow_drop_start", "inflow_drop_start_month", "Primeiro mês com entradas abaixo de 80% da média anterior",
            drop_month, Unit.MONTH, drop_month, drop_month, "transactions", ids(rec_recent or recent),
            "primeiro mês de jun–ago/2026 com entradas < 80% da média de mar–mai/2026", "income_shift", lims))
    return IncomeResult(mq.status, change, recurring_change, drop_month, ms)


# ---------------------------------------------------------------------- despesas
@dataclass
class ExpenseResult:
    status: QualityStatus
    change_pct: object
    isolated_peak_month: date | None
    measurements: list[Measurement]


def _expense_items(data: CaseData) -> list[dict]:
    items = []
    for t in data.card_transactions:
        if t.get("status") and t["status"] not in data.v("card_posted"):
            continue
        items.append({"id": t["card_transaction_id"], "date": t["date"], "amount": t["amount"],
                      "category": (t.get("category") or "SEM_CATEGORIA").upper(), "origin": "cartão"})
    for t in data.transactions:
        if data.tx_class(t) == TxClass.ECONOMIC_EXPENSE:
            items.append({"id": t["transaction_id"], "date": t["date"], "amount": t["amount"],
                          "category": (t.get("category") or "SEM_CATEGORIA").upper(), "origin": "conta"})
    return items


def calculate_expense_shift(data: CaseData, quality: DataQualityResult) -> ExpenseResult:
    mq = quality.metrics["expense_shift"]
    items = _expense_items(data)
    withdrawals = [t for t in data.transactions if data.tx_class(t) == TxClass.CASH_WITHDRAWAL]
    lims = tuple(mq.limitations)
    ms: list[Measurement] = []
    if withdrawals:
        ms.append(Measurement(
            "cash_withdrawals", "cash_withdrawals_total", "Saques em dinheiro (destino não identificado)",
            sum(t["amount"] for t in withdrawals), Unit.BRL, WINDOW_START, WINDOW_END, "transactions",
            ids(withdrawals), "soma dos saques", "expense_shift",
            ("Saque prova retirada de caixa, não consumo final identificado.",)))
    if mq.status == I:
        ms.append(Measurement(
            "expense_shift_unavailable", "economic_expense_change_3m", "Variação da despesa econômica observada",
            None, Unit.PCT, PRIOR_WINDOW[0], RECENT_WINDOW[1], "transactions + card_transactions",
            tuple(i["id"] for i in items), "comparação não realizada: visibilidade incompleta", "expense_shift",
            (mq.reason,) + lims))
        return ExpenseResult(mq.status, None, None, ms)

    prior = [i for i in items if _in(PRIOR_MONTHS, i["date"])]
    recent = [i for i in items if _in(RECENT_MONTHS, i["date"])]
    prior_avg = avg_cents(sum(i["amount"] for i in prior), 3)
    recent_avg = avg_cents(sum(i["amount"] for i in recent), 3)
    change = pct_change(recent_avg, prior_avg)
    formula = "compras no cartão + débitos de consumo na conta, média mensal por janela"
    ms += [
        Measurement("expense_prior", "economic_expense_avg_prior", "Despesa econômica observada — média mensal",
                    prior_avg, Unit.BRL, *PRIOR_WINDOW, "card_transactions + transactions",
                    tuple(i["id"] for i in prior), formula, "expense_shift", lims),
        Measurement("expense_recent", "economic_expense_avg_recent", "Despesa econômica observada — média mensal",
                    recent_avg, Unit.BRL, *RECENT_WINDOW, "card_transactions + transactions",
                    tuple(i["id"] for i in recent), formula, "expense_shift", lims),
        Measurement("expense_change", "economic_expense_change_3m", "Variação da despesa econômica observada",
                    change, Unit.PCT, PRIOR_WINDOW[0], RECENT_WINDOW[1], "card_transactions + transactions",
                    tuple(i["id"] for i in prior + recent), "100 × (média jun–ago − média mar–mai) ÷ média mar–mai",
                    "expense_shift", lims),
    ]

    # Pico isolado (eval 18): um único mês acima de 150% da média anterior e os outros dois estáveis.
    by_month = defaultdict(int)
    for i in recent:
        by_month[i["date"].replace(day=1)] += i["amount"]
    peak_month = None
    if prior_avg:
        high = [m for m in RECENT_MONTHS if by_month[m] > prior_avg * 1.5]
        stable = [m for m in RECENT_MONTHS if abs(by_month[m] - prior_avg) <= prior_avg * 0.2]
        if len(high) == 1 and len(stable) == 2:
            peak_month = high[0]
            peak_items = [i for i in recent if i["date"].replace(day=1) == peak_month]
            biggest = max(peak_items, key=lambda i: i["amount"])
            ms.append(Measurement(
                "expense_isolated_peak", "economic_expense_isolated_peak", "Mês com despesa pontualmente elevada",
                peak_month, Unit.MONTH, peak_month, peak_month, "card_transactions + transactions",
                tuple(i["id"] for i in peak_items),
                "único mês de jun–ago/2026 acima de 150% da média de mar–mai/2026, com os outros dois meses "
                "a ±20% dessa média", "expense_shift",
                (f"Maior lançamento do mês: {fmt_brl(biggest['amount'])}. Um pico isolado não indica, sozinho, "
                 "mudança de padrão.",)))

    # Categorias com mudança material (|Δ| ≥ 30% e ≥ R$ 100/mês); sensíveis ficam marcadas.
    cats = defaultdict(lambda: [0, 0, [], []])
    for i in prior:
        cats[i["category"]][0] += i["amount"]
        cats[i["category"]][2].append(i["id"])
    for i in recent:
        cats[i["category"]][1] += i["amount"]
        cats[i["category"]][3].append(i["id"])
    for cat, (p, r, pids, rids) in sorted(cats.items()):
        pa, ra = avg_cents(p, 3), avg_cents(r, 3)
        delta = pct_change(ra, pa)
        if delta is None or abs(delta) < 30 or abs(ra - pa) < 10_000:
            continue
        recent_months_for_cat = {i["date"].replace(day=1) for i in recent if i["category"] == cat}
        if peak_month and recent_months_for_cat == {peak_month}:
            continue  # gasto concentrado no mês do pico: já descrito como pico isolado
        sensitive = data.is_sensitive(cat)
        ms.append(Measurement(
            f"category_change_{cat.lower()}", "expense_category_change_3m",
            f"Despesas na categoria {cat.title()}" if not sensitive else f"Despesas na categoria {cat.title()} "
            "(potencialmente sensível)", delta, Unit.PCT, PRIOR_WINDOW[0], RECENT_WINDOW[1],
            "card_transactions + transactions", tuple(pids + rids),
            f"média mensal mar–mai: {fmt_brl(pa)}; jun–ago: {fmt_brl(ra)}; 100 × (jun–ago − mar–mai) ÷ mar–mai",
            "expense_shift",
            (("Mudança financeira observada; não indica condição pessoal.",) if sensitive else ()) + lims,
            sensitive=sensitive))
    return ExpenseResult(mq.status, change, peak_month, ms)
