"""Fluxo 100% servidor: curl_cffi (fingerprint Chrome) + 2Captcha + proxy BR.
GET Identificacao -> resolve hCaptcha -> POST Continuar -> ve resultado."""
import os, re, asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import captcha_solver
from curl_cffi import requests as creq

PROXY = f"http://{os.environ['PROXY_USER']}:{os.environ['PROXY_PASS']}@{os.environ['PROXY_SERVER']}"
PROXIES = {"http": PROXY, "https": PROXY}
BASE = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app"
IDENT = BASE + "/Identificacao"
CONT = BASE + "/Identificacao/Continuar"
CNPJ = os.environ.get("TESTE_CNPJ", "26920383000100")


def log(*a): print("[FLOW]", *a, flush=True)


async def main():
    s = creq.Session(impersonate="chrome", proxies=PROXIES, timeout=45)
    log("1) GET Identificacao pelo IP BR...")
    r = s.get(IDENT)
    log("   HTTP", r.status_code, "| robo?", "Comportamento de Rob" in r.text)
    tok = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', r.text)
    sk = re.search(r'data-sitekey="([^"]+)"', r.text)
    log("   antiforgery:", (tok.group(1)[:20]+"...") if tok else None)
    log("   sitekey:", sk.group(1) if sk else None)
    log("   cookies:", list(s.cookies.keys()))
    if not (tok and sk):
        log("ERRO: faltou token/sitekey"); return

    log("2) resolvendo hCaptcha invisible via 2Captcha (proxy BR)... 20-90s")
    token = await captcha_solver.resolver_hcaptcha(IDENT, sk.group(1), True)
    log("   token len:", len(token))

    log("3) POST Continuar com cnpj + antiforgery + h-captcha-response...")
    data = {
        "__RequestVerificationToken": tok.group(1),
        "cnpj": CNPJ,
        "h-captcha-response": token,
        "g-recaptcha-response": token,
    }
    r2 = s.post(CONT, data=data, headers={"Referer": IDENT, "Origin": "https://www8.receita.fazenda.gov.br"},
                allow_redirects=True)
    txt = r2.text
    log("   HTTP", r2.status_code, "| URL final:", r2.url)
    log("   robo/13896?", ("Comportamento de Rob" in txt) or ("13896" in txt))
    # indicadores de sucesso
    low = txt.lower()
    for kw in ["apura", "benefici", "razão social", "razao social", "nome empresarial", "período", "periodo", "das", "gerar", "pagamento"]:
        if kw in low:
            log("   >> encontrou termo de sucesso:", kw)
    Path("/app/backend/_continuar_result.html").write_text(txt, encoding="utf-8")
    log("   salvo _continuar_result.html (", len(txt), "chars )")
    # mostra titulo/mensagens
    tt = re.search(r"<title>(.*?)</title>", txt, re.I|re.S)
    log("   <title>:", (tt.group(1).strip()[:80]) if tt else None)
    for m in re.findall(r'(alert[^>]*>[\s\S]{0,160}?<|toastr[\s\S]{0,120})', txt)[:5]:
        log("   msg:", re.sub(r"\s+"," ", m)[:160])


asyncio.run(main())
