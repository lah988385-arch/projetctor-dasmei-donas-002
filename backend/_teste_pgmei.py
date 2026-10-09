"""Teste ponta-a-ponta: consulta real do PGMEI pelo IP brasileiro + 2Captcha."""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import captcha_solver
from pgmei_sessao import Sessao, BASE

CNPJ = os.environ.get("TESTE_CNPJ", "26920383000100")
ANO = int(os.environ.get("TESTE_ANO", "2026"))


def log(*a):
    print("[TESTE]", *a, flush=True)


async def main():
    log("proxy PGMEI =", os.environ.get("PGMEI_PROXY_SERVER"))
    log("abrindo navegador e digitando CNPJ", CNPJ, "...")
    sessao = Sessao(CNPJ)
    try:
        await sessao.abrir()
        log("estado apos abrir:", sessao.estado, "|", sessao.mensagem)

        sitekey, invisible = await captcha_solver.extrair_sitekey(sessao.page)
        log("sitekey:", sitekey, "| invisible:", invisible)
        if not sitekey:
            log("ERRO: sitekey nao encontrado (pagina pode ter bloqueado).")
            html = (await sessao.page.content())[:2000]
            log("trecho HTML:", html[:800])
            return

        url = f"{BASE}/Identificacao"
        log("resolvendo hCaptcha via 2Captcha (usando proxy BR)... pode levar 20-90s")
        token = await captcha_solver.resolver_hcaptcha(url, sitekey, bool(invisible))
        log("token recebido (len):", len(token))

        await captcha_solver.injetar_token(sessao.page, token)
        log("token injetado. Clicando em Continuar...")
        await sessao.enviar_identificacao()

        autent = await sessao.autenticado()
        aviso = await sessao.aviso_site()
        log("AUTENTICADO?", autent)
        log("AVISO DO SITE:", repr(aviso))

        try:
            await sessao.page.screenshot(path="/app/backend/_teste_resultado.jpg", type="jpeg", quality=60)
            log("screenshot salvo em _teste_resultado.jpg")
        except Exception as e:
            log("falha screenshot:", e)

        if autent:
            log(">>> SUCESSO: Receita LIBEROU a consulta pelo IP brasileiro! <<<")
            periodos = await sessao.coletar_ano(ANO)
            log(f"periodos do ano {ANO}:", len(periodos))
            for p in periodos[:6]:
                log("  ", p)
        else:
            log(">>> Ainda bloqueado ou captcha nao aceito. Veja o AVISO acima. <<<")
    except Exception as exc:
        import traceback
        log("EXCECAO:", exc)
        traceback.print_exc()
    finally:
        await sessao.fechar()
        log("fim.")


asyncio.run(main())
