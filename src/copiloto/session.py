"""Sessão do colaborador: um caso ativo por vez e isolamento entre clientes (briefing §6).

Trocar de caso:
 1. valida a autorização do novo caso (se negar, nada muda);
 2. invalida o contexto anterior e fecha o repositório dele;
 3-5. descarta memória do agente, cache e pacote de evidências (estado por caso);
 6. respostas assíncronas do caso anterior são descartadas (correlation_id diferente);
 7. o novo contexto nasce com um correlation_id novo.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .audit import AuditService
from .auth import ActiveCaseContext, EntitlementStore, authorize_case
from .directory import CaseDirectory, CaseSummary
from .errors import AccessDenied
from .repository import ScopedRepository
from .schema_map import ReadOnlyDatabase


class CaseSession:
    def __init__(self, *, employee_id: str, entitlements: EntitlementStore, directory: CaseDirectory,
                 db: ReadOnlyDatabase, audit: AuditService):
        employee = entitlements.get(employee_id)
        if employee is None:
            raise AccessDenied("Colaborador desconhecido.")
        self.employee = employee
        self.session_id = str(uuid.uuid4())
        self._entitlements = entitlements
        self._directory = directory
        self._db = db
        self._audit = audit
        self._lock = threading.RLock()
        self._ctx: ActiveCaseContext | None = None
        self._repo: ScopedRepository | None = None
        self._state: dict[str, Any] = {}

    # ------------------------------------------------------------------ casos
    def authorized_cases(self) -> list[CaseSummary]:
        return self._directory.list_authorized_cases(self.employee)

    @property
    def context(self) -> ActiveCaseContext | None:
        return self._ctx

    def open_case(self, case_id: str) -> ActiveCaseContext:
        with self._lock:
            new_ctx = authorize_case(employee_id=self.employee.employee_id, case_id=case_id,
                                     session_id=self.session_id, entitlements=self._entitlements,
                                     directory=self._directory, audit=self._audit)
            self._close_current(reason="troca_de_caso")
            self._ctx = new_ctx
            self._repo = ScopedRepository(new_ctx, self._db)
            self._state = {}
            return new_ctx

    def close_case(self) -> None:
        with self._lock:
            self._close_current(reason="encerrado_pelo_colaborador")

    def _close_current(self, reason: str) -> None:
        if self._repo is not None:
            self._repo.close()
        if self._ctx is not None:
            self._audit.record_case_closed(self._ctx, reason)
        self._ctx, self._repo, self._state = None, None, {}

    # ------------------------------------------------------------------ acesso ao caso ativo
    def repository(self) -> ScopedRepository:
        if self._repo is None or self._ctx is None:
            raise AccessDenied("Nenhum caso ativo nesta sessão.")
        return self._repo

    def require_context(self) -> ActiveCaseContext:
        if self._ctx is None:
            raise AccessDenied("Nenhum caso ativo nesta sessão.")
        return self._ctx

    def is_current(self, correlation_id: str) -> bool:
        return self._ctx is not None and self._ctx.correlation_id == correlation_id

    # Estado por caso (evidências, narrativa, cache). Sempre amarrado ao correlation_id.
    def put(self, correlation_id: str, key: str, value: Any) -> bool:
        with self._lock:
            if not self.is_current(correlation_id):
                self._audit.record_stale_response_discarded(
                    stale_correlation_id=correlation_id, session_id=self.session_id,
                    employee_id=self.employee.employee_id)
                return False
            self._state[key] = value
            return True

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)
