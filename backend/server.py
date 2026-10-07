from fastapi import FastAPI, APIRouter, HTTPException, Response, Body
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import asyncio
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
import uuid
from datetime import datetime, timezone, date, timedelta
import httpx
from das_pdf import (gerar_pdf_das, numero_apuracao, numero_documento,
                     composicao_das, brl, codigo_pix_estudo, qrcode_base64)
from pgmei_import import parse_emissao, resumir
from pgmei_sessao import VIEWPORT, SessaoExpirada, gerenciador
from pgmei_motor import motor
from admin_painel import montar_router as montar_admin_router


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


class IdentificacaoRequest(BaseModel):
    cnpj: str


class IdentificacaoResponse(BaseModel):
    status: str
    valido: bool
    cnpj: str
    mensagem: str


class ConsultaCnpjResponse(BaseModel):
    cnpj: str
    cnpj_formatado: str
    nome: str
    situacao: Optional[str] = None
    uf: Optional[str] = None
    encontrado: bool


class PeriodoApuracao(BaseModel):
    pa: str
    rotulo: str
    apurado: str
    situacao: str
    vencimento: str
    principal: str
    multa: str
    juros: str
    total: str
    data_vencimento: str
    data_acolhimento: str


class ApuracaoResponse(BaseModel):
    cnpj: str
    cnpj_formatado: str
    ano: int
    data_pagamento: str
    data_pagamento_inicio: str
    data_pagamento_fim: str
    periodos: List[PeriodoApuracao]
    origem: str = "mock"
    importado_em: Optional[str] = None
    cache_expira_em: Optional[str] = None
    cache_expirado: bool = False
    dias_restantes: int = 0


class ImportarApuracaoRequest(BaseModel):
    cnpj: str
    ano: int
    html: str


class ImportacaoResumo(BaseModel):
    cnpj: str
    cnpj_formatado: str
    ano: int
    origem: str
    importado_em: Optional[str] = None
    cache_expira_em: Optional[str] = None
    cache_expirado: bool = False
    dias_restantes: int = 0
    total_periodos: int = 0
    em_aberto: List[PeriodoApuracao] = []
    a_vencer: List[PeriodoApuracao] = []
    liquidados: List[PeriodoApuracao] = []
    baixados: List[PeriodoApuracao] = []
    total_em_aberto: float = 0.0
    total_em_aberto_formatado: str = "0,00"


# ---------------------------------------------------------------------------
# CNPJ helpers (estudo)
# ---------------------------------------------------------------------------
def _only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def validar_cnpj(cnpj: str) -> bool:
    """Valida os dígitos verificadores do CNPJ (14 dígitos)."""
    num = _only_digits(cnpj)
    if len(num) != 14:
        return False
    if num == num[0] * 14:  # rejeita sequências repetidas (00000000000000, ...)
        return False

    def calc_dv(base: str, pesos: list[int]) -> int:
        soma = sum(int(d) * p for d, p in zip(base, pesos))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    dv1 = calc_dv(num[:12], pesos1)
    dv2 = calc_dv(num[:12] + str(dv1), pesos2)
    return num[12] == str(dv1) and num[13] == str(dv2)


def formatar_cnpj(cnpj: str) -> str:
    n = _only_digits(cnpj)
    if len(n) != 14:
        return cnpj
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"message": "Hello World"}


