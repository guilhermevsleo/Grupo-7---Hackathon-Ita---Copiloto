"""Tema visual (laranja/azul aproximados, sem logotipo oficial) e pequenos construtores de HTML.

Regra de segurança: todo texto dinâmico passa por html.escape antes de entrar em HTML. Textos livres da
base (notas do CRM) nunca entram em HTML: são exibidos com st.text."""
from __future__ import annotations

from html import escape

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root{
  --orange:#EC7000; --orange-ink:#B35400; --blue:#003399; --navy:#00246B; --chart-blue:#2456C9;
  --ink:#15181D; --ink2:#3D4450; --muted:#6B7280; --line:#E5E7EB; --line2:#EEF0F3; --surface:#FFFFFF; --canvas:#F4F5F7;
  --ok:#137A4B; --ok-bg:#E8F5EE; --warn:#8A5300; --warn-bg:#FFF4DE; --crit:#A11B1B; --crit-bg:#FDECEC;
  --info:#1F47B0; --info-bg:#EEF3FF; --gray-bg:#F1F2F4;
}
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], button, input, textarea, select {
  font-family: Inter, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
[data-testid="stAppViewContainer"]{background:var(--canvas)}
[data-testid="stHeader"]{background:transparent}
.block-container{padding:0.9rem 1.6rem 3rem !important; max-width:1280px}
[data-testid="stSidebar"]{background:#fff; border-right:1px solid var(--line)}
[data-testid="stSidebar"] .block-container{padding-top:1rem}
/* setas de recolher/expandir a barra lateral em laranja */
[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"] span,
[data-testid="stExpandSidebarButton"], [data-testid="stExpandSidebarButton"] span{color:var(--orange) !important}
[data-testid="stSidebarCollapseButton"] button:hover, [data-testid="stExpandSidebarButton"]:hover{
  color:var(--orange-ink) !important;background:#FFF2E4 !important}
[data-testid="stMain"] [data-testid="stVerticalBlock"]{gap:0.9rem}
h1,h2,h3,h4{font-family:inherit}

/* barra superior */
.tb{display:flex;align-items:center;gap:12px;background:linear-gradient(90deg,var(--navy),var(--blue));
  border-radius:12px;padding:14px 20px;margin:0 0 4px;border-bottom:3px solid var(--orange);color:#fff}
.tb-mark{width:30px;height:30px;border-radius:8px;background:var(--orange);display:flex;align-items:center;justify-content:center;flex:none}
.tb-mark i{width:12px;height:12px;border:2.5px solid #fff;border-radius:3px;display:block}
.tb-title{font-weight:700;font-size:15px;line-height:1.1}
.tb-sub{font-size:12px;color:#C9D6FF}
.tb-tags{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.tb-tag{font-size:11px;font-weight:600;border:1px solid rgba(255,255,255,.4);background:rgba(255,255,255,.12);
  border-radius:999px;padding:2px 9px;white-space:nowrap}
@media (max-width:760px){.tb{flex-wrap:wrap}.tb-tags{margin-left:0;justify-content:flex-start}}

/* O Streamlit aplica margem negativa (-16px) em todo bloco de markdown para compensar a margem do último
   parágrafo. Nos nossos blocos de HTML (que terminam em <div>) isso cola o texto na borda do card e sobrepõe
   blocos vizinhos; neutralizamos só nesses casos. Parágrafos e listas do Streamlit continuam intactos. */
[data-testid="stMarkdownContainer"]:has(> div:last-child){margin-bottom:0 !important}
[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]{padding:16px 18px !important}

/* faixa do caso */
.cs{display:flex;align-items:center;gap:18px;flex-wrap:wrap;background:#fff;border:1px solid var(--line);
  border-radius:12px;padding:16px 22px;margin:0 0 4px}
.cs-ref{font-size:22px;font-weight:700;color:var(--ink);letter-spacing:-.01em}
.cs-case{font-size:12px;color:var(--muted);font-weight:600;margin-top:-2px}
.cs-item{display:flex;flex-direction:column;gap:3px}
.cs-item small{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;font-weight:600}
.cs-item b{font-size:13px;color:var(--ink2);font-weight:600}
.cs-sep{width:1px;align-self:stretch;background:var(--line)}

/* chips e pílulas de status (sempre com texto, nunca só cor) */
.chip{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:2px 9px;font-size:12px;font-weight:600;
  border:1px solid transparent;white-space:nowrap}
.chip::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.c-ok{background:var(--ok-bg);color:var(--ok)} .c-warn{background:var(--warn-bg);color:var(--warn)}
.c-crit{background:var(--crit-bg);color:var(--crit)} .c-info{background:var(--info-bg);color:var(--info)}
.c-gray{background:var(--gray-bg);color:var(--muted)}

/* indicadores */
.kpis-wrap{container-type:inline-size}
.kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin:0 0 4px}
@container (max-width:860px){.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
@container (max-width:520px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
.kpi{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 18px 14px;min-height:126px;
  display:flex;flex-direction:column;gap:4px}
.kpi-top{display:flex;align-items:center;justify-content:space-between;gap:6px}
.kpi-label{font-size:12px;font-weight:600;color:var(--ink2)}
.qdot{width:8px;height:8px;border-radius:50%;flex:none}
.q-SUFFICIENT{background:var(--ok)} .q-PARTIAL{background:#D08A00} .q-INSUFFICIENT{background:var(--crit)}
.kpi-value{font-size:22px;font-weight:700;color:var(--ink);letter-spacing:-.01em;line-height:1.15}
.kpi-value small{font-size:12px;font-weight:500;color:var(--muted);margin-left:2px}
.kpi-value.na{font-size:16px;color:var(--muted)}
.kpi-delta{font-size:12px;font-weight:600}
.d-bad{color:var(--crit)} .d-warn{color:var(--warn)} .d-good{color:var(--ok)} .d-neutral{color:var(--muted)}
.kpi-foot{font-size:11.5px;color:var(--muted);line-height:1.4;margin-top:2px}
.meter{height:6px;border-radius:999px;background:#E7ECF7;overflow:hidden;margin:2px 0}
.meter i{display:block;height:100%;border-radius:999px}

/* cartões */
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.card-h{display:flex;align-items:center;gap:8px;margin:0 0 8px;font-size:12px;font-weight:700;color:var(--ink2);
  text-transform:uppercase;letter-spacing:.06em}
.card-h .count{margin-left:auto;text-transform:none;letter-spacing:0;font-weight:600;color:var(--muted)}
.muted{color:var(--muted)} .small{font-size:12px}

/* resumo */
.sum p{margin:0 0 8px;font-size:14.5px;line-height:1.5;color:var(--ink)}
.sum-foot{font-size:11.5px;color:var(--muted);border-top:1px solid var(--line2);padding-top:10px;margin-top:8px;line-height:1.45}
.note{border-radius:10px;padding:9px 12px;font-size:13px;line-height:1.45;margin-bottom:8px}
.note.info{background:var(--info-bg);color:#1B3A8C} .note.crit{background:var(--crit-bg);color:#7D1515}
.note.warn{background:var(--warn-bg);color:#6B4100} .note.ok{background:var(--ok-bg);color:#0F5C39}
.reasons{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px}
.ev{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:var(--muted);background:var(--gray-bg);
  border-radius:4px;padding:0 5px;margin-left:4px;white-space:nowrap}

/* sinais */
.sig{display:flex;gap:10px;padding:8px 0;border-top:1px solid var(--line2)}
.sig:first-of-type{border-top:0;padding-top:2px}
.sig-ic{flex:none;width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700}
.t-alert{background:var(--crit-bg);color:var(--crit)} .t-warn{background:var(--warn-bg);color:var(--warn)}
.t-info{background:var(--info-bg);color:var(--info)} .t-gap{background:var(--gray-bg);color:var(--muted)}
.sig b{font-size:13.5px;color:var(--ink);font-weight:600}
.sig div div{font-size:12.5px;color:var(--ink2);line-height:1.4}

/* qualidade */
.qrow{display:flex;align-items:center;gap:8px;padding:5px 0;border-top:1px solid var(--line2);font-size:13px}
.qrow:first-of-type{border-top:0}
.qrow .lbl{color:var(--ink)} .qrow .st{margin-left:auto;font-size:12px;font-weight:600}
.qreason{font-size:11.5px;color:var(--muted);margin:0 0 6px 16px;line-height:1.45}
.st-SUFFICIENT{color:var(--ok)} .st-PARTIAL{color:var(--warn)} .st-INSUFFICIENT{color:var(--crit)}

/* linha do tempo */
.tl{position:relative;padding-left:14px}
.tl::before{content:"";position:absolute;left:4px;top:4px;bottom:4px;width:2px;background:var(--line)}
.tl-i{position:relative;padding:3px 0 7px}
.tl-i::before{content:"";position:absolute;left:-14px;top:7px;width:10px;height:10px;border-radius:50%;background:#fff;
  border:2px solid var(--orange)}
.tl-i.k-contato::before{border-color:#9AA3B2} .tl-i.k-visibilidade::before{border-color:#9AA3B2;border-style:dashed}
.tl-i small{font-size:11px;color:var(--muted);font-weight:600}
.tl-i div{font-size:13px;color:var(--ink);line-height:1.35}

/* hipóteses e perguntas */
.hyp{border:1px dashed #F0C79A;background:#FFFBF4;border-left:3px solid var(--orange);border-radius:10px;padding:9px 12px;margin-bottom:8px}
.hyp small{font-size:10.5px;font-weight:700;letter-spacing:.08em;color:var(--orange-ink)}
.hyp div{font-size:14px;color:var(--ink);line-height:1.45}
.q{display:flex;gap:10px;padding:7px 0;border-top:1px solid var(--line2);font-size:14px;color:var(--ink);line-height:1.4}
.q:first-of-type{border-top:0}
.q span{flex:none;width:20px;height:20px;border-radius:50%;background:var(--info-bg);color:var(--info);font-size:11px;
  font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:1px}

/* fatos */
.fact{font-size:13.5px;color:var(--ink);line-height:1.45;padding:2px 0}
.topic{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--blue);margin:6px 0 0}
table.mini{width:100%;border-collapse:collapse;font-size:13px}
table.mini th{font-size:11px;color:var(--muted);text-align:left;font-weight:600;padding:4px 6px;border-bottom:1px solid var(--line)}
table.mini td{padding:5px 6px;border-bottom:1px solid var(--line2);color:var(--ink)}

/* estado vazio */
.empty{background:#fff;border:1px solid var(--line);border-radius:14px;padding:26px 28px}
.empty h3{margin:0 0 6px;font-size:20px;color:var(--ink)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:16px}
.step{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:#FCFCFD}
.step b{display:block;font-size:13.5px;color:var(--ink);margin-bottom:3px}
.step span{font-size:12.5px;color:var(--ink2);line-height:1.4}
.step i{font-style:normal;display:inline-flex;width:22px;height:22px;border-radius:50%;background:var(--orange);color:#fff;
  font-size:12px;font-weight:700;align-items:center;justify-content:center;margin-bottom:6px}

/* componentes do Streamlit */
[data-testid="stTab"]{padding:8px 14px !important}
[data-testid="stTab"] p{font-weight:600 !important;font-size:14px !important}
[data-testid="stTab"][aria-selected="true"]{box-shadow:inset 0 -3px 0 var(--orange)}
[data-testid="stTab"][aria-selected="true"] p{color:var(--navy) !important}
[data-testid="stPopover"] button{min-height:26px;padding:0 8px;font-size:12px}
[data-testid="stForm"]{background:#fff;border:1px solid var(--line);border-radius:12px}
/* caixas de texto visíveis (decisão e observações) */
[data-testid="stTextArea"] [data-baseweb="textarea"]{border:1px solid #C9D0DA !important;border-radius:10px !important;
  background:#FAFBFC !important}
[data-testid="stTextArea"] textarea{background:#FAFBFC !important;color:var(--ink) !important}
[data-testid="stTextArea"] [data-baseweb="textarea"]:focus-within{border-color:var(--orange) !important;
  box-shadow:0 0 0 3px rgba(236,112,0,.15) !important;background:#fff !important}
/* colunas que empilham em telas estreitas (containers com key) */
.st-key-overview [data-testid="stColumn"], .st-key-conversa [data-testid="stColumn"],
.st-key-evidencias [data-testid="stColumn"].colmain{min-width:300px}
.st-key-overview > div > [data-testid="stHorizontalBlock"], .st-key-conversa > div > [data-testid="stHorizontalBlock"]{flex-wrap:wrap}
.foot{color:var(--muted);font-size:11.5px;margin-top:18px;border-top:1px solid var(--line);padding-top:10px;line-height:1.5}
@media (prefers-reduced-motion:no-preference){.pulse{animation:pulse 1.6s ease-in-out infinite}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
</style>
"""

QUALITY_WORD = {"SUFFICIENT": "Suficiente", "PARTIAL": "Parcial", "INSUFFICIENT": "Insuficiente"}
CASE_STATUS = {"COMPLETE": ("Dados completos", "c-ok"), "PARTIAL": ("Dados parciais", "c-warn"),
               "INSUFFICIENT_DATA": ("Dados insuficientes", "c-crit")}


def e(text) -> str:
    return escape(str(text)) if text is not None else ""


def chip(label: str, cls: str, title: str = "") -> str:
    return f'<span class="chip {cls}" title="{e(title)}">{e(label)}</span>'


def ev_tags(ids: list[str], limit: int = 3) -> str:
    shown = "".join(f'<span class="ev">{e(i.split("-")[0])}</span>' for i in ids[:limit])
    return shown + (f'<span class="ev">+{len(ids) - limit}</span>' if len(ids) > limit else "")


def topbar(dataset_label: str) -> str:
    return f"""<div class="tb">
  <div class="tb-mark" aria-hidden="true"><i></i></div>
  <div><div class="tb-title">Copiloto de Contexto</div><div class="tb-sub">Cobrança e renegociação</div></div>
  <div class="tb-tags"><span class="tb-tag">Dados sintéticos · ref. 01/09/2026</span>
  <span class="tb-tag">{e(dataset_label)}</span><span class="tb-tag">Protótipo de hackathon</span></div>
</div>"""
