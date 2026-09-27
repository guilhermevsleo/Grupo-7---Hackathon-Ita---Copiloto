# Copiloto de Contexto Financeiro — Hackathon Itaú 2026 (Case C)

> Protótipo de hackathon. Não é produto nem comunicado oficial do Itaú. Todos os dados são sintéticos.

Copiloto para colaboradores de cobrança e renegociação. Ele reúne os dados de **um** cliente autorizado e
entrega fatos verificáveis, sinais, linha do tempo, hipóteses a validar, informações ausentes, perguntas
neutras e limitações. Cada afirmação vem com a sua evidência. **O agente prepara o contexto; o colaborador decide.**

## Como rodar

### 1. Pré-requisitos

- **Python 3.12** (a versão testada). No Windows, pelo gerenciador oficial: `py install 3.12`.
  No macOS/Linux, use o Python 3.12 do seu sistema, do `pyenv` ou do site python.org.
- **Chave da API Gemini** (opcional): crie em [aistudio.google.com](https://aistudio.google.com) → *Get API key*.
  Sem chave, o app funciona em "modo sem IA", só com fatos e sinais calculados.

### 2. Instalar (uma vez só)

Abra um terminal na pasta do projeto (`copiloto`).

**Windows (PowerShell):**

```powershell
py -V:3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python tools\build_demo_db.py
```

**macOS / Linux:**

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python tools/build_demo_db.py
```

O último comando gera a base de demonstração em `data/demo_synthetic_bank.db`. Pule esse passo se for usar a
base oficial (veja o passo 4).

### 3. Configurar a IA (opcional)

Abra o arquivo `.env` e cole a chave depois de `GOOGLE_API_KEY=`. **Nunca** envie o `.env` para o repositório,
os slides ou o vídeo (ele já está no `.gitignore`). As outras opções do `.env`:

| Variável | Padrão | Para que serve |
|---|---|---|
| `COPILOTO_GEMINI_MODEL` | `gemini-3.8-flash` | Modelo principal |
| `COPILOTO_GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash,gemini-3.5-flash-lite` | Modelos reserva se o principal estiver indisponível |
| `COPILOTO_GEMINI_THINKING` | `low` | Nível de raciocínio do modelo (`low` é mais rápido) |
| `COPILOTO_LLM_TIMEOUT_S` | `45` | Tempo máximo de espera pela IA, em segundos |
| `COPILOTO_GEMINI_TIER` | `free` | Plano da API; muda o aviso de privacidade na tela |
| `COPILOTO_DB_PATH` | vazio | Caminho de outra base (senão usa a oficial ou a de demonstração) |

### 4. Usar a base oficial (opcional)

Copie `agent_input/synthetic_banking.db` do pacote do hackathon para `data/synthetic_banking.db`, **sem** a pasta
`evaluator_only/`. O app passa a usá-la automaticamente. Depois:

```powershell
.venv\Scripts\python tools\inspect_db.py
```

Esse comando aponta colunas com nome diferente do esperado e os `case_id` da base. Ajuste
`config/schema_map.yaml` e `config/entitlements.yaml` e rode os testes de novo.

### 5. Rodar o app

**Windows:**

```powershell
.venv\Scripts\python -m streamlit run app\streamlit_app.py
```

**macOS / Linux:**

```bash
.venv/bin/python -m streamlit run app/streamlit_app.py
```

Abra **http://localhost:8501** no navegador. Na barra lateral, escolha **Ana (analista)** e um caso da fila.
Para parar o app, pressione `Ctrl+C` no terminal.

### 6. Testes, avaliações e PDFs

```powershell
.venv\Scripts\python -m pytest                   # 109 testes automatizados
.venv\Scripts\python tools\run_evals.py          # placar dos 18 evals em docs/EVALS_REPORT.md
.venv\Scripts\python tools\live_eval.py          # mede o Gemini real (consome cota da API)
```

Para regenerar os PDFs da apresentação e do guia (usa o Microsoft Edge instalado):

```powershell
.venv\Scripts\python -m pip install -r requirements-docs.txt
.venv\Scripts\python tools\capture_screens.py    # com o app rodando em localhost:8501
.venv\Scripts\python tools\build_pdfs.py         # gera os PDFs em docs/apresentacao/
```

### 7. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| "Não foi possível abrir a base de dados" | Rode `tools/build_demo_db.py` ou confira `COPILOTO_DB_PATH` |
| Barra lateral diz "Chave não configurada" | Preencha `GOOGLE_API_KEY` no `.env` e reinicie o app |
| "IA indisponível" ou demora | Alta demanda no plano gratuito (erro 503) ou modelo retirado (404). O app mostra os fatos calculados e tenta os modelos reserva; se persistir, troque `COPILOTO_GEMINI_MODEL` |
| "Port 8501 is already in use" | Outro app está aberto: feche-o ou rode com `--server.port 8502` |
| Mudei o código e a tela não mudou | Pare o app (`Ctrl+C`) e rode de novo |
| Quero começar a demo com a auditoria limpa | Com o app parado, apague `data/audit.db` |

## Roteiro de uso

1. Na barra lateral, escolha a identidade simulada **Ana (analista)**. "Sua fila" mostra só os casos autorizados
   para ela, em ordem de número; não existe busca nem priorização de clientes.
2. Abra um caso. No topo ficam sempre visíveis a **faixa do caso** (pseudônimo C-XXXX, status dos dados, estado
   da IA, tempo) e **5 indicadores** (entradas, despesa econômica, uso do cartão, parcelas ÷ entradas, atraso),
   cada um com o ponto de qualidade da métrica e um botão para as evidências.
3. O trabalho segue três etapas:
   - **① Visão geral:** resumo (IA validada ou fatos por regra), sinais, gráfico mensal (meses sem visibilidade
     ficam em bege, sem valor desenhado), confiabilidade dos dados e linha do tempo.
   - **② Evidências:** cada fato com o botão "Ver" (fonte, período, cálculo, limitações, linhas de origem),
     tabela do fluxo mensal, conciliação do cartão e limitações.
   - **③ Conversa e decisão:** hipóteses a validar, perguntas neutras, interações e notas do CRM (texto não
     confiável), o que falta saber e o registro da decisão (campo vazio).
4. Os fatos aparecem na hora; o resumo da IA chega de 10 a 30 segundos depois ("IA redigindo…").
5. Em **Ações do caso** (barra lateral), "Testar o validador" envia uma resposta propositalmente inválida
   (número inventado, oferta, inferência sensível) e mostra o bloqueio ao vivo, com os motivos em
   "Por que foi bloqueado?". A tela identifica que é um teste simulado.
6. Troque para **Sérgio (risco)**: o painel de governança mostra a integridade da trilha, a taxa de bloqueio
   das respostas reais do Gemini (separada dos testes simulados e das falhas do provedor), a reconstrução de
   qualquer contexto exibido e o interruptor que desliga a IA para todos.

Para começar a demo com a trilha de auditoria limpa, apague `data/audit.db` com o app parado.

Casos da base de demonstração: 0001 queda real de entradas · 0002 Open Finance expirado · 0003 acordo rompido
e nota maliciosa · 0004 dados insuficientes · 0005 pico isolado · 0006 categoria sensível · 0007 referência.

## Arquitetura

```
Colaborador simulado ─► authorize_case (nega por padrão) ─► ActiveCaseContext imutável (servidor)
  ─► ScopedRepository (SQLite somente leitura, sem parâmetro customer_id, JOIN com dono nas duas pontas)
  ─► Qualidade por fonte e por métrica ─► Motor de features determinístico (centavos, Decimal)
  ─► Pacote de evidências (E07-9F3A…) ─► Minimizador ─► Agente ADK + Gemini (sem ferramentas)
  ─► validate_agent_output ─✗─► só fatos determinísticos + "Não foi possível validar o contexto gerado pela IA."
                           ─✓─► marcadores substituídos pelos valores calculados ─► Streamlit
  ─► Decisão humana (texto livre, vazio) ─► AuditService (audit.db, somente inserção, hash encadeado)
```

| Camada | Arquivo | Controle principal |
|---|---|---|
| Autorização | `src/copiloto/auth.py`, `session.py` | Nega por padrão; `customer_id` resolvido no servidor; a troca de caso limpa o estado e gera novo `correlation_id` |
| Dados | `repository.py`, `config/schema_map.yaml` | Somente leitura, projeção explícita, filtro pelo cliente ativo em toda consulta |
| Cálculo | `features/` | Transferência própria, resgate, Pix de terceiro, cartão × fatura e ausência ≠ zero |
| Qualidade | `features/quality.py` | SUFFICIENT/PARTIAL/INSUFFICIENT por métrica, sem score global |
| Evidências | `evidence.py` | Todo fato, sinal e evento aponta evidências reproduzíveis |
| LLM | `minimizer.py`, `agent/` | Payload mínimo; o agente não tem ferramentas; sessão descartável por chamada |
| Validação | `validator.py` | Reprova a saída inteira: evidência alheia, número fora de marcador, oferta, canal, horário, ranking, intenção, inferência sensível, causalidade, dramatização |
| Auditoria | `audit.py` | Versões de snapshot, motor, prompt, modelo e schema; contexto exibido; decisão humana |

## O que é real e o que é simulado

| Real, funcionando | Simulado ou fora do MVP |
|---|---|
| Autorização por caso, isolamento, somente leitura, auditoria, validador, cálculos e evidências | Login: a identidade é simulada |
| Agente Google ADK + Gemini (com `GOOGLE_API_KEY`) | Base: a de demonstração foi gerada pelo time até a base oficial ser configurada |
| Bloqueio da saída inválida (testado com respostas adversariais roteirizadas) | Nenhuma integração com sistemas do banco; registrar a decisão não executa cobrança |
| 96 testes automatizados, incluindo os 18 evals do briefing | Ganho de tempo e de qualidade para o colaborador ainda precisa de teste com usuários |

## Limites e governança

- Arquitetura do MVP incorpora controles preliminares de governança, segurança e privacidade. Uso real exigiria
  validação das políticas internas, requisitos jurídicos e controles organizacionais aplicáveis.
- Requisitos orientados pela ISO/IEC 42001 (prévia do documento), sem alegação de conformidade.
- Comportamentos do MVP sobre status Open Finance representam regras analíticas da base sintética, não política
  jurídica ou operacional do Itaú.
- **Plano da API Gemini:** usamos o plano gratuito, em que os termos do fornecedor permitem usar o conteúdo enviado
  para melhorar os produtos dele. Por isso o protótipo envia só o pacote minimizado e só dados sintéticos. Estamos
  cientes de que, com dados de clientes, seria necessário um plano pago; ele é condição mínima, não suficiente,
  e a avaliação jurídica continua pendente (L-05 e L-06).
- Pendências jurídicas: [LEGAL_DECISIONS_REQUIRED.md](LEGAL_DECISIONS_REQUIRED.md). Decisões de implementação:
  [DECISIONS.md](DECISIONS.md). Política técnica: [config/privacy_policy.yaml](config/privacy_policy.yaml).
- A lista de termos do validador é uma rede de segurança, não garantia semântica. Por isso os fatos são
  determinísticos e toda frase exige evidência.
