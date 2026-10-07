"""Resolução de hCaptcha via 2Captcha (JSON API: createTask / getTaskResult).

Usado pelo motor de sessão do servidor para resolver o hCaptcha invisible do
PGMEI automaticamente. A chave vem de TWOCAPTCHA_API_KEY no ambiente.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TWOCAPTCHA_BASE = "https://api.2captcha.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class CaptchaError(Exception):
    pass


def _chave() -> str:
    chave = os.environ.get("TWOCAPTCHA_API_KEY", "").strip()
    if not chave:
        raise CaptchaError("TWOCAPTCHA_API_KEY ausente no ambiente.")
    return chave


async def saldo() -> float:
    async with httpx.AsyncClient(timeout=20) as cli:
        data = await _post_json(cli, f"{TWOCAPTCHA_BASE}/getBalance", {"clientKey": _chave()})
    if data.get("errorId"):
        raise CaptchaError(data.get("errorDescription") or "Falha ao consultar saldo.")
    return float(data.get("balance", 0))

def proxy_para_playwright() -> Optional[dict]:
    """Retorna o proxy no formato que o Playwright espera, ou None."""
    p = _proxy_ambiente()
    if not p:
        return None
    cfg = {"server": f"{p['type']}://{p['host']}:{p['port']}"}
    if p["user"]:
        cfg["username"] = p["user"]
        cfg["password"] = p["pass"]
    return cfg



async def extrair_sitekey(page) -> tuple[Optional[str], bool]:
    """Extrai o sitekey do hCaptcha e se é invisible, a partir da página aberta."""
    info = await page.evaluate("""() => {
        const out = {sitekey: null, invisible: false};
        const el = document.querySelector('[data-sitekey]');
        if (el) out.sitekey = el.getAttribute('data-sitekey');
        document.querySelectorAll('iframe').forEach(f => {
            const s = f.src || '';
            if (s.includes('hcaptcha')) {
                const m = s.match(/sitekey=([0-9a-f-]{20,})/i);
                if (m && !out.sitekey) out.sitekey = m[1];
                if (/size=invisible|checkbox-invisible/.test(s)) out.invisible = true;
            }
        });
        if (!out.sitekey) {
            const m = document.documentElement.outerHTML.match(/sitekey['"]?\\s*[:=]\\s*['"]([0-9a-f-]{20,})/i);
            if (m) out.sitekey = m[1];
        }
        return out;
    }""")
    return info.get("sitekey"), bool(info.get("invisible"))


async def _post_json(cli: httpx.AsyncClient, url: str, payload: dict, tentativas: int = 4) -> dict:
    """POST com retry: o 2Captcha às vezes devolve corpo vazio (Cloudflare)."""
    ultimo = ""
    for _ in range(tentativas):
        try:
            r = await cli.post(url, json=payload)
            texto = (r.text or "").strip()
            if texto:
                return r.json()
            ultimo = "resposta vazia"
        except Exception as exc:  # erro de rede/JSON: tenta de novo
            ultimo = str(exc)
        await asyncio.sleep(2)
    raise CaptchaError(f"2Captcha não respondeu corretamente ({ultimo}).")


def _proxy_ambiente() -> Optional[dict]:
    """Lê proxy residencial do ambiente. Formato: PROXY_SERVER=host:porta, PROXY_USER, PROXY_PASS."""
    server = os.environ.get("PROXY_SERVER", "").strip()
    if not server:
        return None
    if "://" in server:
        server = server.split("://", 1)[1]
    host, _, porta = server.partition(":")
    if not host or not porta:
        return None
    return {
        "host": host,
        "port": int(porta),
        "user": os.environ.get("PROXY_USER", "").strip(),
        "pass": os.environ.get("PROXY_PASS", "").strip(),
        "type": os.environ.get("PROXY_TYPE", "http").strip().lower(),
    }


async def _resolver_uma_vez(cli: httpx.AsyncClient, chave: str, task: dict, timeout_seg: int) -> str:
    criado = await _post_json(cli, f"{TWOCAPTCHA_BASE}/createTask",
                              {"clientKey": chave, "task": task})
    if criado.get("errorId"):
        raise CaptchaError(criado.get("errorDescription") or "Falha ao criar task no 2Captcha.")
    task_id = criado.get("taskId")
    if not task_id:
        raise CaptchaError("2Captcha não retornou taskId.")
    inicio = asyncio.get_event_loop().time()
    await asyncio.sleep(5)
    while True:
        res = await _post_json(cli, f"{TWOCAPTCHA_BASE}/getTaskResult",
                               {"clientKey": chave, "taskId": task_id})
        if res.get("errorId"):
            raise CaptchaError(res.get("errorDescription") or "Falha ao resolver o captcha.")
        if res.get("status") == "ready":
            sol = res.get("solution") or {}
            token = sol.get("token") or sol.get("gRecaptchaResponse")
            if not token:
                raise CaptchaError("2Captcha retornou solução sem token.")
            return token
        if asyncio.get_event_loop().time() - inicio > timeout_seg:
            raise CaptchaError("Tempo esgotado aguardando o 2Captcha.")
        await asyncio.sleep(4)


async def resolver_hcaptcha(website_url: str, website_key: str, invisible: bool = True,
                            timeout_seg: int = 150, tentativas: int = 3) -> str:
    """Resolve o hCaptcha no 2Captcha, com retry (workers às vezes falham).

    Se houver proxy residencial no ambiente, usa HCaptchaTask (proxy) para que o
    captcha seja resolvido pelo MESMO IP que enviará o formulário.
    """
    chave = _chave()
    proxy = _proxy_ambiente()
    task = {
        "type": "HCaptchaTask" if proxy else "HCaptchaTaskProxyless",
        "websiteURL": website_url,
        "websiteKey": website_key,
        "isInvisible": invisible,
        "userAgent": UA,
    }
    if proxy:
        task.update({
            "proxyType": proxy["type"],
            "proxyAddress": proxy["host"],
            "proxyPort": proxy["port"],
            "proxyLogin": proxy["user"],
            "proxyPassword": proxy["pass"],
        })
    async with httpx.AsyncClient(timeout=30) as cli:
        ultimo = ""
        for n in range(tentativas):
            try:
                return await _resolver_uma_vez(cli, chave, task, timeout_seg)
            except CaptchaError as exc:
                ultimo = str(exc)
                logger.warning("2Captcha tentativa %s/%s falhou: %s", n + 1, tentativas, ultimo)
        raise CaptchaError(f"hCaptcha não resolvido após {tentativas} tentativas ({ultimo}).")


async def injetar_token(page, token: str):
    """Injeta o token nos campos h-captcha-response/g-recaptcha-response da página."""
    await page.evaluate("""(token) => {
        document.querySelectorAll('textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]').forEach(t => { t.value = token; });
        const byId = document.querySelector('#h-captcha-response, #g-recaptcha-response');
        if (byId) byId.value = token;
        try {
            const host = document.querySelector('[data-sitekey]');
            const cb = host && host.getAttribute('data-callback');
            if (cb && typeof window[cb] === 'function') window[cb](token);
        } catch (e) {}
    }""", token)
