"""Valores monetários em centavos inteiros e formatação pt-BR (sem float em cálculos)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ONE_DECIMAL = Decimal("0.1")


def to_cents(value) -> int | None:
    """Converte o valor da base (REAL/TEXT em reais) para centavos. None/'' viram None, nunca zero."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    return int(amount * 100)


def pct_change(recent_cents: int, prior_cents: int) -> Decimal | None:
    """Variação relativa em pontos percentuais com 1 casa: 100 * (recente - anterior) / anterior.
    Denominador zero => indisponível (None), nunca infinito (ANALISE §5)."""
    if prior_cents == 0:
        return None
    value = Decimal(100) * (Decimal(recent_cents) - Decimal(prior_cents)) / Decimal(prior_cents)
    return value.quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


def ratio_pct(numerator_cents: int, denominator_cents: int) -> Decimal | None:
    if denominator_cents <= 0:
        return None
    value = Decimal(100) * Decimal(numerator_cents) / Decimal(denominator_cents)
    return value.quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


def avg_cents(total_cents: int, months: int) -> int:
    return int((Decimal(total_cents) / Decimal(months)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fmt_brl(cents: int | None) -> str:
    if cents is None:
        return "indisponível"
    sign = "−" if cents < 0 else ""
    reais, cent = divmod(abs(cents), 100)
    grouped = f"{reais:,}".replace(",", ".")
    return f"{sign}R$ {grouped},{cent:02d}"


def fmt_pct(value: Decimal | None, signed: bool = True) -> str:
    if value is None:
        return "indisponível"
    text = f"{abs(value):.1f}".replace(".", ",")
    if not signed:
        return f"{text}%"
    if value > 0:
        return f"+{text}%"
    if value < 0:
        return f"−{text}%"
    return f"{text}%"
