"""Captura telas reais do app (Streamlit rodando em localhost:8501) para a apresentação e o guia.

Usa o Microsoft Edge instalado (Playwright, channel="msedge"), em sessão própria.
A primeira tela usa a IA real (1 chamada ao Gemini, com uma nova tentativa se o provedor falhar);
as demais são capturadas com a IA desligada.

Uso:  python tools/capture_screens.py [url]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "apresentacao" / "img"
URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501"
ONLY_FIRST = "--so-primeira" in sys.argv
SKIP_FIRST = "--sem-primeira" in sys.argv


def settle(page: Page, ms: int = 1200) -> None:
    page.wait_for_timeout(ms)
    page.wait_for_function("!document.querySelector('[data-testid=\"stStatusWidget\"]') || "
                           "!document.querySelector('[data-testid=\"stStatusWidget\"]').innerText.includes('Running')",
                           timeout=120_000)
    page.wait_for_timeout(400)


def open_case(page: Page, case_id: str) -> None:
    page.locator('[data-testid="stSidebar"] label').filter(has_text=case_id).first.click()
    page.wait_for_function(f"document.querySelector('.cs') && document.querySelector('.cs').innerText.includes('{case_id}')",
                           timeout=60_000)
    settle(page)


def wait_ai(page: Page) -> str:
    page.wait_for_function("!document.body.innerText.includes('A IA está redigindo')", timeout=120_000)
    settle(page, 800)
    text = page.locator(".cs").inner_text()
    for state in ("IA validada", "IA bloqueada", "IA indisponível", "Sem IA"):
        if state in text:
            return state
    return "?"


def main_clip(page: Page, top_selector: str | None = None, bottom_selector: str | None = None, pad: int = 12) -> dict:
    main = page.locator('[data-testid="stMain"] .block-container').first.bounding_box()
    y0, y1 = main["y"], main["y"] + main["height"]
    if top_selector:
        y0 = page.locator(top_selector).first.bounding_box()["y"] - pad
    if bottom_selector:
        b = page.locator(bottom_selector).first.bounding_box()
        y1 = b["y"] + b["height"] + pad
    vp = page.viewport_size
    y1 = min(y1, vp["height"])
    return {"x": main["x"], "y": max(0, y0), "width": main["width"], "height": y1 - max(0, y0)}


def shot(page: Page, name: str, clip: dict | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page.mouse.move(2, 2)  # evita tooltips de hover na captura
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / name), clip=clip)
    print("ok", name)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=2)
        page.goto(URL)
        page.wait_for_selector("text=Identidade simulada", timeout=60_000)
        settle(page)

        # 0. estado inicial (fila e explicação das 3 etapas)
        shot(page, "00_inicio.png")

        # 1. visão geral com a IA real
        if SKIP_FIRST:  # recaptura só das telas sem IA
            page.locator('[data-testid="stSidebar"]').get_by_text("Resumo e hipóteses com IA").click()
            settle(page)
            open_case(page, "CASE_0001")
            return capture_rest(page, browser, ai_already_off=True)
        open_case(page, "CASE_0001")
        state = wait_ai(page)
        if state != "IA validada":
            page.locator('[data-testid="stSidebar"] button').filter(has_text="Remontar contexto").first.click()
            settle(page)
            state = wait_ai(page)
        print("estado da IA na tela 1:", state)
        page.set_viewport_size({"width": 1440, "height": 1180})
        settle(page, 600)
        shot(page, "01_visao_geral.png")
        if ONLY_FIRST:
            browser.close()
            return

        capture_rest(page, browser, ai_already_off=False)


def capture_rest(page: Page, browser, *, ai_already_off: bool) -> None:
    if True:
        # desliga a IA para as demais telas (sem gastar cota)
        page.set_viewport_size({"width": 1440, "height": 1000})
        if not ai_already_off:
            page.locator('[data-testid="stSidebar"]').get_by_text("Resumo e hipóteses com IA").click()
            settle(page)

        # 2. evidência de um fato (aba 2)
        page.get_by_role("tab", name=re.compile("Evidências")).click()
        settle(page, 600)
        page.locator('[data-testid="stPopover"] button').filter(has_text="Ver").first.click()
        settle(page, 800)
        shot(page, "02_evidencia.png")  # tela inteira: o painel se estende sobre a barra lateral
        page.keyboard.press("Escape")
        settle(page, 400)

        # 3. teste do validador: resposta adversarial bloqueada + motivos
        page.locator('[data-testid="stSidebar"] button').filter(has_text="Testar o validador").first.click()
        settle(page)
        page.get_by_role("tab", name=re.compile("Visão geral")).click()
        settle(page, 500)
        shot(page, "03_bloqueio.png", main_clip(page))

        # 4. Open Finance expirado: indicadores indisponíveis e meses sem visibilidade
        page.set_viewport_size({"width": 1440, "height": 1500})
        open_case(page, "CASE_0002")
        shot(page, "04_indisponivel.png", main_clip(page, ".cs"))

        # 5. conversa e decisão com nota maliciosa exibida como texto
        page.set_viewport_size({"width": 1440, "height": 1250})
        open_case(page, "CASE_0003")
        page.get_by_role("tab", name=re.compile("Conversa")).click()
        settle(page, 600)
        page.get_by_text(re.compile("Notas do CRM")).click()
        settle(page, 600)
        shot(page, "05_conversa.png", main_clip(page, ".cs"))

        # 6. painel de governança (papel de risco)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("combobox", name="Colaborador").click()
        page.keyboard.type("Sérgio")
        page.keyboard.press("Enter")
        page.wait_for_selector("text=Governança da IA", timeout=60_000)
        settle(page)
        shot(page, "06_governanca.png", main_clip(page))
        browser.close()


if __name__ == "__main__":
    main()
