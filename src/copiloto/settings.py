"""Constantes do MVP e configuração carregada do ambiente."""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

# Referência temporal fixa do dataset (briefing §13). Nunca usar datetime.now() para cálculo financeiro.
REFERENCE_DATE = date(2026, 9, 1)
WINDOW_START = date(2025, 9, 1)
WINDOW_END = date(2026, 8, 31)
PRIOR_WINDOW = (date(2026, 3, 1), date(2026, 5, 31))
RECENT_WINDOW = (date(2026, 6, 1), date(2026, 8, 31))

FEATURE_ENGINE_VERSION = "fe-0.1.0"
CONTEXT_SCHEMA_VERSION = "ctx-0.1.0"
PROMPT_VERSION = "prompt-v2"

PURPOSE_ID = "employee_financial_context"
PURPOSE = ("auxiliar colaborador de cobrança a compreender o contexto financeiro observável "
           "de um cliente autorizado")
UI_DATA_BADGE = "Dados sintéticos — referência 01/09/2026"
PROTOTYPE_NOTICE = ("Protótipo de hackathon (Hackathon Itaú 2026, Case C). Não é produto nem "
                    "comunicado oficial do Itaú. Todos os dados são sintéticos.")
GOVERNANCE_STATEMENT = ("Arquitetura do MVP incorpora controles preliminares de governança, "
                        "segurança e privacidade. Uso real exigiria validação das políticas internas, "
                        "requisitos jurídicos e controles organizacionais aplicáveis.")
OPEN_FINANCE_NOTICE = ("Comportamentos do MVP sobre status Open Finance representam regras analíticas "
                       "da base sintética, não política jurídica ou operacional do Itaú.")
BLOCKED_NARRATIVE_MESSAGE = "Não foi possível validar o contexto gerado pela IA."
LLM_TIER_NOTICE = {
    "free": ("Plano gratuito da API Gemini: o fornecedor pode usar o conteúdo enviado para melhorar seus "
             "produtos. Por isso só sai o pacote minimizado, com dados sintéticos. Com dados de clientes, "
             "seria necessário plano pago e validação jurídica."),
    "paid": ("Plano pago da API Gemini. Uso com dados reais ainda exige validação jurídica "
             "(retenção, subprocessadores, transferência internacional)."),
}

OFFICIAL_DB_NAME = "synthetic_banking.db"
DEMO_DB_NAME = "demo_synthetic_bank.db"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    audit_db_path: Path
    config_dir: Path
    gemini_model: str
    llm_timeout_s: float
    google_api_key_present: bool
    gemini_tier: str = "free"
    gemini_thinking: str = "low"
    gemini_fallback_models: tuple[str, ...] = ()

    @property
    def llm_tier_notice(self) -> str:
        return LLM_TIER_NOTICE.get(self.gemini_tier, LLM_TIER_NOTICE["free"])

    @property
    def is_official_dataset(self) -> bool:
        return self.db_path.name == OFFICIAL_DB_NAME

    @property
    def dataset_label(self) -> str:
        if self.is_official_dataset:
            return "Base sintética oficial do hackathon"
        return "Base de demonstração gerada pelo time (sintética)"


def _resolve_db_path() -> Path:
    explicit = os.getenv("COPILOTO_DB_PATH", "").strip()
    if explicit:
        return Path(explicit).resolve()
    official = PROJECT_ROOT / "data" / OFFICIAL_DB_NAME
    if official.exists():
        return official
    return PROJECT_ROOT / "data" / DEMO_DB_NAME


def load_settings() -> Settings:
    return Settings(
        db_path=_resolve_db_path(),
        audit_db_path=Path(os.getenv("COPILOTO_AUDIT_DB_PATH", PROJECT_ROOT / "data" / "audit.db")),
        config_dir=PROJECT_ROOT / "config",
        gemini_model=os.getenv("COPILOTO_GEMINI_MODEL", "gemini-3.8-flash").strip(),
        llm_timeout_s=float(os.getenv("COPILOTO_LLM_TIMEOUT_S", "45")),
        google_api_key_present=bool(os.getenv("GOOGLE_API_KEY", "").strip()),
        gemini_tier=os.getenv("COPILOTO_GEMINI_TIER", "free").strip().lower() or "free",
        gemini_thinking=os.getenv("COPILOTO_GEMINI_THINKING", "low").strip().lower() or "low",
        gemini_fallback_models=tuple(m.strip() for m in os.getenv(
            "COPILOTO_GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite").split(",") if m.strip()),
    )


@lru_cache(maxsize=8)
def _file_digest(path: str, mtime: float) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def snapshot_version(db_path: Path) -> str:
    """Versão do snapshot = nome + hash do conteúdo. Mesma base => mesma versão."""
    return f"{db_path.name}@sha256:{_file_digest(str(db_path), db_path.stat().st_mtime)}"


def pseudonym_secret() -> bytes:
    """Segredo do HMAC de pseudonimização. Vem do .env ou de um arquivo local fora do git."""
    env = os.getenv("COPILOTO_PSEUDONYM_SECRET", "").strip()
    if env:
        return env.encode()
    path = PROJECT_ROOT / "data" / ".pseudonym_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip().encode()
