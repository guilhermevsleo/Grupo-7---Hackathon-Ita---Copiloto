"""AuditService (briefing §23). Separado das ferramentas de dados e do LLM.

- Banco próprio (audit.db), só com inserções: gatilhos SQLite abortam UPDATE/DELETE.
- Cada evento guarda o hash do anterior (encadeamento). Isso DETECTA alteração, mas não prova
  autoria nem impede adulteração por quem controla todo o armazenamento.
- Não registra banco inteiro, segredos nem prompts completos.
- Tentativas negadas registram só colaborador, caso pedido e motivo.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .errors import AuditUnavailable

if TYPE_CHECKING:
    from .auth import ActiveCaseContext

TZ = ZoneInfo("America/Sao_Paulo")
GENESIS = "0" * 64

_COLUMNS = (
    "event_id", "event_type", "ts", "correlation_id", "employee_id", "session_id", "case_id",
    "customer_id", "data_snapshot_version", "feature_engine_version", "prompt_version",
    "model_version", "schema_version", "evidence_ids_used", "validation_result",
    "context_version_displayed", "human_decision", "human_notes", "details",
)

_DDL = f"""
CREATE TABLE IF NOT EXISTS audit_events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  {", ".join(f"{c} TEXT" for c in _COLUMNS)},
  prev_hash TEXT NOT NULL,
  row_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS displayed_contexts (
  context_version TEXT PRIMARY KEY,
  correlation_id TEXT NOT NULL,
  created_ts TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events e somente-insercao'); END;
CREATE TRIGGER IF NOT EXISTS audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events e somente-insercao'); END;
CREATE TRIGGER IF NOT EXISTS displayed_contexts_no_update BEFORE UPDATE ON displayed_contexts
BEGIN SELECT RAISE(ABORT, 'displayed_contexts e somente-insercao'); END;
CREATE TRIGGER IF NOT EXISTS displayed_contexts_no_delete BEFORE DELETE ON displayed_contexts
BEGIN SELECT RAISE(ABORT, 'displayed_contexts e somente-insercao'); END;
"""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    events: int
    first_broken_seq: int | None = None


class AuditService:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(_DDL)
        except (sqlite3.Error, OSError) as exc:
            raise AuditUnavailable(f"Trilha de auditoria indisponível: {exc}") from exc

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ escrita
    def _append(self, event_type: str, **fields: Any) -> str:
        record = {c: None for c in _COLUMNS}
        record.update({k: (v if v is None or isinstance(v, str) else _canonical(v)) for k, v in fields.items()})
        record["event_id"] = str(uuid.uuid4())
        record["event_type"] = event_type
        record["ts"] = datetime.now(TZ).isoformat(timespec="milliseconds")
        try:
            with self._lock, self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                last = conn.execute("SELECT row_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
                prev = last[0] if last else GENESIS
                row_hash = hashlib.sha256((prev + _canonical(record)).encode()).hexdigest()
                conn.execute(
                    f"INSERT INTO audit_events ({', '.join(_COLUMNS)}, prev_hash, row_hash) "
                    f"VALUES ({', '.join('?' for _ in _COLUMNS)}, ?, ?)",
                    [record[c] for c in _COLUMNS] + [prev, row_hash],
                )
                conn.execute("COMMIT")
        except sqlite3.Error as exc:
            raise AuditUnavailable(f"Falha ao gravar auditoria: {exc}") from exc
        return record["event_id"]

    def _ctx_fields(self, ctx: "ActiveCaseContext") -> dict[str, Any]:
        return dict(correlation_id=ctx.correlation_id, employee_id=ctx.employee_id,
                    session_id=ctx.session_id, case_id=ctx.case_id,
                    customer_id=ctx.active_customer_id)

    def record_access_denied(self, *, employee_id: str, session_id: str, requested_case_id: str,
                             reason: str) -> str:
        return self._append("ACCESS_DENIED", employee_id=employee_id, session_id=session_id,
                            case_id=requested_case_id, details={"reason": reason})

    def record_case_opened(self, ctx: "ActiveCaseContext") -> str:
        return self._append("CASE_OPENED", **self._ctx_fields(ctx))

    def record_case_closed(self, ctx: "ActiveCaseContext", reason: str) -> str:
        return self._append("CASE_CLOSED", **self._ctx_fields(ctx), details={"reason": reason})

    def record_context_displayed(self, ctx: "ActiveCaseContext", *, context_payload: dict,
                                 versions: dict[str, str], evidence_ids: list[str],
                                 validation: dict, metrics: dict | None = None) -> str:
        """Guarda a versão exata do contexto exibido (para reconstrução) e o resultado da validação."""
        payload = _canonical(context_payload)
        context_version = hashlib.sha256(payload.encode()).hexdigest()[:16]
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO displayed_contexts VALUES (?,?,?,?)",
                    (context_version, ctx.correlation_id, datetime.now(TZ).isoformat(), payload),
                )
        except sqlite3.Error as exc:
            raise AuditUnavailable(f"Falha ao gravar contexto exibido: {exc}") from exc
        self._append("CONTEXT_DISPLAYED", **self._ctx_fields(ctx),
                     data_snapshot_version=versions.get("data_snapshot_version"),
                     feature_engine_version=versions.get("feature_engine_version"),
                     prompt_version=versions.get("prompt_version"),
                     model_version=versions.get("model_version"),
                     schema_version=versions.get("schema_version"),
                     evidence_ids_used=evidence_ids, validation_result=validation,
                     context_version_displayed=context_version, details=metrics or {})
        return context_version

    def record_llm_failure(self, ctx: "ActiveCaseContext", *, model_version: str, reason: str) -> str:
        return self._append("LLM_FAILURE", **self._ctx_fields(ctx), model_version=model_version,
                            details={"reason": reason[:300]})

    def record_stale_response_discarded(self, *, stale_correlation_id: str, session_id: str,
                                        employee_id: str) -> str:
        return self._append("STALE_RESPONSE_DISCARDED", correlation_id=stale_correlation_id,
                            session_id=session_id, employee_id=employee_id)

    def record_human_decision(self, ctx: "ActiveCaseContext", *, context_version: str | None,
                              decision: str, notes: str) -> str:
        """Só retorna depois de persistir. Se falhar, levanta AuditUnavailable (a UI não confirma)."""
        ctx.require("decision:write")
        decision = (decision or "").strip()
        if not decision:
            raise ValueError("A decisão do colaborador não pode ser vazia.")
        return self._append("HUMAN_DECISION", **self._ctx_fields(ctx),
                            context_version_displayed=context_version,
                            human_decision=decision[:2000], human_notes=(notes or "").strip()[:4000])

    def record_ai_toggle(self, *, employee_id: str, session_id: str, enabled: bool) -> str:
        return self._append("AI_TOGGLED", employee_id=employee_id, session_id=session_id,
                            details={"ai_enabled": enabled})

    # ------------------------------------------------------------------ leitura (papel risco)
    def list_events(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM audit_events ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_displayed_context(self, context_version: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM displayed_contexts WHERE context_version = ?",
                               (context_version,)).fetchone()
        return json.loads(row[0]) if row else None

    def verify_chain(self) -> ChainCheck:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
        prev = GENESIS
        for r in rows:
            record = {c: r[c] for c in _COLUMNS}
            expected = hashlib.sha256((prev + _canonical(record)).encode()).hexdigest()
            if r["prev_hash"] != prev or r["row_hash"] != expected:
                return ChainCheck(False, len(rows), r["seq"])
            prev = r["row_hash"]
        return ChainCheck(True, len(rows))
