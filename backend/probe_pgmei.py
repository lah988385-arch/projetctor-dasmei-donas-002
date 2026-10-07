"""Sonda de viabilidade: abre o PGMEI real e extrai dados do hCaptcha."""
import asyncio, os, subprocess, json
from playwright.async_api import async_playwright

BASE = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

def display():
    if not os.path.exists("/tmp/.X11-unix/X99"):
        subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = ":99"

async def main():
    display()
    await asyncio.sleep(1.5)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled", "--lang=pt-BR"],
            ignore_default_args=["--enable-automation"],
        )
        ctx = await browser.new_context(viewport={"width":1000,"height":760}, user_agent=UA,
                                        locale="pt-BR", timezone_id="America/Sao_Paulo")
        page = await ctx.new_page()
        try:
            resp = await page.goto(f"{BASE}/Identificacao", wait_until="domcontentloaded", timeout=45000)
            print("STATUS:", resp.status if resp else None)
            await page.wait_for_timeout(5000)
            info = await page.evaluate("""() => {
                const out = {sitekeys: [], iframes: [], has_hcaptcha_script: false, hcaptcha_textarea: false, cnpj_field: false};
                document.querySelectorAll('[data-sitekey]').forEach(e => out.sitekeys.push(e.getAttribute('data-sitekey')));
                document.querySelectorAll('iframe').forEach(f => { if ((f.src||'').includes('hcaptcha')) out.iframes.push(f.src); });
                out.has_hcaptcha_script = !!document.querySelector('script[src*="hcaptcha"]');
                out.hcaptcha_textarea = !!document.querySelector('textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]');
                out.cnpj_field = !!document.querySelector('#cnpj');
                const m = (document.documentElement.outerHTML.match(/sitekey['\"]?\\s*[:=]\\s*['\"]([0-9a-f-]{20,})/i));
                if (m) out.sitekey_in_html = m[1];
                return out;
            }""")
            print("INFO:", json.dumps(info, indent=2))
            await page.screenshot(path="/tmp/pgmei_probe.png")
            print("screenshot saved")
        except Exception as e:
            print("ERRO:", repr(e))
        finally:
            await ctx.close(); await browser.close()

asyncio.run(main())
