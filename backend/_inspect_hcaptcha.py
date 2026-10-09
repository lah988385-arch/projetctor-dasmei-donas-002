"""Inspeciona a configuracao do hCaptcha do PGMEI (enterprise? rqdata?)."""
import asyncio, os, re, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
from pgmei_sessao import Sessao, BASE

async def main():
    sessao = Sessao("26920383000100")
    try:
        await sessao.abrir()
        page = sessao.page
        info = await page.evaluate(r"""() => {
            const out = {attrs:{}, iframes:[], hasHcaptchaObj:false, renderParams:null, rqdataFound:[]};
            const el = document.querySelector('[data-sitekey]');
            if (el) { for (const a of el.attributes) out.attrs[a.name]=a.value; }
            document.querySelectorAll('iframe[src*=hcaptcha]').forEach(f=>out.iframes.push(f.src));
            out.hasHcaptchaObj = !!window.hcaptcha;
            // procura rqdata em todo HTML/scripts
            const html = document.documentElement.outerHTML;
            const re = /rqdata['"]?\s*[:=]\s*['"]([^'"]{10,})['"]/gi;
            let m; while((m=re.exec(html))) out.rqdataFound.push(m[1].slice(0,60));
            // procura chamadas hcaptcha.render / execute com config
            const re2 = /hcaptcha\.(render|execute)\s*\([^)]{0,400}/gi;
            out.renderCalls = html.match(re2)||[];
            // enterprise markers
            out.enterprise = /enterprise|rqdata|sentry|hsw/i.test(html);
            return out;
        }""")
        print("ATTRS:", json.dumps(info.get("attrs"), ensure_ascii=False))
        print("IFRAMES:", info.get("iframes"))
        print("hasHcaptchaObj:", info.get("hasHcaptchaObj"))
        print("enterprise markers:", info.get("enterprise"))
        print("rqdataFound:", info.get("rqdataFound"))
        print("renderCalls:", info.get("renderCalls"))
        # baixa o bundle hcaptchapgmei pra ver a integracao
        import httpx
        proxy = os.environ.get("PGMEI_PROXY_SERVER")
        async with httpx.AsyncClient(proxy=proxy, timeout=30, verify=True) as c:
            # tenta achar a url do bundle
            html = await page.content()
            mm = re.search(r'(/SimplesNacional/[^"\']*hcaptchapgmei[^"\']*)', html)
            if mm:
                burl = "https://www8.receita.fazenda.gov.br"+mm.group(1)
                r = await c.get(burl)
                txt = r.text
                print("=== BUNDLE hcaptchapgmei (primeiros 1500 chars) ===")
                print(txt[:1500])
    finally:
        await sessao.fechar()

asyncio.run(main())
