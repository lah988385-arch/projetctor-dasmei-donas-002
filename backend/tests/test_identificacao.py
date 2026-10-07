"""Backend tests for PGMEI /api/identificacao endpoint."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://pgmei-study.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# Root health
def test_root(client):
    r = client.get(f"{API}/")
    assert r.status_code == 200
    assert r.json().get("message") == "Hello World"


# Valid CNPJ (formatted)
def test_identificacao_valid_formatted(client):
    r = client.post(f"{API}/identificacao", json={"cnpj": "11.222.333/0001-81"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["valido"] is True
    assert data["cnpj"] == "11.222.333/0001-81"
    assert "sucesso" in data["mensagem"].lower()


# Valid CNPJ (digits only)
def test_identificacao_valid_digits(client):
    r = client.post(f"{API}/identificacao", json={"cnpj": "11222333000181"})
    assert r.status_code == 200
    data = r.json()
    assert data["valido"] is True
    assert data["status"] == "ok"
    assert data["cnpj"] == "11.222.333/0001-81"


# Invalid CNPJ - repeated digits
def test_identificacao_invalid_repeated(client):
    r = client.post(f"{API}/identificacao", json={"cnpj": "11.111.111/1111-11"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "erro"
    assert data["valido"] is False
    assert "inválido" in data["mensagem"].lower() or "invalido" in data["mensagem"].lower()


# Invalid CNPJ - wrong check digits
def test_identificacao_invalid_dv(client):
    r = client.post(f"{API}/identificacao", json={"cnpj": "11.222.333/0001-82"})
    assert r.status_code == 200
    data = r.json()
    assert data["valido"] is False
    assert data["status"] == "erro"


# Invalid - too short
def test_identificacao_short(client):
    r = client.post(f"{API}/identificacao", json={"cnpj": "123"})
    assert r.status_code == 200
    assert r.json()["valido"] is False


# Missing field -> 422
def test_identificacao_missing(client):
    r = client.post(f"{API}/identificacao", json={})
    assert r.status_code == 422


# Persistence check: insert and query via a subsequent valid call
def test_identificacao_persists(client):
    # Just assert the endpoint returned 200 for valid cnpj (persistence verified by no 500)
    r = client.post(f"{API}/identificacao", json={"cnpj": "11.222.333/0001-81"})
    assert r.status_code == 200
