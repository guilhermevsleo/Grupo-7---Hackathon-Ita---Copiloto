class CopilotoError(Exception):
    """Erro base da aplicação."""


class AccessDenied(CopilotoError):
    """Acesso negado: colaborador sem direito ao caso ou cliente divergente do caso ativo."""


class SchemaMismatch(CopilotoError):
    """A base não tem as colunas exigidas pelo mapa de schema."""


class AuditUnavailable(CopilotoError):
    """A trilha de auditoria não pôde ser gravada; a operação não deve ser confirmada."""


class NarrationFailed(CopilotoError):
    """Falha, timeout ou resposta inutilizável do provedor de LLM."""
