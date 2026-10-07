import os
import requests
import pytest

BASE = os.environ.get("REACT_APP_BACKEND_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0].strip()
BASE = BASE.rstrip("/")

VALID_CNPJ_1 = "37411286000108"
VALID_CNPJ_2 = "11222333000181"
INVALID = "11111111111111"


def test_consulta_valid_1():
    r = requests.get(f"{BASE}/api/consulta-cnpj/{VALID_CNPJ_1}", timeout=25)
    assert r.status_code == 200
    d = r.json()
    assert d["encontrado"] is True
    assert d["cnpj_formatado"] == "37.411.286/0001-08"
    assert d["nome"] == "LUCI SCHIAVI DA SILVA 42017335215"


def test_consulta_valid_2():
    r = requests.get(f"{BASE}/api/consulta-cnpj/{VALID_CNPJ_2}", timeout=25)
    assert r.status_code == 200
    d = r.json()
    assert d["encontrado"] is True
    assert d["nome"] and d["nome"] != "Contribuinte não localizado"


def test_consulta_invalid():
    r = requests.get(f"{BASE}/api/consulta-cnpj/{INVALID}", timeout=25)
    assert r.status_code == 200
    d = r.json()
    assert d["encontrado"] is False
    assert d["nome"] == "Contribuinte não localizado"


def test_identificacao_valid():
    r = requests.post(f"{BASE}/api/identificacao", json={"cnpj": VALID_CNPJ_1}, timeout=15)
    assert r.status_code == 200
    assert r.json()["valido"] is True


def test_identificacao_invalid():
    r = requests.post(f"{BASE}/api/identificacao", json={"cnpj": INVALID}, timeout=15)
    assert r.status_code == 200
    assert r.json()["valido"] is False
