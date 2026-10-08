"""Tests for PGMEI HTML import pipeline (POST/GET/DELETE /api/apuracao/importar...).

Covers the user's central requirement: that imported real values are correct and
ISOLATED per CNPJ (no cross-contamination between tenants).
"""
import os
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

# Two valid CNPJs (dígitos verificadores corretos)
CNPJ_A = "11222333000181"  # 1 período Devedor
CNPJ_B = "11444777000161"  # 2 períodos Pago (liquidado)
CNPJ_INVALIDO = "12345678901234"

ANO = 2026


def _html(linhas_tbody: str) -> str:
    return f"""
    <html><body>
    <table>
      <thead>
        <tr>
          <th></th>
          <th>Período</th>
          <th>Apurado</th>
          <th>Situação</th>
          <th>Principal</th>
          <th>Multa</th>
          <th>Juros</th>
          <th>Total</th>
          <th>Data de Vencimento</th>
          <th>Data de Acolhimento</th>
        </tr>
      </thead>
      <tbody>{linhas_tbody}</tbody>
    </table>
    </body></html>
    """


HTML_A = _html(
    """
    <tr class='pa'>
      <td><input name='pa' value='202601'></td>
      <td>01/2026</td><td>Sim</td><td>Devedor</td>
      <td>R$ 73,53</td><td>-</td><td>-</td><td>R$ 73,53</td>
      <td>20/02/2026</td><td>-</td>
    </tr>
    """
)

HTML_B = _html(
    """
    <tr class='pa'>
      <td><input name='pa' value='202603'></td>
      <td>03/2026</td><td>Sim</td><td>Pago</td>
      <td>R$ 70,00</td><td>-</td><td>-</td><td>R$ 70,00</td>
      <td>20/04/2026</td><td>18/04/2026</td>
    </tr>
    <tr class='pa'>
      <td><input name='pa' value='202604'></td>
      <td>04/2026</td><td>Sim</td><td>Liquidado</td>
      <td>R$ 71,20</td><td>-</td><td>-</td><td>R$ 71,20</td>
      <td>20/05/2026</td><td>19/05/2026</td>
    </tr>
    """
)


def _cleanup(cnpj: str):
    try:
        requests.delete(f"{API}/apuracao/importada/{cnpj}/{ANO}", timeout=20)
    except Exception:
        pass


def setup_module(module):
    _cleanup(CNPJ_A)
    _cleanup(CNPJ_B)


def teardown_module(module):
    _cleanup(CNPJ_A)
    _cleanup(CNPJ_B)


# ---------------------------------------------------------------------------
# POST /api/apuracao/importar
# ---------------------------------------------------------------------------
def test_importar_cnpj_a_devedor():
    r = requests.post(f"{API}/apuracao/importar",
                      json={"cnpj": CNPJ_A, "ano": ANO, "html": HTML_A}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["origem"] == "real"
    assert data["total_periodos"] == 1
    assert len(data["em_aberto"]) == 1
    assert len(data["liquidados"]) == 0
    assert len(data["a_vencer"]) == 0
    p = data["em_aberto"][0]
    assert p["pa"] == "202601"
    assert p["situacao"] == "Devedor"
    assert p["total"] == "R$ 73,53"
    # Total em aberto = 73,53
    assert data["total_em_aberto_formatado"] == "73,53"


def test_importar_cnpj_b_pago_e_liquidado():
    r = requests.post(f"{API}/apuracao/importar",
                      json={"cnpj": CNPJ_B, "ano": ANO, "html": HTML_B}, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["origem"] == "real"
    assert data["total_periodos"] == 2
    assert len(data["liquidados"]) == 2
    assert len(data["em_aberto"]) == 0
    assert len(data["a_vencer"]) == 0
    assert data["total_em_aberto_formatado"] == "0,00"
    pas = sorted(p["pa"] for p in data["liquidados"])
    assert pas == ["202603", "202604"]


# ---------------------------------------------------------------------------
# GET /api/apuracao/{cnpj}/{ano} — origem real + isolamento por CNPJ
# ---------------------------------------------------------------------------
def test_get_apuracao_cnpj_a_isolado():
    r = requests.get(f"{API}/apuracao/{CNPJ_A}/{ANO}", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["origem"] == "real"
    # Deve ter SOMENTE o período do CNPJ_A (202601), nada do CNPJ_B
    pas = sorted(p["pa"] for p in data["periodos"])
    assert pas == ["202601"], f"vazou dados entre CNPJs: {pas}"
    p = data["periodos"][0]
    assert p["situacao"] == "Devedor"
    assert p["total"] == "R$ 73,53"


def test_get_apuracao_cnpj_b_isolado():
    r = requests.get(f"{API}/apuracao/{CNPJ_B}/{ANO}", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["origem"] == "real"
    pas = sorted(p["pa"] for p in data["periodos"])
    assert pas == ["202603", "202604"], f"vazou dados entre CNPJs: {pas}"
    for p in data["periodos"]:
        assert p["situacao"] in ("Pago", "Liquidado")


def test_isolamento_resumo_importada():
    """Dupla checagem via /apuracao/importada: cada CNPJ só vê o seu."""
    ra = requests.get(f"{API}/apuracao/importada/{CNPJ_A}/{ANO}", timeout=30).json()
    rb = requests.get(f"{API}/apuracao/importada/{CNPJ_B}/{ANO}", timeout=30).json()

    assert ra["total_periodos"] == 1
    assert len(ra["em_aberto"]) == 1
    assert ra["em_aberto"][0]["pa"] == "202601"
    assert ra["total_em_aberto_formatado"] == "73,53"

    assert rb["total_periodos"] == 2
    assert len(rb["em_aberto"]) == 0
    assert len(rb["liquidados"]) == 2
    assert rb["total_em_aberto_formatado"] == "0,00"


# ---------------------------------------------------------------------------
# DELETE /api/apuracao/importada/{cnpj}/{ano}
# ---------------------------------------------------------------------------
def test_delete_remove_importacao():
    # Re-import to ensure data exists
    requests.post(f"{API}/apuracao/importar",
                  json={"cnpj": CNPJ_A, "ano": ANO, "html": HTML_A}, timeout=30)
    r = requests.delete(f"{API}/apuracao/importada/{CNPJ_A}/{ANO}", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["total_periodos"] == 0
    assert data["origem"] == "mock"

    # Após deletar, GET /apuracao volta para mock
    g = requests.get(f"{API}/apuracao/{CNPJ_A}/{ANO}", timeout=30).json()
    assert g["origem"] == "mock"


# ---------------------------------------------------------------------------
# CNPJ inválido → 400
# ---------------------------------------------------------------------------
def test_importar_cnpj_invalido_400():
    r = requests.post(f"{API}/apuracao/importar",
                      json={"cnpj": CNPJ_INVALIDO, "ano": ANO, "html": HTML_A}, timeout=30)
    assert r.status_code == 400
    assert "CNPJ" in r.json().get("detail", "")
