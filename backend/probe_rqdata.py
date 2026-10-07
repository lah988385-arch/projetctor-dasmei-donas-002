"""Captura TODO o tráfego do hCaptcha para achar rqdata / entender o modo."""
import asyncio, os, subprocess, json
from playwright.async_api import async_playwright

BASE = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app"
URL = f"{BASE}/Identificacao"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

def display():
    if not os.path.exists("/tmp/.X11-unix/X99"):
        subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = ":99"

async def main():
    display(); await asyncio.sleep(1.5)
    reqs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled","--lang=pt-BR"],
            ignore_default_args=["--enable-automation"])
        ctx = await browser.new_context(viewport={"width":1000,"height":760}, user_agent=UA,
                                        locale="pt-BR", timezone_id="America/Sao_Paulo")
        page = await ctx.new_page()

        def on_request(req):
            if "hcaptcha.com" in req.url:
                entry = {"m": req.method, "url": req.url[:140]}
                try:
                    pd = req.post_data
                    if pd and ("rqdata" in pd or "getcaptcha" in req.url):
                        entry["body"] = pd[:800]
                except Exception: pass
                reqs.append(entry)
        page.on("request", on_request)

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            await page.fill("#cnpj", "")
            await page.type("#cnpj", "11222333000181", delay=50)
            # clica Continuar para disparar o execute do invisible
            btn = page.locator("button:has-text('Continuar'), form button[type=submit], form input[type=submit]").first
            if await btn.count(): await btn.click()
            await page.wait_for_timeout(7000)
            # procura rqdata via JS: hcaptcha config / window
            js = await page.evaluate(r"""() => {
                const out = {};
                try {
                  const html = document.documentElement.innerHTML;
                  const m = html.match(/rqdata["'\s:=]+([A-Za-z0-9_\-\.]{20,})/);
                  out.rqdata_html = m ? m[1] : null;
                  // varre todas as frames/iframes src por rqdata
                  out.iframe_rqdata = [...document.querySelectorAll('iframe')].map(f=>f.src).filter(s=>/rqdata/.test(s));
                } catch(e){ out.err = String(e); }
                return out;
            }""")
            print("JS:", json.dumps(js)[:400])
        except Exception as e:
            print("ERRO:", repr(e))
        finally:
            await ctx.close(); await browser.close()
    getc = [r for r in reqs if "getcaptcha" in r["url"]]
    print("TOTAL hcaptcha reqs:", len(reqs))
    print("getcaptcha reqs:", json.dumps(getc, indent=2)[:1800])
    # mostra urls unicas
    import collections
    print("endpoints:", list(dict.fromkeys([r['url'].split('?')[0] for r in reqs]))[:20])

asyncio.run(main())
