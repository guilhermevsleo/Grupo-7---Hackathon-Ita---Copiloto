"""P0 — autorização, repositório com escopo, isolamento e auditoria.

Cobre os evals 08 (cliente B em sessão A), 09 (customer_id arbitrário), 11 (sessões simultâneas)
e o roteiro A -> B -> A do briefing §6.
"""
from __future__ import annotations

import inspect
import sqlite3
import threading

import pytest

from copiloto.auth import assert_same_customer
from copiloto.errors import AccessDenied, SchemaMismatch
from copiloto.repository import ScopedRepository
from copiloto.schema_map import ReadOnlyDatabase

READ_METHODS = [name for name, _ in inspect.getmembers(ScopedRepository, inspect.isfunction)
                if name.startswith("get_")]


def _events(app, event_type):
    return [e for e in app.audit.list_events() if e["event_type"] == event_type]


# ------------------------------------------------------------------ autorização
def test_lista_somente_casos_autorizados(session_a, session_b):
    assert [c.case_id for c in session_a.authorized_cases()] == [
        "CASE_0001", "CASE_0002", "CASE_0003", "CASE_0004", "CASE_0005", "CASE_0006", "CASE_0007"]
    assert [c.case_id for c in session_b.authorized_cases()] == ["CASE_0003", "CASE_0008"]
    for summary in session_a.authorized_cases():
        assert summary.customer_ref.startswith("C-") and "CUST" not in summary.customer_ref


def test_papel_de_risco_nao_abre_caso(app):
    risco = app.new_session("EMP-900")
    assert risco.authorized_cases() == []
    with pytest.raises(AccessDenied):
        risco.open_case("CASE_0001")


def test_abre_caso_autorizado_e_cria_contexto_no_servidor(session_a):
    ctx = session_a.open_case("CASE_0001")
    assert ctx.active_customer_id == "CUST_0001"
    assert ctx.employee_id == "EMP-001" and ctx.session_id == session_a.session_id
    with pytest.raises(Exception):
        ctx.active_customer_id = "CUST_0008"  # contexto imutável


def test_eval08_cliente_B_em_sessao_A_negado_sem_expor_B(app, session_a):
    session_a.open_case("CASE_0001")
    with pytest.raises(AccessDenied) as err:
        session_a.open_case("CASE_0008")  # caso do analista B
    assert "CUST_0008" not in str(err.value)
    # O caso anterior continua ativo e nenhum dado de B foi carregado
    assert session_a.context.active_customer_id == "CUST_0001"
    customers = {r["customer_id"] for r in session_a.repository().get_transactions()}
    assert customers == {"CUST_0001"}
    denied = _events(app, "ACCESS_DENIED")
    assert denied and denied[0]["case_id"] == "CASE_0008"
    assert denied[0]["customer_id"] is None  # log sem dado do cliente bloqueado


@pytest.mark.parametrize("case_id", ["CASE_0009", "CASE_9999", "CUST_0001", "' OR 1=1 --", "", "CASE_0001; DROP"])
def test_eval09_identificadores_arbitrarios_rejeitados(session_a, case_id):
    with pytest.raises(AccessDenied):
        session_a.open_case(case_id)
    assert session_a.context is None


def test_eval09_nenhum_metodo_do_repositorio_aceita_customer_id():
    for name in READ_METHODS:
        params = inspect.signature(getattr(ScopedRepository, name)).parameters
        assert list(params) == ["self"], f"{name} não deve receber parâmetros além do contexto"


def test_eval09_assert_same_customer_nega_antes_do_sql(session_a, monkeypatch):
    ctx = session_a.open_case("CASE_0001")
    executed = []
    monkeypatch.setattr(ScopedRepository, "_select", lambda *a, **k: executed.append(a))
    with pytest.raises(AccessDenied):
        assert_same_customer(ctx, "CUST_0008")
    assert executed == []


def test_repositorio_exige_contexto_autorizado(app):
    with pytest.raises(AccessDenied):
        ScopedRepository(object(), app.db)  # type: ignore[arg-type]


@pytest.mark.parametrize("method", READ_METHODS)
def test_todas_as_leituras_retornam_somente_o_cliente_ativo(session_a, method):
    session_a.open_case("CASE_0003")
    result = getattr(session_a.repository(), method)()
    rows = result if isinstance(result, list) else [result]
    for row in rows:
        assert row.get("customer_id") in (None, "CUST_0003")


