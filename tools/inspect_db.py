"""Inspeção técnica da base (uso da equipe, não do agente): compara o schema com
config/schema_map.yaml e lista valores de vocabulário e casos, para configurar a base oficial.

Somente leitura (mode=ro). Não abre nem lê nada de evaluator_only/.
Uso:  python tools/inspect_db.py [caminho/para/synthetic_banking.db]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copiloto.schema_map import SchemaMap  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data" / "synthetic_banking.db").resolve()
    if "evaluator_only" in path.parts:
        sys.exit("Recusado: evaluator_only/ não deve ser lido pela equipe de implementação.")
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    schema = SchemaMap(ROOT / "config" / "schema_map.yaml")
    problems = schema.verify(conn)
    print(f"Base: {path}\n")
    print("Problemas de schema:" if problems else "Schema compatível com config/schema_map.yaml.")
    for p in problems:
        print("  -", p)
        table = p.split(".")[0].replace("tabela ausente: ", "")
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        if cols:
            print(f"    colunas existentes em {table}: {', '.join(cols)}")
    print("\nValores observados (para ajustar a seção vocab do schema_map):")
    for table, column in [("transactions", "direction"), ("transactions", "transaction_type"),
                          ("transactions", "category"), ("transactions", "counterparty_type"),
                          ("accounts", "source"), ("card_transactions", "category"), ("card_transactions", "status"),
                          ("consents", "status"), ("contacts", "channel"), ("contacts", "outcome"),
                          ("renegotiations", "status"), ("data_quality", "source_name"), ("data_quality", "status")]:
        try:
            values = [r[0] for r in conn.execute(f'SELECT DISTINCT "{column}" FROM "{table}" ORDER BY 1')]
            print(f"  {table}.{column}: {values}")
        except sqlite3.Error as exc:
            print(f"  {table}.{column}: indisponível ({exc})")
    try:
        cases = [r[0] for r in conn.execute("SELECT case_id FROM agent_cases ORDER BY 1 LIMIT 10")]
        print(f"\nPrimeiros case_id (para config/entitlements.yaml): {cases}")
    except sqlite3.Error:
        pass
    conn.close()


if __name__ == "__main__":
    main()
