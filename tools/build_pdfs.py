"""Gera os PDFs da apresentação (16:9) e do guia dos apresentadores (A4) a partir do HTML em docs/apresentacao.

Usa o Microsoft Edge instalado (Playwright, channel="msedge"). Também salva prévias PNG das páginas
em docs/apresentacao/previa/ para conferência visual.

Uso:  python tools/build_pdfs.py
"""
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "apresentacao"
JOBS = [
    ("apresentacao.html", "Copiloto_de_Contexto_Apresentacao.pdf", {"width": "1280px", "height": "720px"}),
    ("guia_apresentadores.html", "Copiloto_de_Contexto_Guia_dos_Apresentadores.pdf", {
        "format": "A4", "display_header_footer": True, "header_template": "<span></span>",
        "footer_template": ('<div style="font-size:8px;color:#6B7280;width:100%;padding:0 16mm;display:flex;'
                            'justify-content:space-between;font-family:Segoe UI,Arial"><span>Copiloto de Contexto · '
                            'Guia dos apresentadores · protótipo de hackathon, dados sintéticos</span><span>'
                            '<span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'),
        "margin": {"top": "14mm", "right": "16mm", "bottom": "16mm", "left": "16mm"}}),
]


def main() -> None:
    preview = DOCS / "previa"
    preview.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        for src, out, size in JOBS:
            if not (DOCS / src).exists():
                print("ignorado (não existe):", src)
                continue
            page.goto((DOCS / src).as_uri())
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            opts = {"margin": {"top": "0", "right": "0", "bottom": "0", "left": "0"}, "prefer_css_page_size": True}
            opts.update(size)
            page.pdf(path=str(DOCS / out), print_background=True, **opts)
            pdf = pdfium.PdfDocument(str(DOCS / out))
            print(f"{out}: {len(pdf)} páginas")
            for i in range(len(pdf)):
                pdf[i].render(scale=1.1).to_pil().save(preview / f"{Path(out).stem}_p{i + 1:02d}.png")
            pdf.close()
        browser.close()


if __name__ == "__main__":
    main()
