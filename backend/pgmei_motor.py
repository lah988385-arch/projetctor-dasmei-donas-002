"""Motor de consulta real do PGMEI reaproveitando a sessão autenticada (cookie).

Ideia (modelo descrito pelo usuário): um humano loga no gov.br uma vez (ex.: toda
segunda) e o cookie da sessão autenticada é salvo no painel. O servidor reaproveita
esse cookie como se fosse uma "API":
  - keep-alive: um ping periódico mantém a sessão viva durante a semana;
  - fila: as consultas são processadas uma a uma, com espaçamento, para não
    parecer robô nem derrubar a sessão;
  - cache: o resultado vai para `apuracoes_importadas` (validade de 7 dias).

NÃO há burla de captcha aqui: quem fez o login foi o usuário. Quando a Receita
derruba a sessão (semanalmente), o motor detecta a tela de login e pausa, marcando
a sessão como expirada para o usuário renovar.

IMPORTANTE: o formato exato das requisições autenticadas (`_buscar`) precisa ser
afinado com um cookie REAL — só é possível validar ponta a ponta quando o usuário
enviar uma sessão de verdade pela extensão.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

import httpx

from pgmei_import import parse_emissao

logger = logging.getLogger(__name__)

BASE = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# espaçamento entre consultas (anti-rajada). 5 s = ~12/min, aguenta o pico de 20/min
ESPACO_SEG = float(os.environ.get("MOTOR_ESPACO_SEG", "5"))
KEEPALIVE_SEG = int(os.environ.get("MOTOR_KEEPALIVE_SEG", "600"))  # 10 min
VALIDADE_DIAS = 7

# marcadores que indicam que a Receita devolveu a tela de login (sessão morta)
MARCAS_LOGIN = ("h-captcha", "hcaptcha", 'id="cnpj"', "Identificação do Contribuinte",
                "Não sou um robô", "sso.acesso.gov.br")


class MotorConsulta:
    def __init__(self):
        self.db = None
        self.fila: asyncio.Queue = asyncio.Queue()
        self._pendentes: set = set()
        self._worker: Optional[asyncio.Task] = None
        self._keepalive: Optional[asyncio.Task] = None
        self.sessao_viva: Optional[bool] = None
        self.ultima_consulta_em: Optional[str] = None
        self.ultimo_erro: Optional[str] = None
        self.total_ok = 0
        self.total_falhas = 0

    # ------------------------------------------------------------------
    def iniciar(self, db):
        self.db = db
        if not self._worker or self._worker.done():
            self._worker = asyncio.create_task(self._rodar_fila())
        # keep-alive no servidor foi desativado: o replay do cookie fora do
        # navegador cai na tela de captcha da Receita. A coleta real é feita
        # pela extensão, dentro do navegador logado do usuário.

    async def _cookie(self) -> Tuple[Optional[str], Optional[str]]:
        """Retorna (cookie, atualizada_em). cookie=None se ausente ou expirado."""
        doc = await self.db.sessao_govbr.find_one({"_id": "atual"})
        if not doc or not doc.get("cookie"):
            return None, None
        atualizada = doc.get("atualizada_em")
        if atualizada:
            exp = datetime.fromisoformat(atualizada) + timedelta(days=VALIDADE_DIAS)
            if datetime.now(timezone.utc) >= exp:
                return None, atualizada
        return doc["cookie"], atualizada

    # ------------------------------------------------------------------
    async def enfileirar(self, cnpj: str, ano: int) -> str:
        """Coloca a consulta na fila. Retorna em_andamento | sem_sessao."""
        chave = (cnpj, ano)
        if chave in self._pendentes:
            return "em_andamento"
        cookie, _ = await self._cookie()
        if not cookie:
            return "sem_sessao"
        self._pendentes.add(chave)
        await self.fila.put(chave)
        return "em_andamento"

    # ------------------------------------------------------------------
    async def _rodar_fila(self):
        while True:
            cnpj, ano = await self.fila.get()
            try:
                await self._processar(cnpj, ano)
            except Exception as exc:  # nunca derruba o worker
                logger.warning("motor: erro ao processar %s/%s: %s", cnpj, ano, exc)
            finally:
                self._pendentes.discard((cnpj, ano))
                self.fila.task_done()
            await asyncio.sleep(ESPACO_SEG)  # espaçamento anti-rajada

    async def _processar(self, cnpj: str, ano: int):
        chave = {"cnpj": cnpj, "ano": ano}
        cookie, _ = await self._cookie()
        if not cookie:
            self.sessao_viva = False
            await self._falha(chave, "Sessão ausente ou expirada. Renove no painel.")
            return

        periodos, erro = await self._buscar(cookie, cnpj, ano)
        if erro:
            if any(t in erro.lower() for t in ("sessão", "login", "expir")):
                self.sessao_viva = False
            await self._falha(chave, erro)
            return
        if not periodos:
            await self._falha(chave, "Nenhum período de apuração encontrado para o CNPJ/ano.")
            return

        self.sessao_viva = True
        self.total_ok += 1
        self.ultima_consulta_em = datetime.now(timezone.utc).isoformat()
        await self.db.apuracoes_importadas.update_one(
            chave,
            {"$set": {**chave, "periodos": periodos, "origem": "sessao",
                      "importado_em": self.ultima_consulta_em}},
            upsert=True,
        )
        await self.db.tentativas_consulta.delete_one(chave)

    async def _falha(self, chave: dict, motivo: str):
        self.total_falhas += 1
        self.ultimo_erro = motivo[:220]
        await self.db.tentativas_consulta.update_one(
            chave,
            {"$set": {**chave, "em": datetime.now(timezone.utc).isoformat(),
                      "motivo": motivo[:220]}},
            upsert=True,
        )

    # ------------------------------------------------------------------
    def _parece_login(self, html: str) -> bool:
        if not html:
            return False
        return any(m.lower() in html.lower() for m in MARCAS_LOGIN)

    async def _buscar(self, cookie: str, cnpj: str, ano: int):
        """Consulta a emissão do ano reaproveitando o cookie autenticado.

        AFINAR COM COOKIE REAL: o caminho das requisições do PGMEI autenticado
        pode variar (tokens ASP.NET, rota exata). Mantido isolado aqui de
        propósito para ajuste sem tocar no resto do motor.
        """
        headers = {
            "User-Agent": UA,
            "Cookie": cookie,
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
            "Referer": f"{BASE}/identificacao",
        }
        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True,
                                         timeout=30.0) as client:
                # 1) identifica o CNPJ dentro da sessão logada
                await client.post(f"{BASE}/identificacao", data={"cnpj": cnpj})
                # 2) abre a tela de emissão do ano-calendário
                resp = await client.get(f"{BASE}/emissao", params={"ano": ano})
                html = resp.text
                if self._parece_login(html):
                    return None, "Sessão expirada (Receita devolveu a tela de login). Renove no painel."
                periodos = parse_emissao(html, ano)
                return periodos, None
        except Exception as exc:
            return None, f"Falha de rede na consulta: {exc}"

    # ------------------------------------------------------------------
    async def _rodar_keepalive(self):
        while True:
            await asyncio.sleep(KEEPALIVE_SEG)
            cookie, _ = await self._cookie()
            if not cookie:
                self.sessao_viva = False
                continue
            try:
                async with httpx.AsyncClient(
                        headers={"User-Agent": UA, "Cookie": cookie},
                        follow_redirects=True, timeout=20.0) as client:
                    resp = await client.get(f"{BASE}/identificacao")
                    self.sessao_viva = not self._parece_login(resp.text)
            except Exception as exc:
                logger.info("motor keep-alive: %s", exc)

    # ------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "fila": self.fila.qsize(),
            "pendentes": len(self._pendentes),
            "processadas_ok": self.total_ok,
            "falhas": self.total_falhas,
            "sessao_viva": self.sessao_viva,
            "ultima_consulta_em": self.ultima_consulta_em,
            "ultimo_erro": self.ultimo_erro,
            "espaco_segundos": ESPACO_SEG,
            "keepalive_segundos": KEEPALIVE_SEG,
        }


motor = MotorConsulta()
