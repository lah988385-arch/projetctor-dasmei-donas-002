"""Inspeciona o form do PGMEI, o widget hCaptcha e a resposta do checksiteconfig."""
import asyncio, os, subprocess, json
from playwright.async_api import async_playwright

BASE = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app"
URL = f"{BASE}/Identificacao"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

def display():
    if not os.path.exists("/tmp/.X11-unix/X99"):
        subprocess.Popen(["Xvfb",":99","-screen","0","1280x1024x24","-nolisten","tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"]=":99"

async def main():
    display(); await asyncio.sleep(1.5)
    cfg = {}
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False,
            args=["--no-sandbox","--disable-dev-shm-usage","--disable-blink-features=AutomationControlled","--lang=pt-BR"],
            ignore_default_args=["--enable-automation"])
        ctx = await b.new_context(viewport={"width":1000,"height":760}, user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo")
        page = await ctx.new_page()

        async def on_resp(resp):
            if "checksiteconfig" in resp.url:
                try: cfg["checksiteconfig"] = await resp.json()
                except Exception as e: cfg["checksiteconfig_err"] = str(e)
        page.on("response", on_resp)

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4000)
            form = await page.evaluate(r"""() => {
                const f = document.querySelector('#cnpj') ? document.querySelector('#cnpj').closest('form') : document.querySelector('form');
                const btn = document.querySelector("button[type=submit], input[type=submit], button");
                const widget = document.querySelector('[data-sitekey]');
                return {
                    form_action: f ? (f.getAttribute('action')||'') : null,
                    form_method: f ? (f.getAttribute('method')||'') : null,
                    form_onsubmit: f ? !!f.getAttribute('onsubmit') : null,
                    form_html: f ? f.outerHTML.slice(0, 900) : null,
                    btn_html: btn ? btn.outerHTML.slice(0,300) : null,
                    widget_attrs: widget ? widget.outerHTML.slice(0,400) : null,
                    has_hcaptcha_api: !!window.hcaptcha,
                };
            }""")
            print("FORM/WIDGET:", json.dumps(form, ensure_ascii=False, indent=2)[:2000])
        except Exception as e:
            print("ERRO:", repr(e))
        finally:
            await ctx.close(); await b.close()
    print("CHECKSITECONFIG:", json.dumps(cfg, ensure_ascii=False)[:1200])

asyncio.run(main())
