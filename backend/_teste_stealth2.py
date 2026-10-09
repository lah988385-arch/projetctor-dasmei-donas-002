"""Teste 2: stealth + IP BR, captura a resposta do POST /Continuar e desafio hCaptcha."""
import asyncio, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from pgmei_sessao import _garantir_display, BASE

CNPJ = os.environ.get("TESTE_CNPJ", "20851995000101")
caps = []


def log(*a): print("[ST2]", *a, flush=True)


async def main():
    _garantir_display()
    await asyncio.sleep(1)
    proxy = {"server": os.environ["PGMEI_PROXY_SERVER"],
             "username": os.environ["PGMEI_PROXY_USER"],
             "password": os.environ["PGMEI_PROXY_PASS"]}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False, proxy=proxy,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled", "--lang=pt-BR"],
            ignore_default_args=["--enable-automation"])
        ctx = await browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo",
                                        viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        await stealth_async(page)

        async def on_resp(resp):
            u = resp.url
            if "Continuar" in u or (u.rstrip("/").endswith("Identificacao") and resp.request.method == "POST"):
                try:
                    body = await resp.text()
                except Exception:
                    body = ""
                caps.append((resp.request.method, u, resp.status,
                             ("Comportamento de Rob" in body) or ("13896" in body), len(body), body[:0]))
        page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        log("goto + espera hCaptcha inicializar (8s)...")
        await page.goto(f"{BASE}/Identificacao", wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(8000)
        hc = await page.evaluate("() => typeof hcaptcha !== 'undefined'")
        log("hcaptcha carregado?", hc)

        await page.locator("#cnpj").click()
        await page.keyboard.type(CNPJ, delay=130)
        await page.wait_for_timeout(1500)

        log("clicando Continuar...")
        await page.locator("#continuar").click()

        for i in range(24):
            await page.wait_for_timeout(1500)
            # desafio hCaptcha visivel? (iframe de challenge)
            chal = await page.evaluate("""() => {
                const f=[...document.querySelectorAll('iframe')].find(f=>/hcaptcha.*challenge|frame=challenge/i.test(f.src||''));
                if(!f) return 'nenhum';
                const r=f.getBoundingClientRect(); return (r.width>10&&r.height>10)?'VISIVEL':'oculto';
            }""")
            url = page.url
            saiu = await page.locator("#cnpj").count() == 0
            if caps or saiu or chal == "VISIVEL":
                log(f"  t={i} url_muda={('Identificacao' not in url)} saiu_ident={saiu} desafio={chal} respostas={len(caps)}")
            if saiu and "Identificacao" not in url:
                break
        log("=== RESPOSTAS /Continuar capturadas ===")
        for m, u, st, robo, ln, _ in caps:
            log(f"  {m} {st} robo={robo} len={ln} {u[:70]}")
        body = " ".join((await page.inner_text("body")).split())
        log("URL final:", page.url)
        log("body final (300):", body[:300])
        await page.screenshot(path="/app/backend/_st2.jpg", type="jpeg", quality=55)
        await browser.close()


asyncio.run(main())
