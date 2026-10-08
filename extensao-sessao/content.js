/* DonasPainel — Importador PGMEI em LOTE (roda na sua sessão logada).

   Como funciona: para cada CNPJ da lista, troca o contribuinte ativo via
   POST /Identificacao/Continuar (na área logada normalmente NÃO há captcha),
   lê os anos disponíveis e baixa a tabela de cada ano por POST /emissao,
   enviando o HTML real ao painel (/api/apuracao/importar). Tudo via fetch
   same-origin: os cookies da sessão logada vão automaticamente.

   Se a troca de CNPJ voltar para a tela de identificação (captcha), o CNPJ é
   marcado como "bloqueado" e seguimos para o próximo — nunca martela o site. */
(function () {
  if (window.__dpRunning) return;      // evita execução concorrente no mesmo documento
  window.__dpRunning = true;

  const RAIZ = '/SimplesNacional/Aplicacoes/ATSPO/pgmei.app';
  const DEFAULT_API = 'https://emergent-dasmei.preview.emergentagent.com';
  const PAUSA = 700; // ms entre requisições (educado com a Receita)

  const soDigitos = (v) => (v || '').replace(/\D/g, '');
  const fmt = (c) => c.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, '$1.$2.$3/$4-$5');
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const parse = (html) => new DOMParser().parseFromString(html, 'text/html');

  async function getState() {
    const { estado, config } = await chrome.storage.local.get(['estado', 'config']);
    return { e: estado || {}, api: (((config && config.api) || DEFAULT_API) || '').replace(/\/+$/, '') };
  }
  async function save(e) { await chrome.storage.local.set({ estado: e }); }
  async function log(e, texto, tipo) {
    e.log = [...(e.log || []), { texto, tipo }].slice(-300);
    await save(e);
  }

  function token(doc) {
    const t = doc.querySelector('input[name=__RequestVerificationToken]');
    return t ? t.value : '';
  }
  function temTabela(doc) { return !!doc.querySelector('tr.pa, input[name=pa]'); }
  function ehIdentificacao(doc) {
    return !!doc.querySelector('#cnpj') && /Identificacao\/Continuar/i.test(doc.documentElement.innerHTML);
  }
  function anos(doc) {
    const sel = doc.querySelector('select[name=ano]');
    if (!sel) return [];
    return [...sel.options]
      .map((o) => Number((o.value || o.text || '').trim().slice(0, 4)))
      .filter((a) => a > 2000 && a < 2100)
      .sort((a, b) => b - a);
  }
  function cnpjDaPagina(doc) {
    const m = (doc.body.innerText || '').match(/CNPJ[:\s]*(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})/i);
    return m ? soDigitos(m[1]) : null;
  }

  async function getDoc(path) {
    const r = await fetch(RAIZ + path, { credentials: 'include' });
    return parse(await r.text());
  }
  async function postForm(path, params) {
    const r = await fetch(RAIZ + path, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams(params).toString(),
    });
    return r;
  }

  // Troca o contribuinte ativo. Retorna o doc resultante.
  async function identificar(cnpj) {
    const d1 = await getDoc('/Identificacao');
    const tk = token(d1);
    const params = { cnpj };
    if (tk) params['__RequestVerificationToken'] = tk;
    params['h-captcha-response'] = '';   // na área logada, normalmente ignorado
    params['g-recaptcha-response'] = '';
    const r = await postForm('/Identificacao/Continuar', params);
    return parse(await r.text());
  }

  async function htmlDoAno(ano) {
    const r = await postForm('/emissao', { ano: String(ano) });
    return await r.text();
  }

  async function importarCnpj(e, api, cnpj, precisaIdentificar) {
    if (precisaIdentificar) {
      await log(e, `CNPJ ${fmt(cnpj)}: trocando contribuinte...`);
      const doc = await identificar(cnpj);
      if (ehIdentificacao(doc) && !temTabela(doc) && anos(doc).length === 0) {
        await log(e, `CNPJ ${fmt(cnpj)}: a troca pediu captcha — pulei (precisa resolver o captcha para trocar).`, 'err');
        e.bloqueados = [...(e.bloqueados || []), cnpj];
        return false;
      }
      const detectado = cnpjDaPagina(doc);
      if (detectado && detectado !== cnpj) {
        await log(e, `CNPJ ${fmt(cnpj)}: a sessão ficou em ${fmt(detectado)} — troca não aplicou.`, 'err');
        e.bloqueados = [...(e.bloqueados || []), cnpj];
        return false;
      }
    }

    // CNPJ já identificado (na tela ou após troca): lê os anos e importa
    let doc = await getDoc('/emissao');
    let lista = anos(doc);
    if (!lista.length) {
      const atual = new Date().getFullYear();
      lista = [atual, atual - 1, atual - 2];
    }
    await log(e, `CNPJ ${fmt(cnpj)}: anos ${lista.join(', ')}`);

    let ok = 0;
    for (const ano of lista) {
      if (!e.ativo) break;
      try {
        const html = await htmlDoAno(ano);
        const d = parse(html);
        if (!temTabela(d)) { await log(e, `   ${ano}: sem dados (não optante) — pulando.`); await sleep(PAUSA); continue; }
        const r = await fetch(`${api}/api/apuracao/importar`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cnpj, ano, html }),
        });
        const c = await r.json().catch(() => ({}));
        if (r.ok) {
          ok++;
          await log(e, `   ${ano}: ${c.total_periodos} per., ${(c.em_aberto || []).length} em aberto, devido R$ ${c.total_em_aberto_formatado || '0,00'}`, 'ok');
        } else {
          await log(e, `   ${ano}: ${c.detail || 'falhou'}`, 'err');
        }
      } catch (err) {
        await log(e, `   ${ano}: erro (${err.message})`, 'err');
      }
      await sleep(PAUSA);
    }
    await log(e, `CNPJ ${fmt(cnpj)}: ${ok} ano(s) importado(s).`, ok ? 'ok' : 'err');
    return true;
  }

  (async function () {
    const { e, api } = await getState();
    try {
      if (!e.ativo) return;
      if (!api) { await log(e, 'Configure o endereço do painel.', 'err'); return; }

      let lista = (e.cnpjs || []).map(soDigitos).filter((c) => c.length === 14);
      if (!lista.length) {
        const atual = cnpjDaPagina(document);
        if (!atual) {
          await log(e, 'Cole uma lista de CNPJs no popup, ou abra a emissão de um CNPJ.', 'err');
          e.ativo = false; await save(e); return;
        }
        lista = [atual];
      }
      // remove duplicados preservando ordem
      lista = [...new Set(lista)];
      const atual = cnpjDaPagina(document);  // CNPJ já identificado na tela
      await log(e, `Lote iniciado: ${lista.length} CNPJ(s).`, 'ok');

      let feitos = 0, bloq = 0;
      for (const cnpj of lista) {
        if (!e.ativo) { await log(e, 'Interrompido pelo usuário.', 'err'); break; }
        try {
          const okc = await importarCnpj(e, api, cnpj, cnpj !== atual);
          okc ? feitos++ : bloq++;
        } catch (err) {
          bloq++; await log(e, `CNPJ ${fmt(cnpj)}: falha (${err.message})`, 'err');
        }
        await sleep(PAUSA);
      }
      await log(e, `✓ Concluído! ${feitos} CNPJ(s) OK${bloq ? `, ${bloq} bloqueado(s)` : ''}. Veja os valores no painel.`, 'ok');
      e.ativo = false; await save(e);
    } finally {
      window.__dpRunning = false;
    }
  })();
})();
