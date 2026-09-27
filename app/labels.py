"""Textos de interface: motivos de bloqueio do validador e tom visual dos sinais."""

VIOLATION_PT = {
    "SCHEMA_INVALID": "Resposta fora do formato combinado",
    "CUSTOMER_MISMATCH": "Cliente diferente do caso ativo",
    "UNKNOWN_EVIDENCE": "Cita evidência inexistente",
    "FOREIGN_EVIDENCE": "Cita evidência de outro cliente",
    "PLACEHOLDER_NOT_DECLARED": "Marcador de evidência não declarado na frase",
    "UNAVAILABLE_EVIDENCE": "Usa valor indisponível",
    "NUMBER_OUTSIDE_EVIDENCE": "Número que não corresponde à evidência citada",
    "VALUE_DIRECTION_INCONSISTENT": "Alta/queda contrária ao valor calculado",
    "AUTOMATED_DECISION": "Tenta decidir pelo colaborador",
    "OFFER": "Oferta, desconto ou condição de pagamento",
    "PRODUCT_RECOMMENDATION": "Recomendação de produto",
    "CHANNEL_RECOMMENDATION": "Recomendação de canal ou forma de contato",
    "SCHEDULE_RECOMMENDATION": "Recomendação de horário",
    "RANKING": "Priorização ou comparação entre clientes",
    "INTENT_OR_BLAME": "Intenção de pagar, culpa ou caráter",
    "SENSITIVE_INFERENCE": "Inferência sobre condição pessoal sensível",
    "DRAMATIZATION": "Linguagem dramatizada",
    "INJECTION_ECHO": "Repete instrução maliciosa dos dados",
    "UNSAFE_CONTENT": "Marcação, link ou código",
    "OTHER_CUSTOMER_REFERENCE": "Menciona outro cliente",
    "CAUSAL_WITHOUT_EVIDENCE": "Afirma causa no resumo",
    "HYPOTHESIS_NOT_CONDITIONAL": "Hipótese escrita como fato",
    "HYPOTHESIS_ON_MISSING_DATA": "Hipótese apoiada em dado ausente",
    "HYPOTHESIS_ON_INSUFFICIENT_DATA": "Hipótese sobre métrica sem dados suficientes",
    "NARRATIVE_ON_INSUFFICIENT_DATA": "Hipótese em caso com dados insuficientes",
    "QUESTION_FORMAT": "Pergunta fora do formato",
    "QUESTION_NOT_NEUTRAL": "Pergunta acusatória",
    "QUESTION_OFFER_OR_CONTACT_STRATEGY": "Pergunta que abre negociação ou define contato",
    "NarrationFailed": "Provedor de IA indisponível ou lento",
    "PayloadViolation": "Envio ao provedor bloqueado pela minimização",
}

# Tom visual do sinal dentro do caso (não é prioridade entre clientes). Sempre acompanha ícone + texto.
SIGNAL_TONE = {
    "INFLOW_REDUCTION": ("alert", "↓"),
    "INFLOW_REDUCTION_BEFORE_DELINQUENCY": ("alert", "⇢"),
    "OVERDUE_INSTALLMENTS": ("alert", "!"),
    "CARD_PAYMENTS_BELOW_FULL": ("warn", "!"),
    "HIGH_CARD_UTILIZATION": ("warn", "▲"),
    "PRIOR_AGREEMENT_BROKEN": ("warn", "×"),
    "EXPENSE_INCREASE": ("warn", "↑"),
    "EXPENSE_ISOLATED_PEAK": ("info", "◆"),
    "LIQUIDITY_FROM_INVESTMENT": ("info", "↺"),
    "SENSITIVE_CATEGORY_CHANGE": ("info", "•"),
    "VISIBILITY_LOSS": ("gap", "◌"),
}

AI_STATE = {
    "PENDING": ("IA redigindo…", "c-info"),
    "VALIDATED": ("IA validada", "c-ok"),
    "BLOCKED": ("IA bloqueada", "c-crit"),
    "FAILED": ("IA indisponível", "c-warn"),
    "DISABLED": ("Sem IA", "c-gray"),
}
