"""Mapa lógico -> físico das colunas e acesso somente leitura ao SQLite."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .errors import SchemaMismatch
from .money import to_cents

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class UntrustedText(str):
    """Texto livre vindo da base (notas, descrições). É DADO, nunca instrução.
    Nunca é enviado ao LLM e é sempre exibido como texto puro."""


@dataclass(frozen=True)
class FieldSpec:
    logical: str
    column: str
    type: str
    required: bool


@dataclass(frozen=True)
class TableSpec:
    key: str
    table: str
    customer_column: str
    fields: tuple[FieldSpec, ...]
    parent_table_key: str | None = None
    parent_key: str | None = None


class SchemaMap:
    def __init__(self, path: Path):
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.tables: dict[str, TableSpec] = {}
        for key, spec in raw["tables"].items():
            fields = tuple(
                FieldSpec(logical, f["column"], f.get("type", "str"), f.get("required", True))
                for logical, f in spec["fields"].items()
            )
            for name in [spec["table"], spec["customer_column"], *(f.column for f in fields)]:
                if not _IDENT.match(name):
                    raise SchemaMismatch(f"Identificador inválido no schema_map: {name!r}")
            parent = spec.get("parent") or {}
            self.tables[key] = TableSpec(key, spec["table"], spec["customer_column"], fields,
                                         parent.get("table_key"), parent.get("key"))
        self.vocab: dict[str, Any] = raw.get("vocab", {})
        self._present: dict[str, set[str]] = {}

    def values(self, concept: str) -> frozenset[str]:
        return frozenset(self.vocab.get(concept, []))

    def quality_source_for(self, raw_source_name: str) -> str | None:
        for logical, names in self.vocab.get("quality_sources", {}).items():
            if raw_source_name in names:
                return logical
        return None

    # ---------- verificação de schema ----------
    def verify(self, conn: sqlite3.Connection) -> list[str]:
        """Lista problemas (colunas obrigatórias ausentes). Colunas opcionais ausentes viram None."""
        problems: list[str] = []
        for spec in self.tables.values():
            cols = {row[1] for row in conn.execute(f'PRAGMA table_info("{spec.table}")')}
            if not cols:
                problems.append(f"tabela ausente: {spec.table}")
                continue
            self._present[spec.key] = cols
            if spec.customer_column not in cols:
                problems.append(f"{spec.table}.{spec.customer_column} (coluna de cliente) ausente")
            for f in spec.fields:
                if f.column not in cols and f.required:
                    problems.append(f"{spec.table}.{f.column} ausente (campo lógico {f.logical})")
        return problems

    def present_columns(self, key: str) -> set[str]:
        return self._present.get(key, set())


def convert(value: Any, type_: str) -> Any:
    if type_ == "money":
        return to_cents(value)
    if type_ == "date":
        if value is None or (isinstance(value, str) and not value.strip()):
            return None  # sentinela vazia ("") tratada como ausência, nunca como data
        return date.fromisoformat(str(value)[:10])
    if type_ == "int":
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return int(value)
    if type_ == "flag":
        return bool(int(value)) if value not in (None, "") else False
    if type_ == "untrusted_text":
        return UntrustedText(value) if value not in (None, "") else None
    return None if value is None else str(value)


class ReadOnlyDatabase:
    """Abre o SQLite em modo somente leitura (mode=ro + query_only). Não filtra clientes:
    o filtro é responsabilidade do ScopedRepository."""

    def __init__(self, path: Path, schema: SchemaMap):
        if not Path(path).exists():
            raise FileNotFoundError(f"Base não encontrada: {path}")
        self.path = Path(path)
        self.schema = schema
        self._check_conn = self.connect()
        problems = schema.verify(self._check_conn)
        if problems:
            raise SchemaMismatch("Schema incompatível com config/schema_map.yaml:\n- " + "\n- ".join(problems))

    def connect(self) -> sqlite3.Connection:
        uri = self.path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("PRAGMA query_only = ON")
        return conn
