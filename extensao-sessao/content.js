/* DonasPainel — Importador PGMEI em LOTE (modo navegação, sem 2Captcha).

   Dirige a PÁGINA REAL: preenche o CNPJ e clica em "Continuar" — assim o
   hCaptcha invisible passa sozinho no seu navegador logado (igual quando você
   faz na mão). Sem token, sem serviço de captcha. Se aparecer um desafio
   visual, resolva na tela e a extensão continua sozinha.

   Fluxo (máquina de estados por carregamento de página):
   - /Identificacao  -> preenche o próximo CNPJ da fila e envia (captcha real).
   - /emissao (CNPJ já identificado) -> baixa todos os anos via fetch e envia
     ao painel; depois vai para /Identificacao buscar o próximo CNPJ. */
(function () {
  const RAIZ = '/SimplesNacional/Aplicacoes/ATSPO/pgmei.app';
  const DEFAULT_API = 'https://emergent-dasmei.preview.emergentagent.com';
  const MAX_TENT = 2; // tentativas de identificação por CNPJ antes de pular

  const soDigitos = (v) => (v || '').replace(/\D/g, '');
  const fmt = (c) => c.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, '$1.$2.$3/$4-$5');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const parse = (html) => new DOMParser().parseFromString(html, 'text/html');

  async function getS() {
    const { estado, config } = await chrome.storage.local.get(['estado', 'config']);
    return { e: estado || {}, api: (((config && config.api) || DEFAULT_API) || '').replace(/\/+$/, '') };
  }
  async function save(e) { await chrome.storage.local.set({ estado: e }); }
  async function log(e, t, tp) { e.log = [...(e.log || []), { texto: t, tipo: tp }].slice(-300); await save(e); }

  function cnpjDaPagina() {
    const m = (document.body.innerText || '').match(/CNPJ[:\s]*(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})/i);
    return m ? soDigitos(m[1]) : null;
  }
  const naIdentificacao = () => !!document.querySelector('#cnpj') && /Identificacao/i.test(location.pathname);
  function anosDaPagina(doc) {
    const sel = (doc || document).querySelector('select[name=ano]');
    if (!sel) return [];
    return [...sel.options].map((o) => Number((o.value || o.text || '').trim().slice(0, 4)))
      .filter((a) => a > 2000 && a < 2100).sort((a, b) => b - a);
  }
  const temTabela = (html) => /class="pa"|name="pa"/.test(html);

  async function htmlAno(ano) {
    const r = await fetch(RAIZ + '/emissao', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ ano: String(ano) }).toString(),
    });
    return await r.text();
  }

  async function importarAnos(e, api, cnpj) {
    let anos = anosDaPagina();
    if (!anos.length) {
      const r = await fetch(RAIZ + '/emissao', { credentials: 'include' });
      anos = anosDaPagina(parse(await r.text()));
    }
    if (!anos.length) { const y = new Date().getFullYear(); anos = [y, y - 1, y - 2]; }
    await log(e, `CNPJ ${fmt(cnpj)}: anos ${anos.join(', ')}`);
    let ok = 0;
    for (const ano of anos) {
      if (!e.ativo) break;
      try {
        const html = await htmlAno(ano);
        if (!temTabela(html)) { await log(e, `   ${ano}: sem dados — pulando.`); await sleep(350); continue; }
        const r = await fetch(`${api}/api/apuracao/importar`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cnpj, ano, html }),
        });
        const c = await r.json().catch(() => ({}));
        if (r.ok) { ok++; await log(e, `   ${ano}: ${c.total_periodos} per., ${(c.em_aberto || []).length} em aberto, devido R$ ${c.total_em_aberto_formatado || '0,00'}`, 'ok'); }
        else await log(e, `   ${ano}: ${c.detail || 'falhou'}`, 'err');
      } catch (err) { await log(e, `   ${ano}: erro (${err.message})`, 'err'); }
      await sleep(350);
    }
    await log(e, `CNPJ ${fmt(cnpj)}: ${ok} ano(s) importado(s).`, ok ? 'ok' : 'err');
  }

  async function preencherEEnviar(cnpj) {
    const inp = document.querySelector('#cnpj');
    if (!inp) return false;
    inp.focus();
    inp.value = cnpj;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    inp.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
    await sleep(600);
    const btn = document.querySelector(
      '#identificacao button[type=submit], #identificacao input[type=submit], #identificacao .btn-primary, form button[type=submit], button.btn-primary'
    );
    if (!btn) return false;
    btn.click(); // dispara o hCaptcha invisible real do navegador
    return true;
  }

  (async function () {
    const { e, api } = await getS();
    if (!e.ativo) return;

    const fila = (e.fila || []).map(soDigitos).filter((c) => c.length === 14);
    let idx = e.idx || 0;

    // ---- Página de Identificação: trocar para o próximo CNPJ ----
    if (naIdentificacao()) {
      if (!fila.length || idx >= fila.length) { e.ativo = false; await save(e); return; }
      const alvo = fila[idx];
      e.tent = e.tent || {};
      e.tent[alvo] = (e.tent[alvo] || 0) + 1;
      if (e.tent[alvo] > MAX_TENT) {
        await log(e, `CNPJ ${fmt(alvo)}: não consegui trocar (captcha barrou) — pulando.`, 'err');
        e.idx = idx + 1; await save(e);
        if (e.idx < fila.length) { await sleep(500); location.href = RAIZ + '/Identificacao'; }
        else { await log(e, `✓ Concluído.`, 'ok'); e.ativo = false; await save(e); }
        return;
      }
      await log(e, `CNPJ ${fmt(alvo)}: identificando... (se aparecer um captcha visual, resolva na tela)`);
      await save(e);
      await preencherEEnviar(alvo);
      return; // a página vai navegar sozinha após o captcha
    }

    // ---- Página com um CNPJ já identificado (emissão etc.) ----
    const atual = cnpjDaPagina();

    if (!fila.length) {
      if (atual) { await log(e, 'Importando o CNPJ aberto...', 'ok'); await importarAnos(e, api, atual); }
      else await log(e, 'Cole uma lista de CNPJs no popup, ou abra a emissão de um CNPJ.', 'err');
      e.ativo = false; await save(e); return;
    }

    if (!e.iniciado) { e.iniciado = true; await log(e, `Lote iniciado: ${fila.length} CNPJ(s).`, 'ok'); await save(e); }

    const alvo = fila[idx];
    if (atual && atual === alvo) {
      await importarAnos(e, api, alvo);
      e.idx = idx + 1; await save(e);
      if (e.idx < fila.length) { await log(e, 'Próximo CNPJ...'); await sleep(600); location.href = RAIZ + '/Identificacao'; }
      else { await log(e, `✓ Concluído! ${e.idx} CNPJ(s) processado(s). Veja no painel.`, 'ok'); e.ativo = false; await save(e); }
    } else {
      // CNPJ aberto não é o alvo -> ir identificar o alvo
      await sleep(400);
      location.href = RAIZ + '/Identificacao';
    }
  })();
})();
