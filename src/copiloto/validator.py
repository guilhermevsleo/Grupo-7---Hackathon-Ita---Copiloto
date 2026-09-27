"""validate_agent_output (briefing §22). Reprova a saída INTEIRA do LLM diante de qualquer violação.

Camadas:
1. Contrato: JSON no schema AgentOutput (campos extras proibidos: decisão, oferta, canal...).
2. Cliente: case_ref igual ao do caso ativo; nenhuma referência a outro cliente.
3. Evidências: todo marcador {Exx-XXXX} existe no pacote do cliente ativo; evidência de outro
   cliente é identificada como tal; hipóteses não se apoiam em métricas INSUFFICIENT.
4. Números: o texto do modelo não pode conter dígitos nem valores por extenso — números entram
   apenas pelos marcadores, preenchidos pelo código. Direção (alta/queda) precisa bater com o valor.
5. Conteúdo proibido: decisão, oferta, produto, canal, horário, priorização, intenção/culpa,
   inferência sensível, dramatização, narrativa causal no resumo, eco de instruções injetadas.

Limite honesto (AI-05): listas de termos são rede de segurança, não garantia semântica. Por isso o
resumo é curto, os fatos são determinísticos e toda frase exige evidência.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from .auth import ActiveCaseContext
from .evidence import REGISTRY, EvidenceBundle
from .schemas import AgentOutput, Hypothesis, NarrativeSentence

PLACEHOLDER = re.compile(r"\{(E\d{2}-[0-9A-F]{4})\}")
ANY_BRACES = re.compile(r"\{[^{}]*\}")

FORBIDDEN_KEYS = {"decision", "decisao", "decisão", "offer", "oferta", "recommendation", "recomendacao",
                  "priority", "prioridade", "score", "channel", "canal", "action", "acao", "next_action"}


def normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _rx(*patterns: str) -> list[re.Pattern]:
    return [re.compile(p) for p in patterns]


PROHIBITED: dict[str, list[re.Pattern]] = {
    "AUTOMATED_DECISION": _rx(r"\baprov\w*", r"\bnega(r|do|da)\b", r"\bdecid\w*", r"\ba decisao (e|foi|sera)\b",
                              r"\bdeve(ria)? ser cobrad\w*", r"\bcobrar o cliente\b", r"\bnegativ\w*", r"\bprotest\w*",
                              r"\bencaminh\w* (para|ao) (juridico|cobranca)"),
    "OFFER": _rx(r"\boferta\w*", r"\bofere\w*", r"\bdesconto\w*", r"\babatimento\w*", r"\bcondic\w* especia\w*",
                 r"\b(propor|sugerir|oferecer) (um |uma )?(acordo|renegociacao|parcelamento)",
                 r"\bparcela\w* (ideal|recomendad\w*|sugerid\w*|de ate)\b", r"\bparcelar em\b", r"\bquitar com\b",
                 r"\bvalor de entrada\b", r"\bcondic\w* de pagamento\b",
                 r"\bajust\w* (o |a |os |as )?(vencimento|data|prazo|parcela|pagamento|condic)\w*",
                 r"\b(nova|novo|outra|outro) (data|vencimento|prazo)\b", r"\bprorrog\w*"),
    "PRODUCT_RECOMMENDATION": _rx(r"\brecomend\w*", r"\bcontrat(ar|acao)\b", r"\bnovo (emprestimo|cartao|credito)\b",
                                  r"\bportabilidade\b", r"\brefinanci\w*", r"\bproduto\w*"),
    "CHANNEL_RECOMMENDATION": _rx(r"\b(ligar|telefonar|contatar|acionar|abordar)\b", r"\babordagem\b",
                                  r"\bentrar em contato\b", r"\benviar (uma )?(mensagem|sms|e-?mail|whatsapp)\b",
                                  r"\b(melhor|ideal|preferencial|recomendad\w*) canal\b",
                                  r"\bcanal (ideal|preferencial|recomendado|mais eficiente)\b",
                                  r"\b(via|por|pelo) (whatsapp|sms|aplicativo)\b.*\b(deve|deveria|convem|ideal)\b"),
    "SCHEDULE_RECOMMENDATION": _rx(r"\bhorario\w*", r"\bmelhor (momento|dia|periodo) para\b",
                                   r"\b(pela|de) manha\b", r"\b(a|de) noite\b", r"\bfim de semana\b"),
    "RANKING": _rx(r"\bprioriz\w*", r"\bprioridade\b", r"\branking\b", r"\branque\w*", r"\bfila\b", r"\burgen\w*",
                   r"\bpropens\w*", r"\bprobabilidade\b", r"\bchance(s)? de\b", r"\bscore\b", r"\bpontuacao\b",
                   r"\boutros? clientes?\b"),
    "INTENT_OR_BLAME": _rx(r"\bintencao de\b", r"\bnao quer pagar\b", r"\bvai pagar\b", r"\bnao vai pagar\b",
                           r"\bmau pagador\b", r"\bbom pagador\b", r"\bcaloteir\w*", r"\birredutivel\b",
                           r"\bresistente\b", r"\bma-?fe\b", r"\bculpa\w*", r"\birresponsav\w*", r"\bdescuido\b",
                           r"\bnegligen\w*", r"\bcarater\b", r"\bpreguic\w*", r"\bdesorganizad\w*",
                           r"\bdisposic\w* (a|de|para) pagar\b"),
    "SENSITIVE_INFERENCE": _rx(r"\bdesempreg\w*", r"\bdemiti\w*", r"\bdemissao\b", r"\bperd\w* (o|do|de) emprego\b",
                               r"\bsem emprego\b", r"\bdoen\w*", r"\benferm\w*", r"\bdiagnost\w*",
                               r"\btratamento\w*", r"\binternac\w*", r"\bhospital\w*", r"\bremedio\w*",
                               r"\bmedicament\w*", r"\bvici\w*", r"\bdependencia\b", r"\balcool\w*", r"\bdroga\w*",
                               r"\baposta\w*", r"\bjogo\w*", r"\breligi\w*", r"\bigreja\b", r"\bpolitic\w*",
                               r"\borientacao sexual\b", r"\bdivorci\w*", r"\bseparac\w*", r"\bgravid\w*",
                               r"\bgestante\b", r"\bfilho\w*", r"\bfamilia\w*", r"\bluto\b", r"\bfalec\w*",
                               r"\bmorte\b", r"\bobito\b", r"\bpobre\w*", r"\bmiseria\b", r"\bvulnerab\w*",
                               r"\bbaixa renda\b", r"\bsuperendivid\w*"),
    "DRAMATIZATION": _rx(r"\bcrise\b", r"\bcolapso\b", r"\balarmante\b", r"\bdescontrol\w*", r"\bfalid\w*",
                         r"\bfalencia\b", r"\bgravissim\w*", r"\bdesesper\w*"),
    "INJECTION_ECHO": _rx(r"\bignor\w* (as |todas as )?(regras|instrucoes)", r"\bregras anteriores\b",
                          r"\binstrucoes anteriores\b", r"\bprompt\b", r"\bsystem\b"),
}
CAUSAL = _rx(r"\bporque\b", r"\bdevido\b", r"\bpor causa\b", r"\bem razao\b", r"\bcaus\w*", r"\blevou a\b",
             r"\bresult\w* (em|de|na|no)\b", r"\bmotiv\w*", r"\bexplica\w*", r"\bem consequencia\b",
             r"\bconsequentemente\b", r"\bpor isso\b", r"\bgracas a\b")
HEDGE = re.compile(r"\b(pode|podem|poderia|poderiam|possivel|possivelmente|talvez|hipotese)\b")
NUMBER_WORDS = re.compile(r"\b(por cento|reais|mil|milhao|milhoes|metade|dobro|triplo|quadruplo)\b")
UP = re.compile(r"\b(aument\w*|cresc\w*|subiu|subiram|elev\w*|alta)\b")
DOWN = re.compile(r"\b(cai|caiu|cairam|caem|queda\w*|reduz\w*|reduc\w*|diminu\w*|recuo|recuou|recuaram|retra\w*)\b")
UNSAFE = re.compile(r"[<>]|https?:|javascript:|\]\(")
# Perguntas não podem abrir negociação nem definir estratégia de contato (teste real com Gemini, 26/09).
QUESTION_OFFER_OR_CONTACT = _rx(
    # abrir negociação nova (mencionar o histórico de acordos é permitido)
    r"\b(nova|novo|outra|outro) (renegociacao|acordo|proposta|negociacao|parcelamento)\b",
    r"\b(fazer|fechar|firmar|propor|oferecer|aceitar) (um |uma )?(novo |nova )?(acordo|renegociacao|proposta|negociacao|parcelamento)\b",
    r"\binteresse em\b", r"\bgostaria de (renegociar|negociar|parcelar|quitar)\b",
    r"\bpodemos (renegociar|negociar|parcelar|oferecer|propor|ajustar)\b", r"\bcomo podemos ajudar\b",
    # estratégia de contato
    r"\bcanal\b", r"\bcanais\b", r"\bmeio de (contato|comunicacao)\b",
    r"\bmelhor (forma|maneira|jeito) de (contato|falar|entrar|receber)\b",
    r"\bpreferencia de (contato|comunicacao)\b")
# Hipótese não pode se apoiar no que NÃO foi observado (ausência de dado não vira explicação).
HYPOTHESIS_ON_MISSING = _rx(r"\bnao (sao |estao |foram )?(visiveis|observad\w*|registrad\w*)\b",
                            r"\bausencia de (dados|informac\w*|registro\w*)\b", r"\bsem visibilidade\b",
                            r"\bdados (nao )?atualizados\b", r"\bnao aparec\w*", r"\binvisive\w*")
QUESTION_ACCUSATORY = _rx(r"\bpor que (voce |o senhor |a senhora )?nao\b", r"\bnao pagou\b", r"\bdeixou de pagar\b",
                          r"\bpor que atras\w*")
OTHER_REF = re.compile(r"\bc-[0-9a-f]{4}\b")


@dataclass
class Violation:
    code: str
    where: str
    detail: str = ""


@dataclass
class ValidationResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    summary: list[NarrativeSentence] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    evidence_ids_used: list[str] = field(default_factory=list)

    def as_audit(self) -> dict[str, Any]:
        # Só o termo que disparou a regra (até 80 caracteres), nunca a resposta inteira rejeitada.
        return {"ok": self.ok, "violations": [{"code": v.code, "where": v.where, "trecho": v.detail[:80]}
                                              for v in self.violations]}


def _scan(text: str, where: str, categories: list[str], out: list[Violation]) -> None:
    norm = normalize(text)
    for cat in categories:
        for rx in PROHIBITED[cat]:
            m = rx.search(norm)
            if m:
                out.append(Violation(cat, where, m.group(0)))
                break


def _check_sentence(text: str, eids: list[str], where: str, bundle: EvidenceBundle, ctx: ActiveCaseContext,
                    out: list[Violation], used: list[str], *, hypothesis: bool) -> None:
    placeholders = PLACEHOLDER.findall(text)
    stripped = PLACEHOLDER.sub(" ", text)
    if ANY_BRACES.search(stripped):
        out.append(Violation("UNKNOWN_EVIDENCE", where, "marcador fora do formato"))
    for eid in set(placeholders) | set(eids):
        if eid in bundle.evidence:
            used.append(eid)
            ev = bundle.evidence[eid]
            if ev.customer_id != ctx.active_customer_id:
                out.append(Violation("FOREIGN_EVIDENCE", where, eid))
            if ev.value is None and eid in placeholders:
                out.append(Violation("UNAVAILABLE_EVIDENCE", where, eid))
            if hypothesis and ev.quality_status == "INSUFFICIENT":
                out.append(Violation("HYPOTHESIS_ON_INSUFFICIENT_DATA", where, eid))
        else:
            owner = REGISTRY.owner(eid)
            code = "FOREIGN_EVIDENCE" if owner and owner != ctx.active_customer_id else "UNKNOWN_EVIDENCE"
            out.append(Violation(code, where, eid))
    for eid in placeholders:
        if eid not in eids:
            out.append(Violation("PLACEHOLDER_NOT_DECLARED", where, eid))

    norm = normalize(stripped)
    # Números escritos diretamente só passam se forem idênticos a um valor das evidências citadas
    # nesta frase (D-08). Qualquer outro número — inventado, arredondado ou adulterado — reprova.
    allowed = _allowed_numbers([bundle.evidence[e] for e in set(eids) if e in bundle.evidence])
    for token in NUMBER_TOKEN.findall(stripped):
        clean = token.strip(".,")
        if clean not in allowed:
            out.append(Violation("NUMBER_OUTSIDE_EVIDENCE", where, f"'{clean}' não corresponde à evidência citada"))
            break
        for ev in allowed[clean]:
            placeholders.append(ev.evidence_id)  # checagem de direção também vale para números escritos
    if NUMBER_WORDS.search(norm):
        out.append(Violation("NUMBER_OUTSIDE_EVIDENCE", where, "valor escrito por extenso"))
    if UNSAFE.search(stripped):
        out.append(Violation("UNSAFE_CONTENT", where, "marcação ou link"))
    for ref in OTHER_REF.findall(norm):
        if ref != normalize(ctx.customer_ref):
            out.append(Violation("OTHER_CUSTOMER_REFERENCE", where, ref))
    _scan(stripped, where, list(PROHIBITED), out)

    # Direção do texto x sinal do valor (ex.: "aumentaram {E03}" quando E03 = −37,7%)
    for eid in placeholders:
        ev = bundle.evidence.get(eid)
        if ev and ev.unit == "pct" and "change" in ev.metric and isinstance(ev.value, Decimal) and ev.value != 0:
            up, down = bool(UP.search(norm)), bool(DOWN.search(norm))
            if (ev.value < 0 and up and not down) or (ev.value > 0 and down and not up):
                out.append(Violation("VALUE_DIRECTION_INCONSISTENT", where, eid))

    causal = next((rx.search(norm).group(0) for rx in CAUSAL if rx.search(norm)), None)
    if hypothesis:
        if not HEDGE.search(norm):
            out.append(Violation("HYPOTHESIS_NOT_CONDITIONAL", where, "hipótese sem marcador condicional"))
        missing = next((rx.search(norm).group(0) for rx in HYPOTHESIS_ON_MISSING if rx.search(norm)), None)
        if missing:
            out.append(Violation("HYPOTHESIS_ON_MISSING_DATA", where, missing))
    elif causal:
        out.append(Violation("CAUSAL_WITHOUT_EVIDENCE", where, causal))


NUMBER_TOKEN = re.compile(r"\d{1,2}/\d{1,2}/\d{4}|\d[\d.,]*")
REFERENCE_TOKENS = {"01/09/2026", "2026"}  # data de referência do retrato sintético


def _allowed_numbers(evidences) -> dict[str, list]:
    """Tokens numéricos presentes no valor, nas datas, na fórmula e nas limitações das evidências citadas
    (todos gerados pelo nosso código). Qualquer outro número no texto do modelo reprova a saída."""
    allowed: dict[str, list] = {t: [] for t in REFERENCE_TOKENS}

    def add(token: str, ev) -> None:
        token = token.strip(".,")
        if token:
            allowed.setdefault(token, []).append(ev)

    for ev in evidences:
        for token in NUMBER_TOKEN.findall(ev.value_display or ""):
            add(token, ev)
        for text in [ev.formula, *ev.limitations]:
            for token in NUMBER_TOKEN.findall(text or ""):
                allowed.setdefault(token.strip(".,"), [])  # aceito, sem checagem de direção
        if hasattr(ev.value, "year"):  # evidência cujo valor é uma data
            for token in (str(ev.value.day), f"{ev.value.day:02d}", str(ev.value.month),
                          f"{ev.value.month:02d}", str(ev.value.year), ev.value.strftime("%d/%m/%Y")):
                add(token, ev)
        for d in (ev.period_start, ev.period_end):  # período: só o ano
            if d is not None:
                add(str(d.year), ev)
    return allowed


def render(text: str, bundle: EvidenceBundle) -> str:
    return PLACEHOLDER.sub(lambda m: bundle.evidence[m.group(1)].value_display, text)


def validate_agent_output(raw: str | dict, bundle: EvidenceBundle, ctx: ActiveCaseContext) -> ValidationResult:
    out: list[Violation] = []
    if bundle.customer_id != ctx.active_customer_id or bundle.ctx.correlation_id != ctx.correlation_id:
        return ValidationResult(False, [Violation("CUSTOMER_MISMATCH", "bundle", "pacote de outro caso")])

    # 1. contrato
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as exc:
        return ValidationResult(False, [Violation("SCHEMA_INVALID", "json", str(exc)[:120])])
    if not isinstance(data, dict):
        return ValidationResult(False, [Violation("SCHEMA_INVALID", "json", "objeto esperado")])
    bad_keys = {k for k in data if normalize(str(k)) in {normalize(x) for x in FORBIDDEN_KEYS}}
    if bad_keys:
        out.append(Violation("AUTOMATED_DECISION", "json", ", ".join(sorted(bad_keys))))
    try:
        parsed = AgentOutput.model_validate(data)
    except ValidationError as exc:
        out.append(Violation("SCHEMA_INVALID", "json", str(exc.errors()[0].get("msg", ""))[:160]))
        return ValidationResult(False, out)

    # 2. cliente
    if parsed.case_ref != ctx.customer_ref:
        out.append(Violation("CUSTOMER_MISMATCH", "case_ref", parsed.case_ref[:20]))

    # Marcadores abreviados ({E08} em vez de {E08-03B4}) são resolvidos SOMENTE dentro do pacote do cliente
    # ativo, quando o prefixo é único. Um id completo de outro cliente continua caindo em FOREIGN_EVIDENCE.
    short = {}
    for eid in bundle.evidence:
        short.setdefault(eid.split("-")[0], []).append(eid)
    resolve = {k: v[0] for k, v in short.items() if len(v) == 1}

    def expand(sentence):
        text = re.sub(r"\{(E\d{2})\}", lambda m: "{" + resolve.get(m.group(1), m.group(1)) + "}", sentence.text)
        ids = [resolve.get(i, i) if re.fullmatch(r"E\d{2}", i) else i for i in sentence.evidence_ids]
        return sentence.model_copy(update={"text": text, "evidence_ids": ids})

    parsed = parsed.model_copy(update={"executive_summary": [expand(s) for s in parsed.executive_summary],
                                       "hypotheses": [expand(h) for h in parsed.hypotheses]})

    # 3-5. frases
    used: list[str] = []
    for i, s in enumerate(parsed.executive_summary):
        _check_sentence(s.text, s.evidence_ids, f"resumo[{i}]", bundle, ctx, out, used, hypothesis=False)
    if bundle.data_quality.overall == "INSUFFICIENT_DATA" and parsed.hypotheses:
        out.append(Violation("NARRATIVE_ON_INSUFFICIENT_DATA", "hipoteses", "caso sem dados suficientes"))
    for i, h in enumerate(parsed.hypotheses):
        _check_sentence(h.text, h.evidence_ids, f"hipotese[{i}]", bundle, ctx, out, used, hypothesis=True)
    for i, q in enumerate(parsed.suggested_questions):
        where = f"pergunta[{i}]"
        norm = normalize(q)
        if not q.strip().endswith("?") or len(q) > 220 or PLACEHOLDER.search(q):
            out.append(Violation("QUESTION_FORMAT", where, "pergunta deve ser curta, terminar com ? e não ter marcadores"))
        if re.search(r"\d", q) or NUMBER_WORDS.search(norm):
            out.append(Violation("NUMBER_OUTSIDE_EVIDENCE", where, "número em pergunta"))
        if UNSAFE.search(q):
            out.append(Violation("UNSAFE_CONTENT", where, "marcação ou link"))
        _scan(q, where, [c for c in PROHIBITED], out)
        for rx in QUESTION_ACCUSATORY:
            if rx.search(norm):
                out.append(Violation("QUESTION_NOT_NEUTRAL", where, rx.pattern))
                break
        for rx in QUESTION_OFFER_OR_CONTACT:
            m = rx.search(norm)
            if m:
                out.append(Violation("QUESTION_OFFER_OR_CONTACT_STRATEGY", where, m.group(0)))
                break

    if out:
        return ValidationResult(False, out, evidence_ids_used=sorted(set(used)))
    return ValidationResult(
        True, [],
        summary=[NarrativeSentence(text=render(s.text, bundle), evidence_ids=s.evidence_ids)
                 for s in parsed.executive_summary],
        hypotheses=[Hypothesis(text=render(h.text, bundle), evidence_ids=h.evidence_ids) for h in parsed.hypotheses],
        questions=[q.strip() for q in parsed.suggested_questions],
        evidence_ids_used=sorted(set(used)))
