"""Tests for GET /api/apuracao/{cnpj}/{ano} — new Liquidado/Devedor/A Vencer rule."""
import os
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

CNPJ_MARIA = "40570199000108"


def test_apuracao_2026_situacoes():
    r = requests.get(f"{API}/apuracao/{CNPJ_MARIA}/2026", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["cnpj_formatado"] == "40.570.199/0001-08"
    assert len(data["periodos"]) == 12
    by_pa = {p["pa"]: p for p in data["periodos"]}
    # Jan-Jun 2026 = Liquidado (valores "-")
    for mes in range(1, 7):
        p = by_pa[f"20260{mes}"]
        assert p["situacao"] == "Liquidado", p
        for k in ("principal", "multa", "juros", "total"):
            assert p[k] == "-"
    # Julho/Agosto 2026 = Devedor
    jul = by_pa["202607"]
    assert jul["situacao"] == "Devedor"
    assert jul["principal"] == "R$ 82,05"
    assert jul["multa"] == "R$ 11,37"
    assert jul["juros"] == "R$ 1,71"
    assert jul["total"] == "R$ 95,13"
    assert jul["vencimento"] == "20/08/2026"
    assert jul["data_acolhimento"] == "01/10/2026"

    ago = by_pa["202608"]
    assert ago["situacao"] == "Devedor"
    assert ago["principal"] == "R$ 82,05"
    assert ago["multa"] == "R$ 2,70"
    assert ago["juros"] == "R$ 0,82"
    assert ago["total"] == "R$ 85,57"
    assert ago["vencimento"] == "21/09/2026"
    assert ago["data_acolhimento"] == "01/10/2026"

    # Setembro-Dezembro 2026 = A Vencer, multa/juros zerados
    for pa in ("202609", "202610", "202611", "202612"):
        p = by_pa[pa]
        assert p["situacao"] == "A Vencer", p
        assert p["principal"] == "R$ 82,05"
        assert p["multa"] == "R$ 0,00"
        assert p["juros"] == "R$ 0,00"
        assert p["total"] == "R$ 82,05"
