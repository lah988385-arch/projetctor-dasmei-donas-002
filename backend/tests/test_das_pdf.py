"""Tests for DAS PDF consolidado + GET /api/das/gerados + GET /api/das/pdf."""
import io
import os
import re

import pdfplumber
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CNPJ_MARIA = "40570199000108"
CNPJ_LUCI = "37411286000108"


def _post_pdf(payload, expected=200):
    r = requests.post(f"{API}/das/pdf", json=payload, timeout=60)
    assert r.status_code == expected, f"{r.status_code}: {r.text[:300]}"
    return r


def _get_pdf(cnpj, ano, pas, dt=None, expected=200):
    params = {"pas": pas}
    if dt:
        params["dt"] = dt
    r = requests.get(f"{API}/das/pdf/{cnpj}/{ano}", params=params, timeout=60)
    assert r.status_code == expected, f"{r.status_code}: {r.text[:300]}"
    return r


def _get_gerados(cnpj, ano, pas, dt=None, expected=200):
    params = {"pas": pas}
    if dt:
        params["dt"] = dt
    r = requests.get(f"{API}/das/gerados/{cnpj}/{ano}", params=params, timeout=60)
    assert r.status_code == expected, f"{r.status_code}: {r.text[:300]}"
    return r


def _normalize(text):
    text = re.sub(r"\s+", " ", text)
    for _ in range(3):
        text = re.sub(r" [A-Z] ", " ", text)
    text = re.sub(r"(\d)\s*,\s*(\d{2})", r"\1,\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_pages(pdf_bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return [p.extract_text() or "" for p in pdf.pages]


# ---------- Consulta CNPJ expõe UF ----------
def test_consulta_cnpj_returns_uf():
    r = requests.get(f"{API}/consulta-cnpj/{CNPJ_MARIA}", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["uf"] == "RN"
    assert "MARIA JANIERE" in (data.get("nome") or "").upper()


# ---------- POST PDF período único consolidado (1 página) ----------
def test_post_das_pdf_ago_2026_contents():
    r = _post_pdf({
        "cnpj": CNPJ_MARIA, "ano": 2026,
        "periodos": ["202608"], "data_pagamento": "01/10/2026",
    })
    assert r.headers.get("content-type", "").startswith("application/pdf")
    pages = _extract_pages(r.content)
    assert len(pages) == 1
    text = _normalize(pages[0])
    for frag in ["40.570.199/0001-08", "MARIA JANIERE", "agosto/2026", "21/09/2026",
                 "0151", "0083", "DOCUMENTO DE ESTUDO", "NÃO PAGÁVEL", "Totais"]:
        assert frag in text, f"missing {frag}"
    assert re.search(r"Tributos\s*\(R\$\):\s*INSS\s*81,05\s*ICMS\s*1,00\s*ISS\s*0,00", text)
    for v in ("81,05", "2,67", "0,81", "84,53", "1,00", "0,03", "0,01", "1,04",
              "82,05", "2,70", "0,82", "85,57"):
        assert v in text, f"{v} missing"


# ---------- Consolidado 3 períodos → 1 página ----------
def test_get_das_pdf_consolidado_3_periodos():
    r = _get_pdf(CNPJ_MARIA, 2026, "202607,202608,202609", "01/10/2026")
    assert r.headers.get("content-type", "").startswith("application/pdf")
    assert "inline" in r.headers.get("content-disposition", "")
    pages = _extract_pages(r.content)
    assert len(pages) == 1, f"esperado 1 página, veio {len(pages)}"
    text = _normalize(pages[0])
    assert "07/2026 a 09/2026" in text, text
    # tributos consolidados
    assert re.search(r"INSS\s*243,15\s*ICMS\s*3,00\s*ISS\s*0,00", text), text
    # 6 linhas de composição (3 INSS + 3 ICMS)
    assert text.count("0151") >= 3
    assert text.count("0083") >= 3
    # Totais consolidados (Selic 0.010841; juros = 1% + Selic*(meses-1))
    for v in ("246,15", "14,07", "2,53", "262,75"):
        assert v in text, f"total {v} ausente"
    assert "DOCUMENTO DE ESTUDO" in text
    assert "NÃO PAGÁVEL" in text


# ---------- GET /api/das/gerados ----------
def test_get_das_gerados_single():
    r = _get_gerados(CNPJ_MARIA, 2026, "202610", "01/10/2026")
    data = r.json()
    assert data["cnpj_formatado"] == "40.570.199/0001-08"
    assert data["ano"] == 2026
    assert len(data["itens"]) == 1
    item = data["itens"][0]
    assert item["pa"] == "202610"
    assert "utubro" in item["rotulo"].lower() or "Outubro" in item["rotulo"]
    assert item["numero_apuracao"] == "405701992026102809"
    assert item["numero_das"] == "07.10.72809.9874471-3"
    assert item["vencimento"] == "23/11/2026"


def test_get_das_gerados_multi():
    r = _get_gerados(CNPJ_MARIA, 2026, "202607,202608,202609", "01/10/2026")
    data = r.json()
    assert len(data["itens"]) == 3
    pas = [i["pa"] for i in data["itens"]]
    assert pas == ["202607", "202608", "202609"]
    for item in data["itens"]:
        assert len(item["numero_apuracao"]) == 18
        assert re.match(r"07\.\d{2}\.\d{5}\.\d{7}-\d", item["numero_das"])


# ---------- Validações ----------
def test_gerados_cnpj_invalido():
    _get_gerados("11111111111111", 2026, "202608", expected=400)


def test_gerados_pas_vazio_auto_apura():
    # Agora pas vazio = auto-apura devedores (não é mais 400)
    r = requests.get(f"{API}/das/gerados/{CNPJ_MARIA}/2026", params={"pas": ""}, timeout=30)
    assert r.status_code == 200
    assert len(r.json()["itens"]) == 2


def test_gerados_periodo_outro_ano():
    _get_gerados(CNPJ_MARIA, 2026, "202501", expected=400)


def test_pdf_get_cnpj_invalido():
    _get_pdf("11111111111111", 2026, "202608", expected=400)


def test_pdf_get_pas_vazio_auto_apura():
    # Agora pas vazio = auto-apura devedores (não é mais 400)
    r = requests.get(f"{API}/das/pdf/{CNPJ_MARIA}/2026", params={"pas": ""}, timeout=60)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")


def test_pdf_get_periodo_outro_ano():
    _get_pdf(CNPJ_MARIA, 2026, "202501", expected=400)


def test_post_das_pdf_invalid_cnpj():
    _post_pdf({"cnpj": "11111111111111", "ano": 2026,
               "periodos": ["202608"], "data_pagamento": "01/10/2026"}, expected=400)


def test_post_das_pdf_periodos_vazios():
    _post_pdf({"cnpj": CNPJ_MARIA, "ano": 2026,
               "periodos": [], "data_pagamento": "01/10/2026"}, expected=400)


# ---------- 12 períodos consolidados em 1 página ----------
def test_get_das_pdf_12_periodos_1_pagina():
    pas = ",".join(f"2026{m:02d}" for m in range(1, 13))
    r = _get_pdf(CNPJ_LUCI, 2026, pas, "01/10/2026")
    pages = _extract_pages(r.content)
    assert len(pages) == 1
    text = _normalize(pages[0])
    assert "01/2026 a 12/2026" in text, text
    # 12 INSS + 12 ICMS
    assert text.count("0151") >= 12
    assert text.count("0083") >= 12
