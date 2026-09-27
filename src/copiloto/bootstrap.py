"""Monta os componentes da aplicação a partir da configuração."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .audit import AuditService
from .auth import EntitlementStore
from .directory import CaseDirectory
from .pseudonym import Pseudonymizer
from .schema_map import ReadOnlyDatabase, SchemaMap
from .session import CaseSession
from .settings import Settings, load_settings, pseudonym_secret, snapshot_version


@dataclass
class App:
    settings: Settings
    schema: SchemaMap
    db: ReadOnlyDatabase
    entitlements: EntitlementStore
    directory: CaseDirectory
    audit: AuditService
    sensitive_categories: frozenset[str]
    sensitive_label: str
    snapshot_version: str

    def new_session(self, employee_id: str) -> CaseSession:
        return CaseSession(employee_id=employee_id, entitlements=self.entitlements,
                           directory=self.directory, db=self.db, audit=self.audit)


def build_app(settings: Settings | None = None, *, db_path: Path | None = None,
              audit_path: Path | None = None, secret: bytes | None = None) -> App:
    settings = settings or load_settings()
    cfg = settings.config_dir
    schema = SchemaMap(cfg / "schema_map.yaml")
    db = ReadOnlyDatabase(db_path or settings.db_path, schema)
    sensitive = yaml.safe_load((cfg / "sensitive_categories.yaml").read_text(encoding="utf-8"))
    return App(
        settings=settings,
        schema=schema,
        db=db,
        entitlements=EntitlementStore.from_yaml(cfg / "entitlements.yaml"),
        directory=CaseDirectory(db, Pseudonymizer(secret or pseudonym_secret())),
        audit=AuditService(audit_path or settings.audit_db_path),
        sensitive_categories=frozenset(sensitive.get("categories", [])),
        sensitive_label=sensitive.get("neutral_label", "categoria potencialmente sensível"),
        snapshot_version=snapshot_version(db.path),
    )