def test_perfil_nao_expoe_identificadores_nem_demografia(session_a):
    session_a.open_case("CASE_0001")
    profile = session_a.repository().get_customer_profile()
    forbidden = {"full_name", "cpf", "birth_date", "education", "occupation", "household_size",
                 "region", "cohort", "data_completeness_expected"}
    assert forbidden.isdisjoint(profile)
    assert "Marina" not in str(profile)


# ------------------------------------------------------------------ isolamento
def test_roteiro_A_B_A_limpa_estado_e_renova_correlation_id(session_a):
    ctx_a1 = session_a.open_case("CASE_0001")
    session_a.put(ctx_a1.correlation_id, "evidence_bundle", {"cliente": "A"})
    repo_a1 = session_a.repository()

    ctx_b = session_a.open_case("CASE_0002")
    assert session_a.get("evidence_bundle") is None
    assert {r["customer_id"] for r in session_a.repository().get_transactions()} == {"CUST_0002"}
    with pytest.raises(AccessDenied):
        repo_a1.get_transactions()  # repositório antigo foi fechado

    ctx_a2 = session_a.open_case("CASE_0001")
    assert len({ctx_a1.correlation_id, ctx_b.correlation_id, ctx_a2.correlation_id}) == 3
    assert session_a.get("evidence_bundle") is None


def test_resposta_de_caso_anterior_e_descartada(app, session_a):
    ctx_a = session_a.open_case("CASE_0001")
    session_a.open_case("CASE_0002")
    assert session_a.put(ctx_a.correlation_id, "narrative", "texto do caso A") is False
    assert session_a.get("narrative") is None
    assert _events(app, "STALE_RESPONSE_DISCARDED")


def test_eval11_sessoes_simultaneas_sem_contaminacao(app):
    errors: list[str] = []
    plan = {"EMP-001": ["CASE_0001", "CASE_0005", "CASE_0002"], "EMP-002": ["CASE_0008", "CASE_0003"]}
    expected = {"CASE_0001": "CUST_0001", "CASE_0005": "CUST_0005", "CASE_0002": "CUST_0002",
                "CASE_0008": "CUST_0008", "CASE_0003": "CUST_0003"}

    def worker(employee_id: str) -> None:
        session = app.new_session(employee_id)
        for _ in range(15):
            for case_id in plan[employee_id]:
                ctx = session.open_case(case_id)
                session.put(ctx.correlation_id, "marker", case_id)
                seen = {r["customer_id"] for r in session.repository().get_transactions()}
                if seen != {expected[case_id]} or session.get("marker") != case_id:
                    errors.append(f"{employee_id}:{case_id}:{seen}")

    threads = [threading.Thread(target=worker, args=(e,)) for e in plan for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# ------------------------------------------------------------------ somente leitura e schema
def test_conexao_e_somente_leitura(app):
    conn = app.db.connect()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM transactions")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a)")
    conn.close()


def test_schema_incompativel_e_detectado(demo_db, tmp_path, app):
    broken = tmp_path / "broken.db"
    src = sqlite3.connect(demo_db)
    dst = sqlite3.connect(broken)
    src.backup(dst)
    src.close()
    dst.execute("ALTER TABLE transactions RENAME COLUMN amount_brl TO valor")
    dst.commit()
    dst.close()
    with pytest.raises(SchemaMismatch) as err:
        ReadOnlyDatabase(broken, app.schema)
    assert "transactions.amount_brl" in str(err.value)


# ------------------------------------------------------------------ auditoria
def test_auditoria_encadeada_e_somente_insercao(app, session_a):
    session_a.open_case("CASE_0001")
    session_a.open_case("CASE_0002")
    check = app.audit.verify_chain()
    assert check.ok and check.events >= 3
    conn = sqlite3.connect(app.audit.path)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE audit_events SET employee_id = 'x'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM audit_events")
    conn.close()


def test_auditoria_detecta_adulteracao(app, session_a):
    session_a.open_case("CASE_0001")
    conn = sqlite3.connect(app.audit.path)
    conn.execute("DROP TRIGGER audit_events_no_update")
    conn.execute("UPDATE audit_events SET employee_id = 'EMP-666' WHERE seq = 1")
    conn.commit()
    conn.close()
    check = app.audit.verify_chain()
    assert not check.ok and check.first_broken_seq == 1
