"""Roda o agente REAL (Google ADK + Gemini) sobre os casos autorizados e mede validação e latência.

Consome cota da API Gemini: rode só quando quiser medir o modelo de verdade.
Requer GOOGLE_API_KEY no .env. Resultados vão para a trilha de auditoria e para a tela.

Uso:  python tools/live_eval.py [EMP-001] [repetições]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copiloto.agent.narrator import AdkGeminiNarrator  # noqa: E402
from copiloto.bootstrap import build_app  # noqa: E402
from copiloto.pipeline import ContextService  # noqa: E402


def main() -> None:
    employee = sys.argv[1] if len(sys.argv) > 1 else "EMP-001"
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    app = build_app()
    if not app.settings.google_api_key_present:
        sys.exit("GOOGLE_API_KEY ausente no .env — nada foi executado.")
    service = ContextService(app, AdkGeminiNarrator(app.settings.gemini_model, app.settings.gemini_thinking,
                                                    app.settings.gemini_fallback_models))
    session = app.new_session(employee)
    statuses, codes, latencies = Counter(), Counter(), []
    for case in session.authorized_cases():
        for _ in range(reps):
            session.open_case(case.case_id)
            run = service.build(session, ai_enabled=True)
            status = run.context.narrative_status
            statuses[status] += 1
            latencies.append(run.metrics["llm_ms"])
            for v in run.validation.get("violations", []):
                codes[v["code"]] += 1
            print(f"{case.case_id} {case.customer_ref}: {status} "
                  f"{[v['code'] for v in run.validation.get('violations', [])]} llm={run.metrics['llm_ms']} ms")
    total = sum(statuses.values())
    print(f"\nModelo: {app.settings.gemini_model} · execuções: {total}")
    print(f"Validadas: {statuses['VALIDATED']} · bloqueadas: {statuses['BLOCKED']} · falhas: {statuses['FAILED']}")
    print(f"Taxa de bloqueio (validation failure rate): {statuses['BLOCKED'] / total:.0%}")
    print(f"Latência do LLM (mediana): {median(latencies)} ms")
    print(f"Violações mais frequentes: {codes.most_common(5)}")


if __name__ == "__main__":
    main()
