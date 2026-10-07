"""Reprodução do DAS do Simples Nacional (PGMEI) — documento de estudo, sem validade legal.

Layout, cores, fontes e coordenadas extraídos do PDF oficial enviado pelo usuário.
"""
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

PAGINA_L, PAGINA_A = A4  # 595.27 x 841.89

AZUL = colors.Color(0.0, 0.12549, 0.35686)
VERDE = colors.Color(0.39216, 0.6549, 0.04314)
VERMELHO = colors.Color(0.71, 0.19, 0.17)

LOGO = Path(__file__).parent / "assets" / "simples_nacional.png"

# Salário mínimo por ano — base do INSS do MEI (5%)
SALARIO_MINIMO = {
    2021: 1100.00,
    2022: 1212.00,
    2023: 1320.00,
    2024: 1412.00,
    2025: 1518.00,
    2026: 1621.00,
}

SELIC_MENSAL = 0.010841  # taxa mensal usada na apuração dos juros

MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


# ---------------------------------------------------------------------------
# Valores e código de barras


def composicao_das(ano: int, uf: str, vencimento: date, pagamento: date) -> dict:
    """Tributos do DAS do MEI com multa e juros na data informada para pagamento."""
    minimo = SALARIO_MINIMO.get(ano, SALARIO_MINIMO[max(SALARIO_MINIMO)])
    inss = round(minimo * 0.05, 2)
    icms, iss = 1.00, 0.00

    dias = (pagamento - vencimento).days
    if dias <= 0:
        multa_pct = juros_pct = 0.0
    else:
        multa_pct = min(0.0033 * dias, 0.20)
        meses = (pagamento.year - vencimento.year) * 12 + (pagamento.month - vencimento.month)
        # 1% no mês do pagamento + Selic acumulada dos meses intermediários
        juros_pct = 0.01 + SELIC_MENSAL * max(meses - 1, 0)

    tributos = []
    for codigo, denominacao, principal in (
        ("0151", "INSS - SIMPLES NACIONAL - MEI", inss),
        ("0083", "ICMS - SIMPLES NACIONAL - MEI", icms),
        ("0153", "ISS - SIMPLES NACIONAL - MEI", iss),
    ):
        if principal <= 0:
            continue
        multa = round(principal * multa_pct, 2)
        juros = round(principal * juros_pct, 2)
        tributos.append({
            "codigo": codigo,
            "denominacao": denominacao,
            "uf": uf if codigo == "0083" else "",
            "principal": principal,
            "multa": multa,
            "juros": juros,
            "total": round(principal + multa + juros, 2),
        })

    return {
        "inss": inss,
        "icms": icms,
        "iss": iss,
        "tributos": tributos,
        "principal": round(sum(t["principal"] for t in tributos), 2),
        "multa": round(sum(t["multa"] for t in tributos), 2),
        "juros": round(sum(t["juros"] for t in tributos), 2),
        "total": round(sum(t["total"] for t in tributos), 2),
    }


def _mod11(numero: str) -> int:
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(numero)))
    dv = 11 - (soma % 11)
    if dv == 11:
        return 0
    if dv == 10:
        return 1
    return dv


def numero_documento(cnpj: str, pa: str) -> str:
    """Número do documento no formato 07.MM.NNNNN.NNNNNNN-D (determinístico)."""
    mes = pa[4:6]
    semente = int(cnpj[:8] or 0) + int(pa)
    seq5 = f"{semente % 100000:05d}"
    seq7 = f"{(semente * 7919) % 10000000:07d}"
    dv = _mod11(f"0708{seq5}{seq7}"[-16:])
    return f"07.{mes}.{seq5}.{seq7}-{dv}"


