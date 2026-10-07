"""Parser do HTML da tela de emissão do PGMEI oficial.

O usuário resolve o hCaptcha no site da Receita, copia o código-fonte da tela de
emissão e cola no app; aqui o HTML é convertido nos mesmos períodos de apuração
que o restante do sistema consome.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

MESES_NUM = {nome.lower(): i + 1 for i, nome in enumerate(MESES_PT)}

# posições usadas pela tabela da Receita quando o cabeçalho não é reconhecido
POSICOES_PADRAO = {
    "periodo": 1, "apurado": 2, "situacao": 4, "principal": 5, "multa": 6,
    "juros": 7, "total": 8, "data_vencimento": 9, "data_acolhimento": 10,
}

ROTULOS = {
    "periodo": ("periodo de apuracao", "periodo"),
    "apurado": ("apurado",),
    "situacao": ("situacao",),
    "principal": ("principal",),
    "multa": ("multa",),
    "juros": ("juros",),
    "total": ("total",),
    "data_vencimento": ("data de vencimento", "vencimento"),
    "data_acolhimento": ("data de acolhimento", "acolhimento"),
}


def _sem_acento(texto: str) -> str:
    mapa = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ",
                         "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC")
    return texto.translate(mapa)


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", _sem_acento(texto or "")).strip().lower()


def _texto(celula) -> str:
    return re.sub(r"\s+", " ", celula.get_text(" ", strip=True)) if celula else ""


def _pa_do_texto(texto: str) -> Optional[str]:
    """Extrai AAAAMM de rótulos como '01/2026', '2026/01' ou 'Janeiro/2026'."""
    t = _normalizar(texto)
    m = re.search(r"(\d{2})\s*/\s*(\d{4})", t)
    if m:
        return f"{m.group(2)}{m.group(1)}"
    m = re.search(r"(\d{4})\s*/\s*(\d{2})", t)
    if m:
        return f"{m.group(1)}{m.group(2)}"
    m = re.search(r"([a-z]+)\s*/\s*(\d{4})", t)
    if m and m.group(1) in MESES_NUM:
        return f"{m.group(2)}{MESES_NUM[m.group(1)]:02d}"
    m = re.search(r"\b(\d{6})\b", t)
    return m.group(1) if m else None


def _mapear_colunas(tabela) -> Dict[str, int]:
    """Lê o <thead> e descobre o índice de cada coluna; cai no padrão se falhar."""
    posicoes = dict(POSICOES_PADRAO)
    linhas_cabecalho = tabela.select("thead tr")
    if not linhas_cabecalho:
        return posicoes

    encontrados: Dict[str, int] = {}
    inicio_proxima_linha = 0
    for linha_idx, tr in enumerate(linhas_cabecalho):
        # a 2ª linha do cabeçalho só preenche as colunas agrupadas pelo colspan
        indice = inicio_proxima_linha if linha_idx else 0
        inicio_grupo = None
        for th in tr.find_all("th"):
            rotulo = _normalizar(_texto(th))
            colspan = int(th.get("colspan") or 1)
            if colspan > 1 and inicio_grupo is None:
                inicio_grupo = indice
            for campo, nomes in ROTULOS.items():
                if campo not in encontrados and rotulo in nomes:
                    encontrados[campo] = indice
            indice += colspan
        if inicio_grupo is not None:
            inicio_proxima_linha = inicio_grupo

    # Se o cabeçalho foi lido, confia NELE: campos ausentes ficam None -> "-".
    # Antes exigia-se 'principal'; quando um ano não traz as colunas de valor
    # (tudo liquidado), o mapeamento era descartado e as posições fixas liam a
    # coluna errada — a situação virava "R$ 71,60" e os meses ficavam "-".
    if "periodo" in encontrados and "situacao" in encontrados:
        return {campo: encontrados.get(campo) for campo in ROTULOS}
    return posicoes


def _valor(celulas: List, indice: Optional[int]) -> str:
    if indice is None or indice >= len(celulas):
        return "-"
    texto = _texto(celulas[indice])
    return texto or "-"


def _moeda_para_float(texto: str) -> float:
    limpo = re.sub(r"[^\d,.-]", "", texto or "").replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return 0.0


def _rotulo_pa(pa: str) -> str:
    if len(pa) == 6 and pa.isdigit():
        mes = int(pa[4:6])
        if 1 <= mes <= 12:
            return f"{MESES_PT[mes - 1]}/{pa[:4]}"
    return pa


def parse_emissao(html: str, ano: Optional[int] = None) -> List[dict]:
    """Converte o HTML da tela de emissão nos períodos de apuração do ano."""
    sopa = BeautifulSoup(html or "", "lxml")

    linhas = sopa.select("table tr.pa")
    if not linhas:
        linhas = [tr for tr in sopa.select("table tr") if tr.select_one("input[name=pa]")]
    if not linhas:
        return []

    tabela = linhas[0].find_parent("table")
    colunas = _mapear_colunas(tabela) if tabela else dict(POSICOES_PADRAO)

    periodos: List[dict] = []
    for tr in linhas:
        celulas = tr.find_all("td")
        if len(celulas) < 5:
            continue

        check = tr.select_one("input[name=pa]")
        pa = (check.get("value") or "").strip() if check else ""
        rotulo = _valor(celulas, colunas.get("periodo"))
        if not re.fullmatch(r"\d{6}", pa):
            pa = _pa_do_texto(rotulo) or ""
        if not re.fullmatch(r"\d{6}", pa):
            continue
        if ano and not pa.startswith(str(ano)):
            continue

        situacao = _valor(celulas, colunas.get("situacao"))
        vencimento = _valor(celulas, colunas.get("data_vencimento"))
        periodos.append({
            "pa": pa,
            "rotulo": _rotulo_pa(pa) if len(rotulo) < 3 else rotulo,
            "apurado": _valor(celulas, colunas.get("apurado")),
            "situacao": situacao,
            "vencimento": vencimento,
            "principal": _valor(celulas, colunas.get("principal")),
            "multa": _valor(celulas, colunas.get("multa")),
            "juros": _valor(celulas, colunas.get("juros")),
            "total": _valor(celulas, colunas.get("total")),
            "data_vencimento": vencimento,
            "data_acolhimento": _valor(celulas, colunas.get("data_acolhimento")),
        })

    periodos.sort(key=lambda p: p["pa"])
    return periodos


def resumir(periodos: List[dict]) -> dict:
    """Agrupa os períodos por situação e soma apenas o que está realmente devido."""
    grupos = {"em_aberto": [], "a_vencer": [], "liquidados": [], "baixados": []}
    for p in periodos:
        s = _normalizar(p["situacao"])
        if "liquidad" in s or "pago" in s:
            grupos["liquidados"].append(p)
        elif "baixad" in s:
            grupos["baixados"].append(p)
        elif "a vencer" in s:
            grupos["a_vencer"].append(p)
        else:
            grupos["em_aberto"].append(p)

    total = round(sum(_moeda_para_float(p["total"]) for p in grupos["em_aberto"]), 2)
    return {**grupos, "total_em_aberto": total}
