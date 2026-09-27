"""Repositório somente leitura com escopo do caso ativo (briefing §5–§7).

- Construído apenas a partir de um ActiveCaseContext.
- Nenhum método público recebe customer_id: o cliente vem do contexto.
- Toda consulta filtra pelo cliente ativo; tabelas filhas fazem JOIN conferindo o cliente
  nas duas pontas (a FK sozinha não garante que o filho e o pai são do mesmo cliente).
- Projeção explícita: só os campos do config/schema_map.yaml (nunca SELECT *).
- Não expõe SQL, conexão nem escrita.
"""
from __future__ import annotations

from typing import Any

from .auth import ActiveCaseContext
from .errors import AccessDenied
from .schema_map import ReadOnlyDatabase, TableSpec, convert

Row = dict[str, Any]


class ScopedRepository:
    def __init__(self, ctx: ActiveCaseContext, db: ReadOnlyDatabase):
        if not isinstance(ctx, ActiveCaseContext):
            raise AccessDenied("Repositório exige um contexto de caso autorizado.")
        self._ctx = ctx
        self._db = db
        self._schema = db.schema
        self._conn = db.connect()
        self._closed = False

    @property
    def correlation_id(self) -> str:
        return self._ctx.correlation_id

    def close(self) -> None:
        if not self._closed:
            self._conn.close()
            self._closed = True

    # ------------------------------------------------------------------ interno
    def _select(self, key: str, order_by: tuple[str, ...] = ()) -> list[Row]:
        if self._closed:
            raise AccessDenied("Contexto encerrado: abra o caso novamente.")
        spec: TableSpec = self._schema.tables[key]
        present = self._schema.present_columns(key)
        cols, fields = [], []
        for f in spec.fields:
            if f.column in present:
                cols.append(f't."{f.column}" AS "{f.logical}"')
                fields.append(f)
            elif f.required:
                raise AccessDenied(f"Coluna obrigatória ausente: {spec.table}.{f.column}")
        sql = f'SELECT {", ".join(cols)} FROM "{spec.table}" AS t'
        if spec.parent_table_key:
            parent = self._schema.tables[spec.parent_table_key]
            pkey = next(f for f in parent.fields if f.logical == spec.parent_key).column
            ckey = next(f for f in spec.fields if f.logical == spec.parent_key).column
            sql += (f' JOIN "{parent.table}" AS p ON p."{pkey}" = t."{ckey}"'
                    f' AND p."{parent.customer_column}" = t."{spec.customer_column}"')
        sql += f' WHERE t."{spec.customer_column}" = :active_customer_id'
        if order_by:
            logical_to_col = {f.logical: f.column for f in fields}
            sql += " ORDER BY " + ", ".join(f't."{logical_to_col[o]}"' for o in order_by if o in logical_to_col)
        cursor = self._conn.execute(sql, {"active_customer_id": self._ctx.active_customer_id})
        rows = []
        for raw in cursor.fetchall():
            row = {f.logical: convert(v, f.type) for f, v in zip(fields, raw)}
            for f in spec.fields:
                row.setdefault(f.logical, None)
            # Defesa em profundidade: nenhuma linha de outro cliente sai daqui.
            if row.get("customer_id") not in (None, self._ctx.active_customer_id):
                raise AccessDenied("Linha de outro cliente detectada; consulta abortada.")
            rows.append(row)
        return rows

    # ------------------------------------------------------------------ leituras
    def get_case(self) -> Row:
        rows = [r for r in self._select("agent_cases") if r["case_id"] == self._ctx.case_id]
        if not rows:
            raise AccessDenied("Caso ativo não encontrado para o cliente ativo.")
        return rows[0]

    def get_customer_profile(self) -> Row:
        """Projeção mínima: sem nome, CPF, demografia, cohort ou metadados do gerador."""
        rows = self._select("customers")
        return rows[0] if rows else {}

    def get_accounts(self) -> list[Row]:
        return self._select("accounts", ("account_id",))

    def get_transactions(self) -> list[Row]:
        return self._select("transactions", ("date", "transaction_id"))

    def get_credit_cards(self) -> list[Row]:
        return self._select("credit_cards", ("card_id",))

    def get_card_transactions(self) -> list[Row]:
        return self._select("card_transactions", ("date", "card_transaction_id"))

    def get_card_statements(self) -> list[Row]:
        return self._select("card_statements", ("reference_month", "statement_id"))

    def get_loans(self) -> list[Row]:
        return self._select("loans", ("contract_id",))

    def get_installments(self) -> list[Row]:
        return self._select("installments", ("due_date", "installment_id"))

    def get_consents(self) -> list[Row]:
        return self._select("consents", ("consent_id",))

    def get_contacts(self) -> list[Row]:
        return self._select("contacts", ("date", "contact_id"))

    def get_renegotiations(self) -> list[Row]:
        return self._select("renegotiations", ("proposal_date", "agreement_id"))

    def get_source_quality(self) -> list[Row]:
        return self._select("data_quality", ("source_name",))
