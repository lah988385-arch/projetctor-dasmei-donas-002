"""Tests for /donaspainel admin API (admin_painel.py) + motor + extension zip."""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
# Fallback: load from frontend/.env if not in env
if not BASE_URL:
    from pathlib import Path
    for line in Path("/app/frontend/.env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

USER = "donas"
PASS = "Seinao10@@"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/admin/login",
                      json={"usuario": USER, "senha": PASS}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["usuario"] == USER
    assert isinstance(data["token"], str) and len(data["token"]) > 20
    return data["token"]


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- Login ---
class TestAdminLogin:
    def test_login_sucesso(self):
        r = requests.post(f"{BASE_URL}/api/admin/login",
                          json={"usuario": USER, "senha": PASS}, timeout=20)
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_senha_errada(self):
        r = requests.post(f"{BASE_URL}/api/admin/login",
                          json={"usuario": USER, "senha": "errada"}, timeout=20)
        assert r.status_code == 401

    def test_login_usuario_errado(self):
        r = requests.post(f"{BASE_URL}/api/admin/login",
                          json={"usuario": "outro", "senha": PASS}, timeout=20)
        assert r.status_code == 401


# --- Protected routes w/o token ---
class TestProtecao:
    @pytest.mark.parametrize("path", [
        "/api/admin/dashboard", "/api/admin/faturas",
        "/api/admin/sessao", "/api/admin/motor", "/api/admin/me",
    ])
    def test_sem_token_401(self, path):
        r = requests.get(f"{BASE_URL}{path}", timeout=15)
        assert r.status_code == 401


# --- Dashboard ---
class TestDashboard:
    def test_dashboard_shape(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/dashboard",
                         headers=auth_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ("total_acessos", "acessos_validos", "total_consultas",
                  "total_faturas", "serie_acessos", "recentes"):
            assert k in d
        assert isinstance(d["serie_acessos"], list)
        assert len(d["serie_acessos"]) == 14
        for item in d["serie_acessos"]:
            assert "dia" in item and "acessos" in item


# --- Faturas ---
class TestFaturas:
    def test_faturas_shape(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/faturas",
                         headers=auth_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert "total" in d and "itens" in d
        assert isinstance(d["itens"], list)
        if d["itens"]:
            item = d["itens"][0]
            for k in ("cnpj", "ano", "periodos"):
                assert k in item


# --- Sessão com reconfirmação de senha ---
class TestSessao:
    def test_status(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/sessao",
                         headers=auth_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ("ativa", "tem_cookie", "atualizada_em", "expira_em", "expirada"):
            assert k in d

    def test_salvar_sem_senha_painel_erra_403(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/sessao",
                         headers=auth_headers,
                         json={"cookie": "JSESSIONID=TEST_fake",
                               "descricao": "TEST", "senha": "senha_errada"},
                         timeout=20)
        assert r.status_code == 403

    def test_salvar_senha_correta_200(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/sessao",
                         headers=auth_headers,
                         json={"cookie": "JSESSIONID=TEST_fake_cookie_aaa",
                               "descricao": "TEST sessão", "senha": PASS},
                         timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        # confirm status reflects it
        s = requests.get(f"{BASE_URL}/api/admin/sessao",
                        headers=auth_headers, timeout=20).json()
        assert s["ativa"] is True
        assert s["tem_cookie"] is True
        assert s["expira_em"] is not None

    def test_salvar_cookie_vazio_400(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/sessao",
                         headers=auth_headers,
                         json={"cookie": "   ", "senha": PASS}, timeout=20)
        assert r.status_code == 400


# --- Motor status ---
class TestMotor:
    def test_motor_status(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/motor",
                         headers=auth_headers, timeout=20)
        assert r.status_code == 200
        d = r.json()
        assert d.get("disponivel") is True
        for k in ("fila", "processadas_ok", "falhas",
                  "sessao_viva", "espaco_segundos"):
            assert k in d


# --- Consulta automatica (public) ---
class TestConsultaAuto:
    def test_consultar_apuracao_resposta(self):
        r = requests.post(f"{BASE_URL}/api/apuracao/consultar",
                          json={"cnpj": "40570199000108", "ano": 2025},
                          timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d["status"] in ("recusada", "em_andamento", "cache")
        if d["status"] == "recusada" and d.get("motivo"):
            # Should mention renovar/sessão/painel OR be a prior-attempt message
            assert isinstance(d["motivo"], str)


# --- Extensão zip ---
class TestExtensao:
    def test_zip_disponivel(self):
        r = requests.get(f"{BASE_URL}/extensao-sessao.zip", timeout=20)
        assert r.status_code == 200
        assert len(r.content) > 100


# --- Regressão app público ---
class TestRegressaoPublica:
    def test_root_api(self):
        r = requests.get(f"{BASE_URL}/api/", timeout=20)
        assert r.status_code == 200