def codigo_barras(valor: float, cnpj: str, pa: str) -> tuple:
    """Código de barras FEBRABAN de arrecadação (44 dígitos) e linha digitável."""
    numero = numero_documento(cnpj, pa)
    digitos_doc = "".join(ch for ch in numero if ch.isdigit())  # 17 dígitos
    centavos = f"{int(round(valor * 100)):011d}"
    orgao = "0328"  # Simples Nacional
    livre = (digitos_doc[4:9] + digitos_doc + "840")[:25].ljust(25, "0")

    base43 = "858" + centavos + orgao + livre
    dv_geral = _mod11(base43)
    codigo = "858" + str(dv_geral) + centavos + orgao + livre

    blocos = [codigo[i:i + 11] for i in range(0, 44, 11)]
    linha = [(b, str(_mod11(b))) for b in blocos]
    return codigo, linha


# ---------------------------------------------------------------------------
# Desenho


class Folha:
    """Converte as coordenadas "top" do documento original para o reportlab."""

    def __init__(self, c: canvas.Canvas):
        self.c = c

    def texto(self, x, top, tamanho, conteudo, negrito=False, cor=colors.black,
              mono=False, alinhamento="left"):
        if mono:
            fonte = "Courier-Bold" if negrito else "Courier"
        else:
            fonte = "Helvetica-Bold" if negrito else "Helvetica"
        self.c.setFont(fonte, tamanho)
        self.c.setFillColor(cor)
        y = PAGINA_A - top - tamanho * 0.80
        if alinhamento == "right":
            self.c.drawRightString(x, y, conteudo)
        elif alinhamento == "center":
            self.c.drawCentredString(x, y, conteudo)
        else:
            self.c.drawString(x, y, conteudo)

    def caixa(self, x0, top, x1, bottom, preenchimento=None, borda=AZUL, raio=2.5):
        self.c.setStrokeColor(borda)
        self.c.setLineWidth(0.6)
        if preenchimento is not None:
            self.c.setFillColor(preenchimento)
        y0, y1 = PAGINA_A - bottom, PAGINA_A - top
        self.c.roundRect(x0, y0, x1 - x0, y1 - y0, raio,
                         stroke=1, fill=1 if preenchimento is not None else 0)


