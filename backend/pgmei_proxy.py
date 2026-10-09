"""Proxy reverso do PGMEI da Receita.

Espelha https://www8.receita.fazenda.gov.br/... sob o prefixo /api/r/ do nosso
domínio. O usuário acessa a tela do PGMEI pelo NOSSO site, digita o CNPJ e
resolve o hCaptcha NO PRÓPRIO NAVEGADOR dele (o token é dele, não de bot).
Encaminhamos tudo para a Receita, reescrevendo o domínio e os links para
permanecerem dentro do proxy, e repassamos os cookies de sessão nos dois sentidos.
"""
import re
import httpx
from fastapi import Request
from starlette.responses import Response

RECEITA = "https://www8.receita.fazenda.gov.br"
PREFIXO = "/api/r"


def _proxy_url():
    """Proxy brasileiro (VPS) para a Receita ver um IP do Brasil. Lê do ambiente."""
    import os
    server = os.environ.get("PROXY_SERVER", "").strip()
    if not server:
        return None
    if "://" in server:
        server = server.split("://", 1)[1]
    user = os.environ.get("PROXY_USER", "").strip()
    pwd = os.environ.get("PROXY_PASS", "").strip()
    tipo = os.environ.get("PROXY_TYPE", "http").strip() or "http"
    if user:
        return f"{tipo}://{user}:{pwd}@{server}"
    return f"{tipo}://{server}"

# tipos de conteúdo que reescrevemos (texto)
_TEXTO = ("text/html", "javascript", "ecmascript", "text/css", "application/json", "text/xml", "application/xml")

_HEADERS_TIRAR = {"host", "content-length", "accept-encoding", "connection"}
_RESP_TIRAR = {"content-encoding", "content-length", "transfer-encoding", "connection",
               "content-security-policy", "content-security-policy-report-only",
               "x-frame-options", "strict-transport-security"}


def _reescrever(texto: str) -> str:
    texto = texto.replace(RECEITA, PREFIXO)
    # URLs root-relative em atributos (src/href/action) — só uma barra (evita // externas)
    texto = re.sub(r'(src|href|action|data-url|formaction)="/(?!/)', rf'\1="{PREFIXO}/', texto)
    texto = re.sub(r"(src|href|action|data-url|formaction)='/(?!/)", rf"\1='{PREFIXO}/", texto)
    # strings de caminho usadas em JS
    texto = texto.replace('"/SimplesNacional/', f'"{PREFIXO}/SimplesNacional/')
    texto = texto.replace("'/SimplesNacional/", f"'{PREFIXO}/SimplesNacional/")
    texto = texto.replace('url(/', f'url({PREFIXO}/')
    return texto


def _reescrever_cookie(sc: str) -> str:
    # remove Domain=...; e força Path=/ para o cookie valer no nosso host/proxy
    partes = [p.strip() for p in sc.split(";")]
    out = []
    tem_path = False
    for p in partes:
        low = p.lower()
        if low.startswith("domain="):
            continue
        if low.startswith("path="):
            out.append("Path=/")
            tem_path = True
            continue
        if low in ("secure", "httponly") or low.startswith("samesite="):
            # mantém secure/httponly; samesite=None exige secure (ok, estamos em https)
            out.append(p)
            continue
        out.append(p)
    if not tem_path:
        out.append("Path=/")
    return "; ".join(out)


def registrar(app):
    @app.api_route("/api/r/{path:path}", methods=["GET", "POST", "HEAD"])
    async def proxy(path: str, request: Request):
        url = f"{RECEITA}/{path}"
        if request.url.query:
            url += "?" + request.url.query

        headers = {k: v for k, v in request.headers.items() if k.lower() not in _HEADERS_TIRAR}
        # referer/origin coerentes com a Receita (ajuda no anti-forgery e no hcaptcha)
        headers["referer"] = url
        headers["origin"] = RECEITA
        body = await request.body()

        async with httpx.AsyncClient(follow_redirects=False, timeout=45.0, verify=True,
                                     proxy=_proxy_url()) as cli:
            r = await cli.request(request.method, url, headers=headers,
                                  content=body, cookies=request.cookies)

        ctype = r.headers.get("content-type", "")
        content = r.content
        if any(t in ctype for t in _TEXTO):
            try:
                texto = content.decode(r.encoding or "utf-8", errors="ignore")
                content = _reescrever(texto).encode("utf-8")
                if "charset=" in ctype:
                    ctype = re.sub(r"charset=[^;]+", "charset=utf-8", ctype, flags=re.I)
                else:
                    ctype = ctype + "; charset=utf-8"
            except Exception:
                pass

        resp = Response(content=content, status_code=r.status_code)
        for k, v in r.headers.items():
            kl = k.lower()
            if kl in _RESP_TIRAR or kl == "set-cookie":
                continue
            if kl == "location":
                v = v.replace(RECEITA, PREFIXO)
                if v.startswith("/") and not v.startswith(PREFIXO):
                    v = PREFIXO + v
                resp.headers["location"] = v
                continue
            resp.headers[k] = v
        resp.headers["content-type"] = ctype or "application/octet-stream"
        # evita cache do documento HTML (impede servir página antiga/bloqueada)
        if "text/html" in ctype:
            resp.headers["cache-control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["pragma"] = "no-cache"
        # repassa cookies da Receita, reescritos para o nosso host
        try:
            for sc in r.headers.get_list("set-cookie"):
                resp.raw_headers.append((b"set-cookie", _reescrever_cookie(sc).encode("latin-1")))
        except Exception:
            pass
        return resp
