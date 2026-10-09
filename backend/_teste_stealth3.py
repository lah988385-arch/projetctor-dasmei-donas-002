"""Teste 3: preenche CNPJ corretamente, 1 clique, verifica passivo vs desafio."""
import asyncio, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from pgmei_sessao import _garantir_display, BASE
CNPJ = os.environ.get("TESTE_CNPJ", "20851995000101")
def log(*a): print("[ST3]", *a, flush=True)

async def main():
    _garantir_display(); await asyncio.sleep(1)
    proxy = {"server": os.environ["PGMEI_PROXY_SERVER"], "username": os.environ["PGMEI_PROXY_USER"], "password": os.environ["PGMEI_PROXY_PASS"]}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, proxy=proxy,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled","--lang=pt-BR"],
            ignore_default_args=["--enable-automation"])
        ctx = await browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width":1280,"height":900})
        page = await ctx.new_page(); await stealth_async(page)
        await page.goto(f"{BASE}/Identificacao", wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(7000)
        # preenche CNPJ e verifica
        await page.locator("#cnpj").click()
        await page.keyboard.type(CNPJ, delay=140)
        val = await page.locator("#cnpj").input_value()
        dig = "".join(c for c in val if c.isdigit())
        log("valor no campo:", repr(val), "digitos:", dig, "ok?", dig == CNPJ)
        if dig != CNPJ:
            await page.locator("#cnpj").fill(CNPJ)
            val = await page.locator("#cnpj").input_value(); log("apos fill:", repr(val))
        await page.wait_for_timeout(1000)
        log("clique unico em Continuar...")
        await page.locator("#continuar").click()
        resultado = "indefinido"
        for i in range(20):
            await page.wait_for_timeout(1500)
            saiu = await page.locator("#cnpj").count() == 0
            chal = await page.evaluate("""()=>{const f=[...document.querySelectorAll('iframe')].find(f=>/hcaptcha.*(challenge|checkbox)/i.test(f.src||''));if(!f)return 'nenhum';const r=f.getBoundingClientRect();return (r.width>30&&r.height>30)?'DESAFIO_VISIVEL':'oculto';}""")
            url = page.url
            body = " ".join((await page.inner_text("body")).split())
            robo = ("Comportamento de Rob" in body) or ("13896" in body)
            if saiu and "Identificacao" not in url:
                resultado = "AUTENTICOU (passou!)"; break
            if robo:
                resultado = "ROBO"; break
            if chal == "DESAFIO_VISIVEL":
                resultado = "DESAFIO_VISIVEL (precisa resolver imagens)"
            log(f" t={i} saiu={saiu} url_mudou={'Identificacao' not in url} desafio={chal} robo={robo}")
        log("RESULTADO:", resultado)
        log("URL final:", page.url)
        log("body (260):", (" ".join((await page.inner_text('body')).split()))[:260])
        await page.screenshot(path="/app/backend/_st3.jpg", type="jpeg", quality=55)
        await browser.close()
asyncio.run(main())
