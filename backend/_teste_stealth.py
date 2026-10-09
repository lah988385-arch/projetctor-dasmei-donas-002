"""Teste: navegador STEALTH no IP brasileiro, hCaptcha PASSIVO (sem 2Captcha)."""
import asyncio, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from pgmei_sessao import _garantir_display, BASE

CNPJ = os.environ.get("TESTE_CNPJ", "20851995000101")


def log(*a): print("[STEALTH]", *a, flush=True)


async def main():
    _garantir_display()
    await asyncio.sleep(1)
    proxy = {"server": os.environ["PGMEI_PROXY_SERVER"],
             "username": os.environ["PGMEI_PROXY_USER"],
             "password": os.environ["PGMEI_PROXY_PASS"]}
    stealth = None
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False, proxy=proxy,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled", "--lang=pt-BR"],
            ignore_default_args=["--enable-automation"],
        )
        ctx = await browser.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo",
                                        viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        await stealth_async(page)
        errs = []
        page.on("console", lambda m: errs.append(f"{m.type}:{m.text}"[:160]) if m.type in ("error", "warning") else None)

        log("goto Identificacao (IP BR, stealth)...")
        await page.goto(f"{BASE}/Identificacao", wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(2500)
        log("tem campo #cnpj?", await page.locator("#cnpj").count())
        await page.locator("#cnpj").click()
        await page.keyboard.type(CNPJ, delay=120)
        await page.wait_for_timeout(1000)

        log("clicando Continuar (hCaptcha invisivel roda sozinho)...")
        btn = page.locator("button:has-text('Continuar'), form button[type=submit]").first
        await btn.click()
        # espera navegacao / resultado
        for i in range(20):
            await page.wait_for_timeout(1500)
            url = page.url
            tem_cnpj = await page.locator("#cnpj").count()
            if "Identificacao" not in url or tem_cnpj == 0:
                break
        url = page.url
        aut5 = await page.locator("#cnpj").count() == 0
        body = " ".join((await page.inner_text("body")).split())
        robo = ("Comportamento de Rob" in body) or ("13896" in body)
        log("URL final:", url)
        log("AUTENTICADO (saiu da identificacao)?", aut5)
        log("ROBO/13896?", robo)
        # token gerado?
        tok = await page.evaluate("() => { const t=document.querySelector('textarea[name=h-captcha-response]'); return t? t.value.length : -1; }")
        log("tamanho do h-captcha-response gerado pelo browser:", tok)
        log("console errors (hsw?):")
        for e in [x for x in errs if "hsw" in x.lower() or "eval" in x.lower() or "captcha" in x.lower()][:6]:
            log("   ", e)
        await page.screenshot(path="/app/backend/_stealth_result.jpg", type="jpeg", quality=55, full_page=False)
        if aut5 and not robo:
            log(">>> SUCESSO! hCaptcha passou PASSIVO sem 2Captcha. <<<")
            log("trecho body:", body[:300])
        await browser.close()


asyncio.run(main())
