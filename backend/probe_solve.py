"""Teste ao vivo: resolve o hCaptcha do PGMEI via CapSolver e tenta passar da identificação."""
import asyncio, os, subprocess
from dotenv import load_dotenv
from pathlib import Path
from playwright.async_api import async_playwright

load_dotenv(Path(__file__).parent / ".env")
import captcha_solver as cs

BASE = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app"
URL = f"{BASE}/Identificacao"
UA = cs.UA
CNPJ = os.environ.get("TESTE_CNPJ", "11222333000181")

def display():
    if not os.path.exists("/tmp/.X11-unix/X99"):
        subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = ":99"

async def main():
    display()
    await asyncio.sleep(1.5)
    print("saldo capsolver:", await cs.saldo())
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled", "--lang=pt-BR"],
            ignore_default_args=["--enable-automation"])
        proxy_cfg = cs.proxy_para_playwright()
        print("proxy navegador:", proxy_cfg["server"] if proxy_cfg else "NENHUM (direto)")
        ctx_kwargs = dict(viewport={"width":1000,"height":760}, user_agent=UA,
                          locale="pt-BR", timezone_id="America/Sao_Paulo")
        if proxy_cfg:
            ctx_kwargs["proxy"] = proxy_cfg
        ctx = await browser.new_context(**ctx_kwargs)
        page = await ctx.new_page()
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)
            # preenche CNPJ
            await page.fill("#cnpj", "")
            await page.type("#cnpj", CNPJ, delay=80)
            sitekey, invisible = await cs.extrair_sitekey(page)
            print("sitekey:", sitekey, "| invisible:", invisible)
            print("resolvendo no 2captcha...")
            token = await cs.resolver_hcaptcha(URL, sitekey, invisible)
            print("token recebido (len):", len(token))
            # re-garante o CNPJ (o campo pode ter sido limpo durante a espera)
            val = await page.eval_on_selector("#cnpj", "e => e.value") if await page.locator("#cnpj").count() else ""
            print("cnpj no campo antes do submit:", val)
            if "".join(c for c in val if c.isdigit()) != CNPJ and await page.locator("#cnpj").count():
                await page.fill("#cnpj", "")
                await page.type("#cnpj", CNPJ, delay=60)
            await cs.injetar_token(page, token)
            # usa o form real + callback do site (onSubmit), preservando __RequestVerificationToken
            metodo = await page.evaluate("""(token) => {
                const form = document.querySelector('#identificacao') || document.querySelector('form');
                let ta = form.querySelector('textarea[name="h-captcha-response"]');
                if (!ta) { ta = document.createElement('textarea'); ta.name='h-captcha-response'; ta.style.display='none'; form.appendChild(ta); }
                ta.value = token;
                let ga = form.querySelector('textarea[name="g-recaptcha-response"]');
                if (!ga) { ga = document.createElement('textarea'); ga.name='g-recaptcha-response'; ga.style.display='none'; form.appendChild(ga); }
                ga.value = token;
                if (typeof window.onSubmit === 'function') { window.onSubmit(token); return 'onSubmit'; }
                form.submit(); return 'form.submit';
            }""", token)
            print("metodo submit:", metodo)
            await page.wait_for_timeout(9000)
            tem_cnpj = await page.locator("#cnpj").count()
            corpo = (await page.inner_text("body"))[:600]
            print("ainda na tela de CNPJ?", bool(tem_cnpj))
            print("URL atual:", page.url)
            print("--- trecho da pagina ---")
            print(" ".join(corpo.split()))
            await page.screenshot(path="/tmp/pgmei_apos_captcha.png")
        except Exception as e:
            print("ERRO:", repr(e))
        finally:
            await ctx.close(); await browser.close()

asyncio.run(main())
