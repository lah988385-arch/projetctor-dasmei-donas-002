"""Painel administrativo /donaspainel.

Autenticação JWT de um único admin (usuário/senha vindos do .env), estatísticas
de acessos, faturas geradas e gestão da sessão autenticada do gov.br (o cookie que
o servidor reaproveita para consultar os valores reais).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

JWT_ALGORITHM = "HS256"
TOKEN_HORAS = 12

admin_router = APIRouter(prefix="/api/admin")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    usuario: str
    senha: str


class TokenResponse(BaseModel):
    token: str
    usuario: str


class SessaoCookieRequest(BaseModel):
    cookie: str
    descricao: Optional[str] = None
    senha: str  # reconfirmação da senha do painel antes de salvar


# ---------------------------------------------------------------------------
# Helpers de senha / token
# ---------------------------------------------------------------------------
def _admin_usuario() -> str:
    return os.environ["ADMIN_USER"]


def _admin_senha() -> str:
    return os.environ["ADMIN_PASSWORD"]


def _jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def verificar_senha(senha: str) -> bool:
    return senha == _admin_senha()


def criar_token(usuario: str) -> str:
    payload = {
        "sub": usuario,
        "exp": datetime.now(timezone.utc) + timedelta(hours=TOKEN_HORAS),
        "type": "admin",
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def _ler_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    cookie = request.cookies.get("admin_token")
    if cookie:
        return cookie
    raise HTTPException(status_code=401, detail="Não autenticado.")


async def admin_atual(request: Request) -> str:
    token = _ler_token(request)
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sessão expirada. Faça login novamente.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido.")
    if payload.get("type") != "admin" or payload.get("sub") != _admin_usuario():
        raise HTTPException(status_code=401, detail="Token inválido.")
    return payload["sub"]


# ---------------------------------------------------------------------------
# Factory: recebe o db do server.py e devolve o router pronto
# ---------------------------------------------------------------------------
def montar_router(db, motor=None) -> APIRouter:

    # ---- Auth ----
    @admin_router.post("/login", response_model=TokenResponse)
    async def login(payload: LoginRequest, request: Request):
        ip = request.client.host if request.client else "desconhecido"
        ok = payload.usuario == _admin_usuario() and verificar_senha(payload.senha)
        await db.admin_logins.insert_one({
            "usuario": payload.usuario,
            "sucesso": ok,
            "ip": ip,
            "em": datetime.now(timezone.utc).isoformat(),
        })
        if not ok:
            raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
        return TokenResponse(token=criar_token(payload.usuario), usuario=payload.usuario)

    @admin_router.get("/me")
    async def me(usuario: str = Depends(admin_atual)):
        return {"usuario": usuario}

    # ---- Dashboard ----
    @admin_router.get("/dashboard")
    async def dashboard(usuario: str = Depends(admin_atual)):
        agora = datetime.now(timezone.utc)
        inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        inicio_mes = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        total_acessos = await db.identificacoes.count_documents({})
        acessos_validos = await db.identificacoes.count_documents({"valido": True})
        total_consultas = await db.consultas.count_documents({})
        total_faturas = await db.das_gerados.count_documents({})
        acessos_hoje = await db.identificacoes.count_documents(
            {"timestamp": {"$gte": inicio_dia.isoformat()}})
        faturas_mes = await db.das_gerados.count_documents(
            {"timestamp": {"$gte": inicio_mes.isoformat()}})

        # série dos últimos 14 dias (acessos por dia)
        serie = []
        for i in range(13, -1, -1):
            dia = (inicio_dia - timedelta(days=i))
            prox = dia + timedelta(days=1)
            qtd = await db.identificacoes.count_documents(
                {"timestamp": {"$gte": dia.isoformat(), "$lt": prox.isoformat()}})
            serie.append({"dia": dia.strftime("%d/%m"), "acessos": qtd})

        # últimos acessos
        recentes = []
        async for doc in db.identificacoes.find().sort("timestamp", -1).limit(12):
            recentes.append({
                "cnpj": doc.get("cnpj_formatado") or doc.get("cnpj", ""),
                "valido": doc.get("valido", False),
                "em": doc.get("timestamp", ""),
            })

        return {
            "total_acessos": total_acessos,
            "acessos_validos": acessos_validos,
            "acessos_hoje": acessos_hoje,
            "total_consultas": total_consultas,
            "total_faturas": total_faturas,
            "faturas_mes": faturas_mes,
            "serie_acessos": serie,
            "recentes": recentes,
        }

    # ---- Faturas geradas ----
    @admin_router.get("/faturas")
    async def faturas(usuario: str = Depends(admin_atual), limite: int = 100):
        itens = []
        async for doc in db.das_gerados.find().sort("timestamp", -1).limit(min(limite, 300)):
            periodos = doc.get("periodos", []) or []
            itens.append({
                "id": doc.get("id", ""),
                "cnpj": doc.get("cnpj", ""),
                "ano": doc.get("ano"),
                "periodos": periodos,
                "qtd_periodos": len(periodos),
                "em": doc.get("timestamp", ""),
            })
        total = await db.das_gerados.count_documents({})
        return {"total": total, "itens": itens}

    # ---- Sessão gov.br (cookie reaproveitado) ----
    @admin_router.get("/sessao")
    async def sessao_status(usuario: str = Depends(admin_atual)):
        doc = await db.sessao_govbr.find_one({"_id": "atual"})
        if not doc:
            return {"ativa": False, "atualizada_em": None, "descricao": None,
                    "expira_em": None, "expirada": True, "tem_cookie": False}
        atualizada = doc.get("atualizada_em")
        expira = None
        expirada = True
        if atualizada:
            dt = datetime.fromisoformat(atualizada)
            # a Receita derruba a sessão semanalmente; tratamos 7 dias como validade
            exp = dt + timedelta(days=7)
            expira = exp.isoformat()
            expirada = datetime.now(timezone.utc) >= exp
        return {
            "ativa": bool(doc.get("cookie")) and not expirada,
            "tem_cookie": bool(doc.get("cookie")),
            "atualizada_em": atualizada,
            "descricao": doc.get("descricao"),
            "expira_em": expira,
            "expirada": expirada,
        }

    @admin_router.post("/sessao")
    async def sessao_atualizar(payload: SessaoCookieRequest,
                               usuario: str = Depends(admin_atual)):
        # segurança: reconfirmação da senha do painel antes de salvar
        if not verificar_senha(payload.senha):
            raise HTTPException(status_code=403, detail="Senha do painel incorreta.")
        cookie = (payload.cookie or "").strip()
        if not cookie:
            raise HTTPException(status_code=400, detail="Cole o cookie da sessão autenticada.")
        agora = datetime.now(timezone.utc).isoformat()
        await db.sessao_govbr.update_one(
            {"_id": "atual"},
            {"$set": {"cookie": cookie, "descricao": (payload.descricao or "").strip() or None,
                      "atualizada_em": agora, "atualizada_por": usuario}},
            upsert=True,
        )
        await db.sessao_govbr_historico.insert_one({
            "descricao": (payload.descricao or "").strip() or None,
            "atualizada_por": usuario,
            "em": agora,
        })
        return {"ok": True, "atualizada_em": agora}

    # ---- Motor de consulta (status) ----
    @admin_router.get("/motor")
    async def motor_status(usuario: str = Depends(admin_atual)):
        if motor is None:
            return {"disponivel": False}
        return {"disponivel": True, **motor.status()}

    return admin_router