@api_router.post("/identificacao", response_model=IdentificacaoResponse)
async def identificacao(payload: IdentificacaoRequest):
    """Valida o CNPJ, registra no banco (estudo) e retorna resposta mock.

    Gancho para, no futuro, plugar a API oficial (Integra Contador / SERPRO).
    """
    cnpj_num = _only_digits(payload.cnpj)
    valido = validar_cnpj(cnpj_num)

    # Registro local apenas para estudo/histórico
    doc = {
        "id": str(uuid.uuid4()),
        "cnpj": cnpj_num,
        "cnpj_formatado": formatar_cnpj(cnpj_num),
        "valido": valido,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await db.identificacoes.insert_one(doc)

    if not valido:
        return IdentificacaoResponse(
            status="erro",
            valido=False,
            cnpj=cnpj_num,
            mensagem="CNPJ inválido. Verifique os dígitos informados.",
        )

    # MOCK: nenhuma consulta à Receita é feita neste ambiente de estudo.
    return IdentificacaoResponse(
        status="ok",
        valido=True,
        cnpj=formatar_cnpj(cnpj_num),
        mensagem="CNPJ recebido com sucesso (ambiente de estudo — sem consulta à Receita).",
    )


@api_router.get("/consulta-cnpj/{cnpj}", response_model=ConsultaCnpjResponse)
async def consulta_cnpj(cnpj: str):
    """Consulta o nome/razão social do contribuinte pelo CNPJ (BrasilAPI, pública).

    Em caso de CNPJ inexistente ou falha, retorna um nome genérico para o fluxo de estudo.
    """
    cnpj_num = _only_digits(cnpj)
    formatado = formatar_cnpj(cnpj_num)
    nome = None
    situacao = None
    uf = None
    encontrado = False

    if validar_cnpj(cnpj_num):
        try:
            async with httpx.AsyncClient(timeout=15) as http_client:
                resp = await http_client.get(
                    f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_num}"
                )
            if resp.status_code == 200:
                data = resp.json()
                nome = (data.get("razao_social") or data.get("nome_fantasia") or "").strip()
                situacao = data.get("descricao_situacao_cadastral")
                uf = data.get("uf")
                encontrado = bool(nome)
        except Exception as exc:  # falha de rede/timeout — segue com fallback
            logger.warning("Falha ao consultar BrasilAPI: %s", exc)

    if not nome:
        nome = "Contribuinte não localizado"

    # Registro local (estudo)
    await db.consultas.insert_one({
        "id": str(uuid.uuid4()),
        "cnpj": cnpj_num,
        "cnpj_formatado": formatado,
        "nome": nome,
        "encontrado": encontrado,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return ConsultaCnpjResponse(
        cnpj=cnpj_num,
        cnpj_formatado=formatado,
        nome=nome,
        situacao=situacao,
        uf=uf,
        encontrado=encontrado,
    )


MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def _vencimento_das(ano: int, mes: int) -> date:
    """Vencimento do DAS: dia 20 do mês seguinte, adiado para o próximo dia útil."""
    ano_venc = ano + 1 if mes == 12 else ano
    mes_venc = 1 if mes == 12 else mes + 1
    d = date(ano_venc, mes_venc, 20)
    # fins de semana e o feriado nacional de 20/11 adiam para o próximo dia útil
    while d.weekday() >= 5 or (d.month == 11 and d.day == 20):
        d += timedelta(days=1)
    return d


CACHE_DIAS = 7


def _validade_cache(importado_em: Optional[str]) -> dict:
    """Dados reais valem 7 dias; depois disso ficam marcados como desatualizados."""
    if not importado_em:
        return {"cache_expira_em": None, "cache_expirado": False, "dias_restantes": 0}
    importado = datetime.fromisoformat(importado_em)
    expira = importado + timedelta(days=CACHE_DIAS)
    restantes = (expira - datetime.now(timezone.utc)).total_seconds() / 86400
    return {
        "cache_expira_em": expira.isoformat(),
        "cache_expirado": restantes <= 0,
        "dias_restantes": max(0, int(restantes // 1 + (1 if restantes % 1 else 0))),
    }


@api_router.get("/apuracao/{cnpj}/{ano}", response_model=ApuracaoResponse)
async def apuracao(cnpj: str, ano: int):
    """Períodos de apuração do ano-calendário.

    Se houver uma importação do HTML real do PGMEI para esse CNPJ/ano, ela é
    usada; caso contrário os períodos são simulados (dados de exemplo).
    """
    cnpj_num = _only_digits(cnpj)
    hoje = datetime.now(timezone.utc).date()
    ultimo_dia = date(hoje.year + (hoje.month == 12), (hoje.month % 12) + 1, 1) - timedelta(days=1)

    importado = await db.apuracoes_importadas.find_one({"cnpj": cnpj_num, "ano": ano})
    if importado and importado.get("periodos"):
        return ApuracaoResponse(
            cnpj=cnpj_num,
            cnpj_formatado=formatar_cnpj(cnpj_num),
            ano=ano,
            data_pagamento=hoje.strftime("%d/%m/%Y"),
            data_pagamento_inicio=hoje.strftime("%d/%m/%Y"),
            data_pagamento_fim=ultimo_dia.strftime("%d/%m/%Y"),
            periodos=[PeriodoApuracao(**p) for p in importado["periodos"]],
            origem="real",
            importado_em=importado.get("importado_em"),
            **_validade_cache(importado.get("importado_em")),
        )

    vencimentos = {mes: _vencimento_das(ano, mes) for mes in range(1, 13)}
    # Os dois últimos PA vencidos são considerados em aberto. O cálculo é GLOBAL
    # (atravessa anos), então anos antigos aparecem integralmente liquidados.
    candidatos = [
        (a, m)
        for a in range(hoje.year - 1, hoje.year + 2)
        for m in range(1, 13)
        if _vencimento_das(a, m) < hoje
    ]
    candidatos.sort(key=lambda am: _vencimento_das(*am), reverse=True)
    devedores = set(candidatos[:2])

    periodos = []
    for mes in range(1, 13):
        venc = vencimentos[mes]
        if venc >= hoje:
            situacao = "A Vencer"
        elif (ano, mes) in devedores:
            situacao = "Devedor"
        else:
            situacao = "Liquidado"

        if situacao == "Liquidado":
            valores = {k: "-" for k in ("principal", "multa", "juros", "total")}
            data_vencimento = data_acolhimento = "-"
        else:
            comp = composicao_das(ano, "", venc, hoje)
            valores = {k: f"R$ {brl(comp[k])}" for k in ("principal", "multa", "juros", "total")}
            data_vencimento = venc.strftime("%d/%m/%Y")
            data_acolhimento = (hoje if situacao == "Devedor" else venc).strftime("%d/%m/%Y")

        periodos.append(PeriodoApuracao(
            pa=f"{ano}{mes:02d}",
            rotulo=f"{MESES_PT[mes - 1]}/{ano}",
            apurado="Sim",
            situacao=situacao,
            vencimento=venc.strftime("%d/%m/%Y"),
            data_vencimento=data_vencimento,
            data_acolhimento=data_acolhimento,
            **valores,
        ))

    return ApuracaoResponse(
        cnpj=cnpj_num,
        cnpj_formatado=formatar_cnpj(cnpj_num),
        ano=ano,
        data_pagamento=hoje.strftime("%d/%m/%Y"),
        data_pagamento_inicio=hoje.strftime("%d/%m/%Y"),
        data_pagamento_fim=ultimo_dia.strftime("%d/%m/%Y"),
        periodos=periodos,
    )


def _resumo_importacao(cnpj_num: str, ano: int, periodos: List[dict],
                       importado_em: Optional[str]) -> ImportacaoResumo:
    agrupado = resumir(periodos)
    return ImportacaoResumo(
        cnpj=cnpj_num,
        cnpj_formatado=formatar_cnpj(cnpj_num),
        ano=ano,
        origem="real" if periodos else "mock",
        importado_em=importado_em,
        total_periodos=len(periodos),
        em_aberto=[PeriodoApuracao(**p) for p in agrupado["em_aberto"]],
        a_vencer=[PeriodoApuracao(**p) for p in agrupado["a_vencer"]],
        liquidados=[PeriodoApuracao(**p) for p in agrupado["liquidados"]],
        baixados=[PeriodoApuracao(**p) for p in agrupado["baixados"]],
        total_em_aberto=agrupado["total_em_aberto"],
        total_em_aberto_formatado=brl(agrupado["total_em_aberto"]),
        **_validade_cache(importado_em),
    )


@api_router.post("/apuracao/importar", response_model=ImportacaoResumo)
async def importar_apuracao(payload: ImportarApuracaoRequest):
    """Importa os períodos reais a partir do HTML da tela de emissão do PGMEI."""
    cnpj_num = _only_digits(payload.cnpj)
    if not validar_cnpj(cnpj_num):
        raise HTTPException(status_code=400, detail="CNPJ inválido.")
    if not (payload.html or "").strip():
        raise HTTPException(status_code=400, detail="Cole o código-fonte da página de emissão.")

    periodos = parse_emissao(payload.html, payload.ano)
    if not periodos:
        raise HTTPException(
            status_code=422,
            detail=("Não encontrei a tabela de períodos de apuração nesse conteúdo. "
                    "Confirme que copiou a página de emissão do PGMEI do ano "
                    f"{payload.ano} (a tela com a lista de meses)."),
        )

    importado_em = datetime.now(timezone.utc).isoformat()
    await db.apuracoes_importadas.update_one(
        {"cnpj": cnpj_num, "ano": payload.ano},
        {"$set": {"cnpj": cnpj_num, "ano": payload.ano, "periodos": periodos,
                  "origem": "html", "importado_em": importado_em}},
        upsert=True,
    )
    return _resumo_importacao(cnpj_num, payload.ano, periodos, importado_em)


@api_router.get("/apuracao/importada/{cnpj}/{ano}", response_model=ImportacaoResumo)
async def apuracao_importada(cnpj: str, ano: int):
    """Situação da importação de dados reais para o CNPJ/ano."""
    cnpj_num = _only_digits(cnpj)
    doc = await db.apuracoes_importadas.find_one({"cnpj": cnpj_num, "ano": ano})
    periodos = doc.get("periodos", []) if doc else []
    return _resumo_importacao(cnpj_num, ano, periodos, doc.get("importado_em") if doc else None)


@api_router.delete("/apuracao/importada/{cnpj}/{ano}", response_model=ImportacaoResumo)
async def remover_apuracao_importada(cnpj: str, ano: int):
    """Descarta os dados importados e volta para os dados de exemplo."""
    cnpj_num = _only_digits(cnpj)
    await db.apuracoes_importadas.delete_one({"cnpj": cnpj_num, "ano": ano})
    return _resumo_importacao(cnpj_num, ano, [], None)


class SessaoAbrirRequest(BaseModel):
    cnpj: str


class SessaoEstado(BaseModel):
    id: str
    cnpj: str
    cnpj_formatado: str
    estado: str
    mensagem: str = ""
    autenticado: bool = False
    aviso_site: str = ""
    largura: int = 1000
    altura: int = 760
    ociosa_por: int = 0


class SessaoCliqueRequest(BaseModel):
    x: float
    y: float


class SessaoTeclaRequest(BaseModel):
    texto: Optional[str] = None
    tecla: Optional[str] = None


class SessaoColetaRequest(BaseModel):
    anos: List[int] = []


class AnoColetado(BaseModel):
    ano: int
    periodos: int = 0
    em_aberto: int = 0
    a_vencer: int = 0
    liquidados: int = 0
    total_em_aberto_formatado: str = "0,00"
    erro: Optional[str] = None


class SessaoColetaResponse(BaseModel):
    cnpj: str
    anos: List[AnoColetado]
    importados: int = 0


async def _estado_sessao(sessao) -> SessaoEstado:
    try:
        autenticado = await sessao.autenticado()
    except Exception:
        autenticado = False
    try:
        aviso = await sessao.aviso_site()
    except Exception:
        aviso = ""
    if autenticado and sessao.estado == "aguardando_captcha":
        sessao.estado = "autenticado"
        sessao.mensagem = "Captcha aceito. Importe os anos-calendário."
    return SessaoEstado(
        id=sessao.id, cnpj=sessao.cnpj, cnpj_formatado=formatar_cnpj(sessao.cnpj),
        estado=sessao.estado, mensagem=sessao.mensagem, autenticado=autenticado,
        aviso_site=aviso,
        largura=VIEWPORT["width"], altura=VIEWPORT["height"], ociosa_por=int(sessao.ociosa_por),
    )


def _pegar_sessao(sessao_id: str):
    try:
        return gerenciador.obter(sessao_id)
    except SessaoExpirada as exc:
        raise HTTPException(status_code=410, detail=str(exc))


@api_router.post("/sessao/abrir", response_model=SessaoEstado)
async def sessao_abrir(payload: SessaoAbrirRequest):
    """Abre o Chromium no servidor já na tela de identificação do PGMEI."""
    cnpj_num = _only_digits(payload.cnpj)
    if not validar_cnpj(cnpj_num):
        raise HTTPException(status_code=400, detail="CNPJ inválido.")
    try:
        sessao = await gerenciador.abrir(cnpj_num)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Não foi possível abrir o PGMEI: {exc}")
    return await _estado_sessao(sessao)


@api_router.get("/sessao/{sessao_id}/estado", response_model=SessaoEstado)
async def sessao_estado(sessao_id: str):
    sessao = _pegar_sessao(sessao_id)
    async with sessao.lock:
        return await _estado_sessao(sessao)


@api_router.get("/sessao/{sessao_id}/tela")
async def sessao_tela(sessao_id: str):
    """Print atual da tela do navegador do servidor."""
    sessao = _pegar_sessao(sessao_id)
    async with sessao.lock:
        try:
            imagem = await sessao.tela()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Falha ao capturar a tela: {exc}")
    return Response(content=imagem, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@api_router.post("/sessao/{sessao_id}/clique", response_model=SessaoEstado)
async def sessao_clique(sessao_id: str, payload: SessaoCliqueRequest):
    sessao = _pegar_sessao(sessao_id)
    async with sessao.lock:
        try:
            await sessao.page.mouse.move(payload.x, payload.y, steps=10)
            await sessao.page.mouse.click(payload.x, payload.y, delay=60)
            await sessao.page.wait_for_timeout(400)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Falha ao clicar: {exc}")
        return await _estado_sessao(sessao)


@api_router.post("/sessao/{sessao_id}/teclar", response_model=SessaoEstado)
async def sessao_teclar(sessao_id: str, payload: SessaoTeclaRequest):
    sessao = _pegar_sessao(sessao_id)
    async with sessao.lock:
        try:
            if payload.texto:
                await sessao.page.keyboard.type(payload.texto, delay=35)
            if payload.tecla:
                await sessao.page.keyboard.press(payload.tecla)
            await sessao.page.wait_for_timeout(250)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Falha ao digitar: {exc}")
        return await _estado_sessao(sessao)


@api_router.post("/sessao/{sessao_id}/coletar", response_model=SessaoColetaResponse)
async def sessao_coletar(sessao_id: str, payload: SessaoColetaRequest):
    """Com a sessão já autenticada, varre os anos pedidos e importa os períodos reais."""
    sessao = _pegar_sessao(sessao_id)
    ano_atual = datetime.now(timezone.utc).year
    anos = sorted({a for a in (payload.anos or range(ano_atual - 5, ano_atual + 1))
                   if 2009 <= a <= ano_atual + 1})

    resultado: List[AnoColetado] = []
    importados = 0
    async with sessao.lock:
        if not await sessao.autenticado():
            raise HTTPException(status_code=409,
                                detail="A sessão ainda está na tela de identificação. Resolva o captcha e clique em Continuar.")
        sessao.estado = "coletando"
        for ano in anos:
            try:
                periodos = await sessao.coletar_ano(ano)
            except Exception as exc:
                resultado.append(AnoColetado(ano=ano, erro=str(exc)[:160]))
                continue
            if not periodos:
                resultado.append(AnoColetado(ano=ano, erro="Nenhum período encontrado."))
                continue
            agrupado = resumir(periodos)
            await db.apuracoes_importadas.update_one(
                {"cnpj": sessao.cnpj, "ano": ano},
                {"$set": {"cnpj": sessao.cnpj, "ano": ano, "periodos": periodos,
                          "origem": "sessao",
                          "importado_em": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
            importados += 1
            resultado.append(AnoColetado(
                ano=ano, periodos=len(periodos),
                em_aberto=len(agrupado["em_aberto"]), a_vencer=len(agrupado["a_vencer"]),
                liquidados=len(agrupado["liquidados"]),
                total_em_aberto_formatado=brl(agrupado["total_em_aberto"]),
            ))
        sessao.estado = "autenticado"
        sessao.mensagem = f"{importados} ano(s) importado(s)."
    return SessaoColetaResponse(cnpj=sessao.cnpj, anos=resultado, importados=importados)


@api_router.post("/sessao/{sessao_id}/preencher-cnpj", response_model=SessaoEstado)
async def sessao_preencher_cnpj(sessao_id: str, payload: SessaoAbrirRequest = None):
    """Repreenche o campo de CNPJ (o PGMEI limpa o campo quando recusa o captcha)."""
    sessao = _pegar_sessao(sessao_id)
    async with sessao.lock:
        await sessao._digitar_cnpj()
        return await _estado_sessao(sessao)


@api_router.post("/sessao/{sessao_id}/fechar")
async def sessao_fechar(sessao_id: str):
    await gerenciador.encerrar(sessao_id)
    return {"encerrada": True}


class ConsultaAutomaticaRequest(BaseModel):
    cnpj: str
    ano: int


class ConsultaStatus(BaseModel):
    status: str  # cache | em_andamento | recusada
    motivo: Optional[str] = None


async def _consulta_automatica(cnpj_num: str, ano: int):
    """Abre o navegador no servidor, tenta a identificação e grava os períodos reais."""
    chave = {"cnpj": cnpj_num, "ano": ano}

    async def registrar_falha(motivo: str):
        await db.tentativas_consulta.update_one(
            chave, {"$set": {**chave, "em": datetime.now(timezone.utc).isoformat(),
                             "motivo": motivo[:220]}}, upsert=True)

    sessao = None
    try:
        sessao = await gerenciador.abrir(cnpj_num)
        async with sessao.lock:
            await sessao.enviar_identificacao()
            if not await sessao.autenticado():
                await registrar_falha(await sessao.aviso_site()
                                      or "A Receita não liberou a consulta automática.")
                return
            periodos = await sessao.coletar_ano(ano)
            if not periodos:
                await registrar_falha("Nenhum período encontrado na tela de emissão.")
                return
            await db.apuracoes_importadas.update_one(
                chave, {"$set": {**chave, "periodos": periodos, "origem": "automatica",
                                 "importado_em": datetime.now(timezone.utc).isoformat()}},
                upsert=True)
            await db.tentativas_consulta.delete_one(chave)
    except Exception as exc:
        logger.warning("consulta automática falhou para %s/%s: %s", cnpj_num, ano, exc)
        await registrar_falha(f"Falha na consulta automática: {exc}")
    finally:
        if sessao:
            await gerenciador.encerrar(sessao.id)


@api_router.post("/extensao/mapa")
async def receber_mapa(payload: dict = Body(...)):
    """Auto-descoberta: a extensão envia o mapa da aplicação autenticada.

    Em vez de adivinhar os endpoints do PGMEI (o que já causou 3 bugs), a extensão
    lê sozinha os formulários/campos/links da área logada e manda para cá. Com isso
    monta-se o "Modo API" (fetch em segundo plano) sem chute e sem ação do usuário.
    """
    await db.mapas_pgmei.insert_one({
        "url": str(payload.get("url", ""))[:500],
        "titulo": str(payload.get("titulo", ""))[:300],
        "forms": payload.get("forms", [])[:40],
        "links": payload.get("links", [])[:120],
        "em": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True}


@api_router.post("/apuracao/consultar", response_model=ConsultaStatus)
async def consultar_apuracao(payload: ConsultaAutomaticaRequest):
    """Dispara a busca dos valores reais reaproveitando a sessão autenticada salva.

    Cache de 7 dias primeiro; se vencido, enfileira a consulta no motor (que usa o
    cookie da sessão). O front acompanha relendo /api/apuracao. Sem sessão ativa,
    devolve 'recusada' orientando a renovar a sessão no painel.
    """
    cnpj_num = _only_digits(payload.cnpj)
    if not validar_cnpj(cnpj_num):
        raise HTTPException(status_code=400, detail="CNPJ inválido.")

    chave = {"cnpj": cnpj_num, "ano": payload.ano}
    doc = await db.apuracoes_importadas.find_one(chave)
    if doc and doc.get("periodos") and not _validade_cache(doc.get("importado_em"))["cache_expirado"]:
        return ConsultaStatus(status="cache")

    tentativa = await db.tentativas_consulta.find_one(chave)
    if tentativa and (datetime.now(timezone.utc)
                      - datetime.fromisoformat(tentativa["em"])) < timedelta(hours=1):
        return ConsultaStatus(status="recusada", motivo=tentativa.get("motivo"))

    # O servidor NÃO consegue consultar a Receita: o replay do cookie fora do
    # navegador é redirecionado para a tela de captcha (autenticação depende de
    # token em localStorage + sessão amarrada ao IP de origem). A coleta real é
    # feita pela extensão, dentro do navegador logado do usuário.
    return ConsultaStatus(
        status="recusada",
        motivo="a coleta é feita pela extensão no navegador logado (o servidor não consegue consultar a Receita).",
    )


class DasPdfRequest(BaseModel):
    cnpj: str
    ano: int
    periodos: List[str]
    data_pagamento: str


@api_router.post("/das/pdf")
async def das_pdf(payload: DasPdfRequest):
    """Gera o PDF de resumo do DAS (documento de estudo, sem validade legal)."""
    cnpj_num = _only_digits(payload.cnpj)
    if not validar_cnpj(cnpj_num):
        raise HTTPException(status_code=400, detail="CNPJ inválido.")
    if not payload.periodos:
        raise HTTPException(status_code=400, detail="Selecione ao menos um período de apuração.")

    apurados = await apuracao(cnpj_num, payload.ano)
    escolhidos = [p.model_dump() for p in apurados.periodos if p.pa in payload.periodos]
    if not escolhidos:
        raise HTTPException(status_code=400, detail="Períodos informados não pertencem ao ano-calendário.")

    consulta = await consulta_cnpj(cnpj_num)
    pdf = gerar_pdf_das(
        cnpj=apurados.cnpj_formatado,
        nome=consulta.nome,
        uf=consulta.uf or "",
        ano=payload.ano,
        periodos=escolhidos,
        data_pagamento=payload.data_pagamento,
    )

    await db.das_gerados.insert_one({
        "id": str(uuid.uuid4()),
        "cnpj": cnpj_num,
        "ano": payload.ano,
        "periodos": payload.periodos,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    nome_arquivo = f"DAS_{cnpj_num}_{payload.ano}_estudo.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome_arquivo}"'},
    )


class DasGeradoItem(BaseModel):
    pa: str
    rotulo: str
    numero_apuracao: str
    numero_das: str
    vencimento: str


class DasGeradosResponse(BaseModel):
    cnpj_formatado: str
    ano: int
    data_pagamento: str
    itens: List[DasGeradoItem]


def _em_aberto(situacao: str) -> bool:
    s = (situacao or "").strip().lower()
    return not any(t in s for t in ("liquidad", "pago", "baixad", "a vencer"))


async def _periodos_escolhidos(cnpj_num: str, ano: int, pas: List[str]):
    if not validar_cnpj(cnpj_num):
        raise HTTPException(status_code=400, detail="CNPJ inválido.")
    apurados = await apuracao(cnpj_num, ano)
    if pas:
        escolhidos = [p for p in apurados.periodos if p.pa in pas]
        if not escolhidos:
            raise HTTPException(status_code=400,
                                detail="Períodos informados não pertencem ao ano-calendário.")
    else:
        # Nenhum período marcado: apura automaticamente todos os débitos em aberto
        escolhidos = [p for p in apurados.periodos if _em_aberto(p.situacao)]
        if not escolhidos:
            raise HTTPException(status_code=400,
                                detail="Não há débitos em aberto neste ano-calendário.")
    return apurados, escolhidos


@api_router.get("/das/gerados/{cnpj}/{ano}", response_model=DasGeradosResponse)
async def das_gerados(cnpj: str, ano: int, pas: str, dt: Optional[str] = None):
    """Resumo dos DAS gerados para os períodos selecionados."""
    cnpj_num = _only_digits(cnpj)
    lista = [p for p in pas.split(",") if p.strip()]
    apurados, escolhidos = await _periodos_escolhidos(cnpj_num, ano, lista)

    await db.das_gerados.insert_one({
        "id": str(uuid.uuid4()),
        "cnpj": cnpj_num,
        "ano": ano,
        "periodos": [p.pa for p in escolhidos],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return DasGeradosResponse(
        cnpj_formatado=apurados.cnpj_formatado,
        ano=ano,
        data_pagamento=dt or apurados.data_pagamento,
        itens=[
            DasGeradoItem(
                pa=p.pa,
                rotulo=p.rotulo,
                numero_apuracao=numero_apuracao(cnpj_num, p.pa),
                numero_das=numero_documento(cnpj_num, p.pa),
                vencimento=p.vencimento,
            )
            for p in escolhidos
        ],
    )


@api_router.get("/das/pdf/{cnpj}/{ano}")
async def das_pdf_inline(cnpj: str, ano: int, pas: str, dt: Optional[str] = None):
    """Abre o DAS consolidado em PDF (visualização/impressão)."""
    cnpj_num = _only_digits(cnpj)
    lista = [p for p in pas.split(",") if p.strip()]
    apurados, escolhidos = await _periodos_escolhidos(cnpj_num, ano, lista)
    consulta = await consulta_cnpj(cnpj_num)

    pdf = gerar_pdf_das(
        cnpj=apurados.cnpj_formatado,
        nome=consulta.nome,
        uf=consulta.uf or "",
        ano=ano,
        periodos=[p.model_dump() for p in escolhidos],
        data_pagamento=dt or apurados.data_pagamento,
    )
    nome_arquivo = f"DAS_{cnpj_num}_{ano}_estudo.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome_arquivo}"'},
    )


class PixResponse(BaseModel):
    cnpj_formatado: str
    ano: int
    valor: float
    valor_formatado: str
    codigo_pix: str
    qrcode: str
    data_pagamento: str
    periodos: List[DasGeradoItem]


@api_router.get("/das/pix/{cnpj}/{ano}", response_model=PixResponse)
async def das_pix(cnpj: str, ano: int, pas: str = "", dt: Optional[str] = None):
    """Dados do pagamento via PIX (documento de estudo — código não pagável)."""
    cnpj_num = _only_digits(cnpj)
    lista = [p for p in pas.split(",") if p.strip()]
    apurados, escolhidos = await _periodos_escolhidos(cnpj_num, ano, lista)
    pagamento = dt or apurados.data_pagamento

    total = 0.0
    for p in escolhidos:
        try:
            venc = datetime.strptime(p.vencimento, "%d/%m/%Y").date()
        except ValueError:
            venc = _vencimento_das(ano, int(p.pa[4:6]))
        try:
            pago_em = datetime.strptime(pagamento, "%d/%m/%Y").date()
        except ValueError:
            pago_em = datetime.now(timezone.utc).date()
        total += composicao_das(ano, "", venc, pago_em)["total"]
    total = round(total, 2)

    identificador = f"DAS{ano}{escolhidos[0].pa[4:6]}{cnpj_num[:6]}"
    codigo = codigo_pix_estudo(total, identificador)

    return PixResponse(
        cnpj_formatado=apurados.cnpj_formatado,
        ano=ano,
        valor=total,
        valor_formatado=brl(total),
        codigo_pix=codigo,
        qrcode=qrcode_base64(codigo),
        data_pagamento=pagamento,
        periodos=[
            DasGeradoItem(
                pa=p.pa,
                rotulo=p.rotulo,
                numero_apuracao=numero_apuracao(cnpj_num, p.pa),
                numero_das=numero_documento(cnpj_num, p.pa),
                vencimento=p.vencimento,
            )
            for p in escolhidos
        ],
    )


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_obj = StatusCheck(**input.model_dump())
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    await db.status_checks.insert_one(doc)
    return status_obj


# Include the router in the main app
app.include_router(api_router)
app.include_router(montar_admin_router(db, motor))


@app.on_event("startup")
async def iniciar_motor():
    motor.iniciar(db)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    await gerenciador.encerrar_todas()
    client.close()