def _formatar_cpf(nome: str) -> str:
    """O nome empresarial do MEI termina com o CPF do titular."""
    digitos = "".join(ch for ch in nome if ch.isdigit())
    if len(digitos) < 11:
        return ""
    cpf = digitos[-11:]
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def brl(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _marca_estudo(f: Folha):
    c = f.c
    c.saveState()
    c.setFillColor(colors.Color(0.71, 0.19, 0.17, alpha=0.10))
    c.setFont("Helvetica-Bold", 40)
    c.translate(PAGINA_L / 2, PAGINA_A / 2)
    c.rotate(36)
    c.drawCentredString(0, 24, "DOCUMENTO DE ESTUDO")
    c.drawCentredString(0, -26, "SEM VALIDADE LEGAL")
    c.restoreState()


def _barras(f: Folha, codigo: str, x: float, top: float, largura: float, altura: float):
    desenho: Drawing = createBarcodeDrawing(
        "I2of5", value=codigo, barHeight=altura, barWidth=0.95,
        checksum=0, quiet=0, humanReadable=0,
    )
    escala = largura / desenho.width
    f.c.saveState()
    f.c.translate(x, PAGINA_A - top - altura)
    f.c.scale(escala, altura / desenho.height)
    desenho.drawOn(f.c, 0, 0)
    f.c.restoreState()


def _qr_estudo(f: Folha, x: float, top: float, lado: float):
    desenho = createBarcodeDrawing(
        "QR", value="DOCUMENTO DE ESTUDO - SEM VALIDADE LEGAL - NAO PAGAVEL",
        barWidth=lado, barHeight=lado,
    )
    f.c.saveState()
    f.c.translate(x, PAGINA_A - top - lado)
    f.c.scale(lado / desenho.width, lado / desenho.height)
    desenho.drawOn(f.c, 0, 0)
    f.c.restoreState()


def _pagina(c: canvas.Canvas, cnpj_fmt: str, nome: str, rotulo_pa: str, vencimento: date,
            pagamento: date, entradas: list, somas: dict, pa_referencia: str, pagina: str):
    f = Folha(c)
    cnpj_num = "".join(ch for ch in cnpj_fmt if ch.isdigit())
    numero = numero_documento(cnpj_num, pa_referencia)
    codigo, linha = codigo_barras(somas["total"], cnpj_num, pa_referencia)
    comp = somas

    _marca_estudo(f)

    # Logo e título
    if LOGO.exists():
        c.drawImage(str(LOGO), 41, PAGINA_A - 106, width=189, height=53, mask="auto")
    f.texto(456, 55, 15, "Documento de Arrecadação", negrito=True, cor=AZUL, alinhamento="center")
    f.texto(456, 72, 15, "do Simples Nacional", negrito=True, cor=AZUL, alinhamento="center")

    # Caixas de identificação
    f.caixa(39, 123, 146, 146, preenchimento=colors.white)
    f.caixa(156, 123, 556, 146, preenchimento=colors.white)
    f.caixa(39, 149, 146, 172, preenchimento=colors.white)
    f.caixa(156, 149, 272, 172, preenchimento=colors.white)
    f.caixa(281, 149, 442, 172, preenchimento=colors.white)
    f.caixa(39, 175, 442, 220, preenchimento=colors.white)
    f.caixa(449, 161, 556, 184, preenchimento=VERDE, borda=VERDE)
    f.caixa(449, 197, 556, 220, preenchimento=VERDE, borda=VERDE)

    f.texto(42, 125, 6, "CNPJ")
    f.texto(159, 125, 6, "Razão Social")
    f.texto(42, 151, 6, "Período de Apuração", cor=AZUL)
    f.texto(160, 151, 6, "Data de Vencimento", cor=AZUL)
    f.texto(284, 151, 6, "Número do Documento", cor=AZUL)
    f.texto(481, 154, 6, "Pagar este documento até", cor=AZUL)
    f.texto(42, 178, 6, "Observações", cor=AZUL)
    f.texto(481, 190, 6, "Valor Total do Documento", cor=AZUL)

    f.texto(142, 135, 9, cnpj_fmt, negrito=True, alinhamento="right")
    f.texto(159, 134, 11, nome[:52], negrito=True)
    # período consolidado ocupa mais espaço: reduz a fonte para caber na caixa
    f.texto(142, 160 if " a " in rotulo_pa else 159, 8 if " a " in rotulo_pa else 11,
            rotulo_pa, negrito=True, alinhamento="right")
    f.texto(268, 159, 11, vencimento.strftime("%d/%m/%Y"), negrito=True, alinhamento="right")
    f.texto(438, 159, 11, numero, negrito=True, alinhamento="right")
    f.texto(552, 167, 14, pagamento.strftime("%d/%m/%Y"), negrito=True,
            cor=colors.white, alinhamento="right")
    f.texto(552, 203, 14, brl(comp["total"]), negrito=True,
            cor=colors.white, alinhamento="right")

    cpf = _formatar_cpf(nome)
    if cpf:
        f.texto(42, 185, 10, f"CPF: {cpf}", negrito=True)
    f.texto(42, 197, 10,
            "Tributos (R$): INSS %s ICMS %s ISS %s"
            % (brl(comp["inss"]), brl(comp["icms"]), brl(comp["iss"])), negrito=True)
    f.texto(42, 209, 10, "PGMEI(Versao:3.18.0)", negrito=True)

    # Composição
    f.caixa(39, 229, 556, 654, borda=AZUL, raio=3)
    f.caixa(39, 227, 556, 241, preenchimento=AZUL, borda=AZUL, raio=3)
    f.texto(43, 231, 7, "Composição do Documento de Arrecadação", negrito=True, cor=colors.white)

    f.texto(44, 253, 7, "Código", negrito=True, cor=AZUL)
    f.texto(74, 253, 7, "Denominação", negrito=True, cor=AZUL)
    for titulo, x in (("Principal", 342), ("Multa", 409), ("Juros", 476), ("Total", 552)):
        f.texto(x, 253, 7, titulo, negrito=True, cor=AZUL, alinhamento="right")

    compacto = len(entradas) > 13
    top = 264
    for t in entradas:
        pa = t["pa"]
        complemento = f"{t['uf']} - {pa[4:6]}/{pa[:4]}" if t["uf"] else f"{pa[4:6]}/{pa[:4]}"
        f.texto(44, top, 7, t["codigo"], mono=True)
        if compacto:
            f.texto(74, top, 7, f"{t['denominacao']}  {complemento}", mono=True)
        else:
            f.texto(74, top, 7, t["denominacao"], mono=True)
            f.texto(74, top + 12, 7, complemento, mono=True)
        deslocamento = 0 if compacto else 2
        for valor, x in ((t["principal"], 342), (t["multa"], 409),
                         (t["juros"], 476), (t["total"], 552)):
            f.texto(x, top + deslocamento, 7, brl(valor), mono=True, alinhamento="right")
        top += 14 if compacto else 26

    f.texto(74, top + 6, 7, "Totais", mono=True, negrito=True)
    for valor, x in ((comp["principal"], 342), (comp["multa"], 409),
                     (comp["juros"], 476), (comp["total"], 552)):
        f.texto(x, top + 8, 7, brl(valor), mono=True, negrito=True, alinhamento="right")

    f.texto(51, 644, 7, "SENDA (Versão:1.8.0)")
    f.texto(275, 644, 7, f"Página:  {pagina.replace(chr(47), ' / ')}")
    f.texto(481, 644, 7, datetime.now().strftime("%d/%m/%Y   %H:%M:%S"))

    # Linha digitável e autenticação
    posicoes = [49, 100, 122, 173, 194, 245, 267, 318]
    for i, (bloco, dv) in enumerate(linha):
        f.texto(posicoes[i * 2], 662, 8, bloco)
        f.texto(posicoes[i * 2 + 1], 662, 8, dv)
    f.texto(421, 661, 10, "AUTENTICAÇÃO MECÂNICA")
    f.texto(49, 676, 7, "DOCUMENTO DE ESTUDO — NÃO PAGÁVEL. Reprodução didática, sem vínculo com a RFB.",
            negrito=True, cor=VERMELHO)

    # Linha de corte
    c.saveState()
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    c.setDash(3, 3)
    c.line(39, PAGINA_A - 708, 556, PAGINA_A - 708)
    c.restoreState()

    # Canhoto
    f.texto(39, 716, 12, "Documento de Arrecadação do Simples Nacional", negrito=True, cor=AZUL)
    f.texto(497, 718, 6, "Pague com o PIX", negrito=True)

    caixas = [(40, 108), (114, 182), (188, 256), (262, 330)]
    for x0, x1 in caixas:
        f.caixa(x0, 733, x1, 743, preenchimento=colors.white, borda=colors.black, raio=1.5)
    posicoes_canhoto = [46, 97, 120, 171, 194, 245, 268, 319]
    for i, (bloco, dv) in enumerate(linha):
        f.texto(posicoes_canhoto[i * 2], 734, 8, bloco)
        f.texto(posicoes_canhoto[i * 2 + 1], 734, 8, dv)

    f.texto(346, 733, 8, "CNPJ:")
    f.texto(409, 733, 8, cnpj_fmt)
    f.texto(346, 747, 8, "Número:")
    f.texto(396, 747, 8, numero)
    f.texto(346, 761, 8, "Pagar até:")
    f.texto(441, 761, 8, pagamento.strftime("%d/%m/%Y"))
    f.texto(346, 775, 8, "Valor:")
    f.texto(461, 775, 8, brl(comp["total"]))

    _barras(f, codigo, 40, 746, 292, 36)
    _qr_estudo(f, 490, 724, 65)
    f.texto(346, 790, 6, "QR Code e código de barras sem validade — documento de estudo.",
            negrito=True, cor=VERMELHO)


def gerar_pdf_das(cnpj: str, nome: str, uf: str, ano: int, periodos: list,
                  data_pagamento: str) -> bytes:
    """Gera um ÚNICO DAS consolidado com os valores de todos os períodos selecionados.

    Regra do PGMEI: "Quando selecionado mais de um período de apuração (PA),
    será gerado um único DAS consolidado contendo os valores de todos os PA".
    """
    try:
        pagamento = datetime.strptime(data_pagamento, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        pagamento = date.today()

    ordenados = sorted(periodos, key=lambda p: p["pa"])
    entradas = []
    for p in ordenados:
        vencimento = datetime.strptime(p["vencimento"], "%d/%m/%Y").date()
        comp = composicao_das(ano, uf or "", vencimento, pagamento)
        for t in comp["tributos"]:
            entradas.append({**t, "pa": p["pa"]})

    somas = {
        "inss": round(sum(t["principal"] for t in entradas if t["codigo"] == "0151"), 2),
        "icms": round(sum(t["principal"] for t in entradas if t["codigo"] == "0083"), 2),
        "iss": round(sum(t["principal"] for t in entradas if t["codigo"] == "0153"), 2),
        "principal": round(sum(t["principal"] for t in entradas), 2),
        "multa": round(sum(t["multa"] for t in entradas), 2),
        "juros": round(sum(t["juros"] for t in entradas), 2),
        "total": round(sum(t["total"] for t in entradas), 2),
    }

    def rotulo(pa):
        return f"{MESES_PT[int(pa[4:6]) - 1]}/{pa[:4]}"

    if len(ordenados) == 1:
        rotulo_pa = rotulo(ordenados[0]["pa"])
    else:
        primeiro, ultimo = ordenados[0]["pa"], ordenados[-1]["pa"]
        rotulo_pa = f"{primeiro[4:6]}/{primeiro[:4]} a {ultimo[4:6]}/{ultimo[:4]}"

    vencimento_doc = max(
        datetime.strptime(p["vencimento"], "%d/%m/%Y").date() for p in ordenados
    )

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(f"DAS {cnpj} - {ano} (documento de estudo)")
    c.setAuthor("PGMEI - clone de estudo")

    _pagina(
        c,
        cnpj_fmt=cnpj,
        nome=nome,
        rotulo_pa=rotulo_pa,
        vencimento=vencimento_doc,
        pagamento=pagamento,
        entradas=entradas,
        somas=somas,
        pa_referencia=ordenados[0]["pa"],
        pagina="1/1",
    )
    c.showPage()
    c.save()
    return buffer.getvalue()


def numero_apuracao(cnpj: str, pa: str) -> str:
    """Número da apuração: base do CNPJ + ano + mês + sequencial."""
    cnpj_num = "".join(ch for ch in cnpj if ch.isdigit())
    seq = (int(cnpj_num[:8] or 0) + int(pa)) % 10000
    return f"{cnpj_num[:8]}{pa}{seq:04d}"


# ---------------------------------------------------------------------------
# PIX (estudo) — BR Code estruturalmente válido com chave inexistente,
# portanto NÃO pagável. Serve apenas para reproduzir a tela de pagamento.

CHAVE_PIX_ESTUDO = "estudo@pgmei.invalido"


def _crc16(payload: str) -> str:
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def _emv(tag: str, valor: str) -> str:
    return f"{tag}{len(valor):02d}{valor}"


def codigo_pix_estudo(valor: float, identificador: str) -> str:
    """BR Code (PIX copia e cola) para a tela de estudo."""
    conta = _emv("00", "br.gov.bcb.pix") + _emv("01", CHAVE_PIX_ESTUDO)
    payload = (
        _emv("00", "01")
        + _emv("01", "12")
        + _emv("26", conta)
        + _emv("52", "0000")
        + _emv("53", "986")
        + _emv("54", f"{valor:.2f}")
        + _emv("58", "BR")
        + _emv("59", "DOCUMENTO DE ESTUDO")
        + _emv("60", "BRASILIA")
        + _emv("62", _emv("05", identificador[:25]))
        + "6304"
    )
    return payload + _crc16(payload)


def qrcode_base64(conteudo: str) -> str:
    """QR Code em PNG base64 (data URI)."""
    import base64
    import qrcode

    qr = qrcode.QRCode(version=None, box_size=8, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(conteudo)
    qr.make(fit=True)
    imagem = qr.make_image(fill_color="#002059", back_color="white")
    buffer = BytesIO()
    imagem.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
