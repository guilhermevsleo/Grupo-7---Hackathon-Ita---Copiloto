"""Diretório de casos: resolve case_id -> cliente no servidor e lista SÓ os casos autorizados.

Não há busca por nome, CPF, customer_id, conta, telefone ou e-mail (briefing §3)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .auth import Employee
from .pseudonym import Pseudonymizer
from .schema_map import ReadOnlyDatabase, convert


@dataclass(frozen=True)
class CaseSummary:
    case_id: str
    customer_ref: str
    opened_at: date | None


class CaseDirectory:
    def __init__(self, db: ReadOnlyDatabase, pseudonymizer: Pseudonymizer):
        self._db = db
        self._pseudo = pseudonymizer
        spec = db.schema.tables["agent_cases"]
        self._cols = {f.logical: f for f in spec.fields}
        self._table = spec.table

    def pseudonym(self, customer_id: str) -> str:
        return self._pseudo.ref(customer_id)

    def resolve_customer(self, case_id: str) -> str | None:
        c = self._cols
        conn = self._db.connect()
        try:
            row = conn.execute(
                f'SELECT "{c["customer_id"].column}" FROM "{self._table}" '
                f'WHERE "{c["case_id"].column}" = :case_id',
                {"case_id": case_id},
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None

    def list_authorized_cases(self, employee: Employee) -> list[CaseSummary]:
        """Somente casos presentes nos direitos do colaborador. Nega por padrão."""
        if "case:open" not in employee.permissions or not employee.authorized_cases:
            return []
        c = self._cols
        ids = sorted(employee.authorized_cases)
        placeholders = ",".join(f":c{i}" for i in range(len(ids)))
        conn = self._db.connect()
        try:
            rows = conn.execute(
                f'SELECT "{c["case_id"].column}", "{c["customer_id"].column}", "{c["opened_at"].column}" '
                f'FROM "{self._table}" WHERE "{c["case_id"].column}" IN ({placeholders}) '
                f'ORDER BY "{c["case_id"].column}"',
                {f"c{i}": v for i, v in enumerate(ids)},
            ).fetchall()
        finally:
            conn.close()
        return [CaseSummary(r[0], self._pseudo.ref(r[1]), convert(r[2], "date")) for r in rows]
