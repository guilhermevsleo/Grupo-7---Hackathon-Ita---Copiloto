"""Autorização por caso (briefing §3–§5). Nega por padrão.

Fluxo: colaborador (simulado) -> casos autorizados -> caso ativo -> cliente ativo -> dados.
O customer_id nunca vem do navegador nem do LLM: é resolvido no servidor a partir do case_id
autorizado e fica congelado no ActiveCaseContext.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import yaml

from .errors import AccessDenied

if TYPE_CHECKING:
    from .audit import AuditService
    from .directory import CaseDirectory

TZ = ZoneInfo("America/Sao_Paulo")
_CASE_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


@dataclass(frozen=True)
class Employee:
    employee_id: str
    display_name: str
    role: str
    permissions: frozenset[str]
    authorized_cases: frozenset[str]


class EntitlementStore:
    def __init__(self, employees: dict[str, Employee]):
        self._employees = employees

    @classmethod
    def from_yaml(cls, path: Path) -> "EntitlementStore":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        roles = {name: frozenset(spec.get("permissions", [])) for name, spec in raw["roles"].items()}
        employees = {}
        for emp_id, spec in raw["employees"].items():
            role = spec["role"]
            employees[emp_id] = Employee(
                employee_id=emp_id,
                display_name=spec.get("display_name", emp_id),
                role=role,
                permissions=roles.get(role, frozenset()),
                authorized_cases=frozenset(spec.get("authorized_cases") or []),
            )
        return cls(employees)

    def get(self, employee_id: str) -> Employee | None:
        return self._employees.get(employee_id)

    def all(self) -> list[Employee]:
        return list(self._employees.values())


@dataclass(frozen=True)
class ActiveCaseContext:
    """Contexto imutável do caso ativo. Criado somente por authorize_case()."""
    employee_id: str
    session_id: str
    case_id: str
    active_customer_id: str
    customer_ref: str
    role: str
    permissions: frozenset[str]
    opened_at: datetime
    correlation_id: str

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise AccessDenied(f"Permissão ausente: {permission}")


def authorize_case(*, employee_id: str, case_id: str, session_id: str,
                   entitlements: EntitlementStore, directory: "CaseDirectory",
                   audit: "AuditService") -> ActiveCaseContext:
    """Verifica o direito do colaborador ao caso e só então cria o contexto no servidor."""

    def deny(reason: str) -> AccessDenied:
        # Registro mínimo: quem pediu, qual caso e o motivo. Nenhum dado do cliente do caso negado.
        audit.record_access_denied(employee_id=employee_id, session_id=session_id,
                                   requested_case_id=str(case_id)[:64], reason=reason)
        return AccessDenied(f"Acesso negado ao caso solicitado ({reason}).")

    if not isinstance(case_id, str) or not _CASE_ID.match(case_id):
        raise deny("case_id_invalido")
    employee = entitlements.get(employee_id)
    if employee is None:
        raise deny("colaborador_desconhecido")
    if "case:open" not in employee.permissions:
        raise deny("papel_sem_permissao_de_abrir_caso")
    if case_id not in employee.authorized_cases:
        raise deny("caso_nao_autorizado_para_o_colaborador")
    customer_id = directory.resolve_customer(case_id)
    if customer_id is None:
        raise deny("caso_inexistente")

    ctx = ActiveCaseContext(
        employee_id=employee.employee_id,
        session_id=session_id,
        case_id=case_id,
        active_customer_id=customer_id,
        customer_ref=directory.pseudonym(customer_id),
        role=employee.role,
        permissions=employee.permissions,
        opened_at=datetime.now(TZ),
        correlation_id=str(uuid.uuid4()),
    )
    audit.record_case_opened(ctx)
    return ctx


def assert_same_customer(ctx: ActiveCaseContext, requested_customer_id: str) -> None:
    """Para qualquer função que tecnicamente receba customer_id: rejeita ANTES de executar SQL."""
    if requested_customer_id != ctx.active_customer_id:
        raise AccessDenied("Cliente solicitado diverge do cliente do caso ativo.")
