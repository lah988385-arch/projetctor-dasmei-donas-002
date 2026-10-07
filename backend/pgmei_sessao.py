"""Sessão de navegador no servidor para o usuário resolver o hCaptcha do PGMEI.

O site da Receita não pode ser embutido em iframe (x-frame-options: SAMEORIGIN) e o
cookie de sessão é HttpOnly, então o navegador roda aqui: o front recebe prints da
tela e devolve cliques/teclas. Depois de autenticado, a sessão é reaproveitada para
varrer vários anos-calendário.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from playwright.async_api import async_playwright

from pgmei_import import parse_emissao

logger = logging.getLogger(__name__)

BASE = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app"
VIEWPORT = {"width": 1000, "height": 760}
OCIOSA_SEGUNDOS = 600  # 10 min; a sessão da Receita expira por volta de 30 min
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
DISPLAY = ":99"

# o hCaptcha recusa navegador headless ("Comportamento de Robô"), então o Chromium
# roda em modo gráfico dentro de um display virtual
ANTI_DETECCAO = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR', 'pt', 'en-US']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""


def _so_digitos(valor: str) -> str:
    return "".join(c for c in (valor or "") if c.isdigit())


def _garantir_display():
    """Sobe um Xvfb em :99 se ainda não houver display virtual."""
    if os.path.exists("/tmp/.X11-unix/X99"):
        os.environ["DISPLAY"] = DISPLAY
        return
    subprocess.Popen(["Xvfb", DISPLAY, "-screen", "0", "1280x1024x24", "-nolisten", "tcp"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.environ["DISPLAY"] = DISPLAY



async def _garantir_chromium(pw):
    """Reinstala o Chromium se o pod subiu sem o cache do Playwright."""
    try:
        if os.path.exists(pw.chromium.executable_path):
            return
    except Exception:
        pass
    logger.info("baixando o Chromium do Playwright")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "playwright", "install", "chromium",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await asyncio.wait_for(proc.wait(), timeout=420)


class SessaoExpirada(Exception):
    pass


class Sessao:
    def __init__(self, cnpj: str):
        self.id = uuid.uuid4().hex[:12]
        self.cnpj = cnpj
        self.estado = "abrindo"
        self.mensagem = ""
        self.criada_em = datetime.now(timezone.utc)
        self.ultimo_uso = self.criada_em
        self.lock = asyncio.Lock()
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    def tocar(self):
        self.ultimo_uso = datetime.now(timezone.utc)

    @property
    def ociosa_por(self) -> float:
        return (datetime.now(timezone.utc) - self.ultimo_uso).total_seconds()

    async def abrir(self):
        _garantir_display()
        await asyncio.sleep(1.0)
        self._pw = await async_playwright().start()
        await _garantir_chromium(self._pw)
        proxy = None
        if os.environ.get("PGMEI_PROXY_SERVER"):
            proxy = {"server": os.environ["PGMEI_PROXY_SERVER"]}
            if os.environ.get("PGMEI_PROXY_USER"):
                proxy["username"] = os.environ["PGMEI_PROXY_USER"]
                proxy["password"] = os.environ.get("PGMEI_PROXY_PASS", "")
        self._browser = await self._pw.chromium.launch(
            headless=False,
            proxy=proxy,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--start-maximized",
                  "--disable-blink-features=AutomationControlled",
                  "--disable-infobars", "--lang=pt-BR"],
            ignore_default_args=["--enable-automation"],
        )
        self._context = await self._browser.new_context(
            viewport=VIEWPORT, user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo",
        )
        await self._context.add_init_script(ANTI_DETECCAO)
        self.page = await self._context.new_page()
        await self.page.goto(f"{BASE}/Identificacao", wait_until="domcontentloaded", timeout=45000)
        await self._digitar_cnpj()
        self.estado = "aguardando_captcha"
        self.mensagem = "Resolva o captcha na tela e clique em Continuar."
        self.tocar()

    async def _digitar_cnpj(self):
        """Digita o CNPJ como uma pessoa: move o mouse, clica no campo e digita com atraso."""
        try:
            campo = self.page.locator("#cnpj")
            await campo.wait_for(timeout=10000)
            await campo.click()
            await self.page.keyboard.press("Control+a")
            await self.page.keyboard.press("Home")
            await self.page.keyboard.type(self.cnpj, delay=110)
            if _so_digitos(await campo.input_value()) != self.cnpj:
                await campo.fill("")
                await campo.type(self.cnpj, delay=60)
        except Exception:
            logger.warning("não foi possível preencher o CNPJ automaticamente")

    async def fechar(self):
        self.estado = "encerrada"
        for alvo in (self._context, self._browser):
            try:
                if alvo:
                    await alvo.close()
            except Exception:
                pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        self.page = None

    async def tela(self) -> bytes:
        return await self.page.screenshot(type="jpeg", quality=70, full_page=False)

    async def autenticado(self) -> bool:
        """Depois do captacha aceito o site sai da tela de identificação."""
        return await self.page.locator("#cnpj").count() == 0

    async def aviso_site(self) -> str:
        """Mensagem de erro exibida pelo próprio PGMEI (ex.: bloqueio por captcha)."""
        try:
            visiveis = self.page.locator(".alert-danger:visible, .alert-warning:visible, .alert-erro:visible")
            total = await visiveis.count()
            for i in range(total - 1, -1, -1):
                texto = " ".join((await visiveis.nth(i).inner_text()).split())
                if texto and "JavaScript" not in texto:
                    return texto[:220]
            corpo = " ".join((await self.page.inner_text("body")).split())
            achado = re.search(r"\d{3,6}\s*-\s*[^.]{10,160}\.", corpo)
            if achado:
                return achado.group(0)[:220]
        except Exception:
            pass
        return ""

    async def enviar_identificacao(self):
        """Clica em Continuar na tela de identificação e espera a resposta do site."""
        botao = self.page.locator("form button[type=submit], form input[type=submit], button:has-text('Continuar')").first
        if await botao.count():
            caixa = await botao.bounding_box()
            if caixa:
                await self.page.mouse.move(caixa["x"] + caixa["width"] / 2,
                                           caixa["y"] + caixa["height"] / 2, steps=12)
                await self.page.mouse.click(caixa["x"] + caixa["width"] / 2,
                                            caixa["y"] + caixa["height"] / 2, delay=60)
            else:
                await botao.click()
        await self.page.wait_for_timeout(7000)
        self.tocar()

    async def coletar_ano(self, ano: int) -> List[dict]:
        """Navega na emissão do ano-calendário e devolve os períodos da tabela."""
        page = self.page

        if await page.locator("select[name=ano], #ano").count() == 0:
            link = page.locator("a[href*='emissao']").first
            if await link.count():
                await link.click()
                await page.wait_for_load_state("domcontentloaded")

        seletor_ano = "select[name=ano], #ano"
        if await page.locator(seletor_ano).count():
            await page.select_option(seletor_ano, str(ano))
            botao = page.locator("form button[type=submit], form input[type=submit], button:has-text('Ok')").first
            if await botao.count():
                await botao.click()
                await page.wait_for_load_state("domcontentloaded")

        try:
            await page.wait_for_selector("tr.pa", timeout=15000)
        except Exception:
            return []
        return parse_emissao(await page.content(), ano)


class GerenciadorSessoes:
    """Mantém no máximo uma sessão ativa (Chromium consome ~400 MB)."""

    def __init__(self):
        self._sessoes: Dict[str, Sessao] = {}
        self._lock = asyncio.Lock()

    async def abrir(self, cnpj: str) -> Sessao:
        async with self._lock:
            await self._limpar_ociosas()
            if self._sessoes:
                atual = next(iter(self._sessoes.values()))
                await atual.fechar()
                self._sessoes.pop(atual.id, None)
            sessao = Sessao(cnpj)
            self._sessoes[sessao.id] = sessao
        try:
            await sessao.abrir()
        except Exception as exc:
            sessao.estado = "erro"
            sessao.mensagem = f"Não foi possível abrir o PGMEI: {exc}"
            await sessao.fechar()
            self._sessoes.pop(sessao.id, None)
            raise
        return sessao

    def obter(self, sessao_id: str) -> Sessao:
        sessao = self._sessoes.get(sessao_id)
        if not sessao or sessao.estado == "encerrada":
            raise SessaoExpirada("Sessão encerrada ou expirada. Abra uma nova.")
        if sessao.ociosa_por > OCIOSA_SEGUNDOS:
            raise SessaoExpirada("Sessão expirada por inatividade. Abra uma nova.")
        sessao.tocar()
        return sessao

    async def encerrar(self, sessao_id: str):
        sessao = self._sessoes.pop(sessao_id, None)
        if sessao:
            await sessao.fechar()

    async def _limpar_ociosas(self):
        for sid, sessao in list(self._sessoes.items()):
            if sessao.ociosa_por > OCIOSA_SEGUNDOS:
                await sessao.fechar()
                self._sessoes.pop(sid, None)

    async def encerrar_todas(self):
        for sid in list(self._sessoes):
            await self.encerrar(sid)


gerenciador = GerenciadorSessoes()
