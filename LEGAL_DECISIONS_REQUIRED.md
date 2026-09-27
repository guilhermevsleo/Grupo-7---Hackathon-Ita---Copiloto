# Decisões jurídicas e de privacidade pendentes

Este MVP **não interpreta a LGPD** nem define política jurídica. Cada item abaixo depende de validação humana
por responsáveis jurídicos e de privacidade. Enquanto isso, o protótipo implementa apenas o comportamento
técnico neutro descrito na coluna "Comportamento no MVP" e usa **somente dados sintéticos**.

`requires_human_legal_privacy_validation = true` para todos os itens.

| # | Tema | Comportamento no MVP (técnico, neutro) | Status |
|---|---|---|---|
| L-01 | Base legal de tratamento | Nenhuma base legal escolhida; `legal_basis.status: NOT_DEFINED_IN_MVP` em `config/privacy_policy.yaml`. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-02 | Política real de Open Finance (uso, escopo, expiração, revogação) | Status tratado só como disponibilidade e qualidade analítica. EXPIRED: histórico anterior é exibido com a data da última sincronização; nenhuma regra automática de exclusão ou retenção. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-03 | Retenção da trilha de auditoria e dos contextos exibidos | Guardados localmente em `data/audit.db`, somente inserção, sem prazo definido. `retention.status: NOT_DEFINED_FOR_REAL_DATA`. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-04 | Descarte | Não implementado para dados reais. Na demo, apagar `data/` descarta tudo. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-05 | Envio de dados ao fornecedor de LLM (Google Gemini) | O protótipo usa o **plano gratuito** da API Gemini, ciente de que, nesse plano, os termos do fornecedor permitem usar o conteúdo enviado para melhorar os produtos dele. Por isso só envia o pacote minimizado (sem identificadores diretos, sem texto livre, com pseudônimo) e só com dados sintéticos. **O time está ciente de que, com dados de clientes, seria necessário um plano pago**, em que o conteúdo não é usado para esse fim segundo os termos do fornecedor. O plano pago é condição mínima, não suficiente: retenção, subprocessadores e transferência internacional (L-06) continuam exigindo avaliação. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-06 | Transferência internacional de dados | Não avaliada. Com dados reais, o envio ao Gemini pode envolver processamento fora do Brasil. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-07 | Papéis de controlador e operador | Não definidos. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-08 | Políticas internas do Itaú (acesso, cobrança, IA, segurança) | Não consultadas; o MVP não se apresenta como aderente a elas. Horários, canais e regras de cobrança ficaram fora do escopo. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-09 | Requisitos para uso com dados reais | `real_data.allowed: false`. Autenticação corporativa, perfis de acesso, TLS, proteção do armazenamento e avaliação de impacto são pré-requisitos não implementados. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-10 | Direitos do titular aplicáveis (acesso, correção, explicação, revisão) | Não implementados. A rastreabilidade por evidência e a reconstrução do contexto exibido podem apoiar esses processos no futuro, mas isso não foi validado. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-11 | Pseudonimização | O pseudônimo C-XXXX é HMAC do identificador interno. É pseudonimização, **não** anonimização garantida. | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |
| L-12 | Categorias potencialmente sensíveis de despesa | Mostradas ao colaborador só como mudança financeira; agregadas com rótulo neutro para o LLM. A lista é proposta do time (`config/sensitive_categories.yaml`). | REQUIRES_HUMAN_LEGAL_PRIVACY_VALIDATION |

Arquitetura do MVP incorpora controles preliminares de governança, segurança e privacidade. Uso real exigiria
validação das políticas internas, requisitos jurídicos e controles organizacionais aplicáveis.
