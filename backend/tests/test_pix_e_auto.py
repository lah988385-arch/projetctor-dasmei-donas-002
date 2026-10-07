"""Tests for new PIX endpoint and auto-apuração when pas is empty."""
import io
import os
import re

import pdfplumber
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CNPJ_MARIA = "40570199000108"


# -------- PIX endpoint, pas vazio = soma todos os devedores --------
def test_pix_sem_selecao_soma_devedores():
    r = requests.get(f"{API}/das/pix/{CNPJ_MARIA}/2026",
                     params={"pas": "", "dt": "01/10/2026"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["valor"] == 180.70
    assert d["valor_formatado"] == "180,70"
    pas = [p["pa"] for p in d["periodos"]]
    assert pas == ["202607", "202608"]
    assert d["codigo_pix"].startswith("00020101")
    # CRC16 — 4 chars hex ao final
    assert re.match(r".+[0-9A-F]{4}$", d["codigo_pix"])
    assert d["qrcode"].startswith("data:image/png;base64,")


def test_pix_com_selecao_um_periodo():
    r = requests.get(f"{API}/das/pix/{CNPJ_MARIA}/2026",
                     params={"pas": "202609", "dt": "01/10/2026"}, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["valor"] == 82.05
    assert len(d["periodos"]) == 1
    assert d["periodos"][0]["pa"] == "202609"


# -------- GET das/gerados com pas vazio = devedores --------
def test_gerados_sem_selecao():
    r = requests.get(f"{API}/das/gerados/{CNPJ_MARIA}/2026",
                     params={"pas": "", "dt": "01/10/2026"}, timeout=30)
    assert r.status_code == 200
    data = r.json()
    pas = [i["pa"] for i in data["itens"]]
    assert pas == ["202607", "202608"]


# -------- PDF sem seleção consolidando devedores --------
def test_pdf_sem_selecao_consolidado():
    r = requests.get(f"{API}/das/pdf/{CNPJ_MARIA}/2026",
                     params={"pas": "", "dt": "01/10/2026"}, timeout=60)
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/pdf")
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        assert len(pdf.pages) == 1
        text = re.sub(r"\s+", " ", pdf.pages[0].extract_text() or "")
    assert "180,70" in text
    assert "07/2026 a 08/2026" in text
    assert "DOCUMENTO DE ESTUDO" in text


# -------- Ano sem débitos deve retornar 400 (bug atual: retorna 200 p/ 2024) --------
def test_pix_ano_sem_debitos_retorna_400():
    r = requests.get(f"{API}/das/pix/{CNPJ_MARIA}/2024",
                     params={"pas": "", "dt": "01/10/2026"}, timeout=30)
    assert r.status_code == 400, (
        "Esperado 400 'Não há débitos em aberto', recebeu "
        f"{r.status_code} — regra 'devedores' aplicada por ano inclui "
        "indevidamente Nov/Dec 2024 como Devedor"
    )


def test_pdf_ano_sem_debitos_retorna_400():
    r = requests.get(f"{API}/das/pdf/{CNPJ_MARIA}/2024",
                     params={"pas": ""}, timeout=30)
    assert r.status_code == 400


def test_gerados_ano_sem_debitos_retorna_400():
    r = requests.get(f"{API}/das/gerados/{CNPJ_MARIA}/2024",
                     params={"pas": ""}, timeout=30)
    assert r.status_code == 400
