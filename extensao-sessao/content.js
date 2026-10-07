/* DonasPainel — worker que roda na SUA sessão logada do PGMEI.
   Lê a tabela JÁ autenticada e envia o HTML de cada ano ao painel.

   POR QUE O POST DIRETO: o combo de ano da Receita é um bootstrap-select
   (o <select name=ano> real fica escondido com tabindex=-98). Mexer no valor
   por código ou clicar no widget NÃO sincroniza o estado dele, então o
   formulário ia sem o ano e a Receita respondia "É necessário selecionar o
   ano-calendário" — gerando loop infinito.
   O form é um POST simples (action=/.../pgmei.app/emissao, campo "ano", sem
   token antifalsificação), então montamos o POST na mão: determinístico.
   Há travas anti-loop para nunca martelar o site da Receita. */

/* IIFE: escopo próprio. Sem isto, a 2ª injeção do arquivo no mesmo documento
   (content_scripts + executeScript) estoura "Identifier already declared" e o
   script morre antes de logar qualquer coisa. */
(function () {

const MAX_TENTATIVAS_ANO = 2;   // tentativas por ano
const MAX_PASSOS = 60;          // recargas totais por importação

async function lerEstado() {
  const { estado, config } = await chrome.storage.local.get(['estado', 'config']);
  return { estado, api: ((config && config.api) || '').replace(/\/+$/, '') };
}
async function gravar(estado) { await chrome.storage.local.set({ estado }); }
async function logar(estado, texto, tipo) {
  estado.log = [...(estado.log || []), { texto, tipo }].slice(-80);
  await gravar(estado);
}
async function parar(estado, texto, tipo = 'erro') {
  estado.ativo = false;
  await logar(estado, texto, tipo);
}

const soDigitos = (v) => (v || '').replace(/\D/g, '');
const fmtCnpj = (c) => c.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, '$1.$2.$3/$4-$5');

function selectAno() {
  return document.querySelector('select[name=ano], #anoCalendarioSelect, #ano');
}
function tabelaNaTela() {
  return !!document.querySelector('tr.pa, input[name=pa]');
}
function alertaDaPagina() {
  const alvos = [...document.querySelectorAll('[class*="alert"], [class*="erro"], [role=alert]')]
    .map((a) => (a.innerText || '').trim())
    .filter((t) => t && t.length < 300 && !/JavaScript/i.test(t));
  if (alvos.length) return alvos[alvos.length - 1];
  // rede de segurança: mensagens típicas da Receita sem classe de alerta
  const m = document.body.innerText
    .match(/(n[ãa]o\s+optante[^.\n]{0,80}|necess[áa]rio\s+selecionar[^.\n]{0,60})/i);
  return m ? m[1].trim() : '';
}
function detectarCnpj() {
  const m = document.body.innerText
    .match(/CNPJ[:\s]*(\d{2}\.?\d{3}\.?\d{3}\/?\d{4}-?\d{2})/i);
  return m ? soDigitos(m[1]) : null;
}
function anoDaPagina() {
  const pa = document.querySelector('input[name=pa]');
  if (pa && /^\d{6}$/.test(pa.value)) return Number(pa.value.slice(0, 4));
  const sel = selectAno();
  const v = sel && (sel.value || '').trim();
  if (v && /^\d{4}/.test(v)) return Number(v.slice(0, 4));
  return null;
}
function anosDoSeletor() {
  const sel = selectAno();
  if (!sel) return [];
  return [...sel.options]
    .map((o) => Number(((o.value || o.text || '').trim()).slice(0, 4)))
    .filter((a) => a > 2000 && a < 2100)
    .sort((a, b) => b - a); // mais recente primeiro
}

/* Monta e envia o POST do ano na mão — sem depender do bootstrap-select. */
function postarAno(ano) {
  const sel = selectAno();
  const original = (sel && sel.closest('form'))
    || document.querySelector('form[action*="emissao"]');
  const action = (original && original.getAttribute('action'))
    || '/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/emissao';

  const f = document.createElement('form');
  f.method = 'post';
  f.action = action;
  f.style.display = 'none';

  // replica eventuais campos hidden (tokens) do form original
  if (original) {
    original.querySelectorAll('input[type=hidden]').forEach((h) => {
      if (!h.name || h.name === 'ano') return;
      const i = document.createElement('input');
      i.type = 'hidden'; i.name = h.name; i.value = h.value;
      f.appendChild(i);
    });
  }
  const inp = document.createElement('input');
  inp.type = 'hidden'; inp.name = 'ano'; inp.value = String(ano);
  f.appendChild(inp);

  document.body.appendChild(f);
  f.submit();
}

async function proximoAno(estado) {
  const pendentes = (estado.anos || []).filter((a) => !(estado.feitos || []).includes(a));
  if (!pendentes.length) {
    const ok = (estado.importados || []).length;
    await parar(estado, `✓ Concluído! ${ok} ano(s) importado(s). Veja os valores no painel.`, 'ok');
    return;
  }
  const ano = pendentes[0];
  estado.anoAtual = ano;
  await logar(estado, `Abrindo ${ano}...`);
  await gravar(estado);
  setTimeout(() => postarAno(ano), 300);
}

async function importarAnoAtual(estado, api) {
  const ano = anoDaPagina();
  if (!ano) { await parar(estado, 'Não identifiquei o ano desta tela.'); return; }
  if ((estado.feitos || []).includes(ano)) { estado.anoAtual = null; return proximoAno(estado); }

  await logar(estado, `Lendo ${ano}...`);
  try {
    const r = await fetch(`${api}/api/apuracao/importar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cnpj: estado.cnpj, ano, html: document.documentElement.outerHTML }),
    });
    const c = await r.json().catch(() => ({}));
    if (!r.ok) {
      await logar(estado, `${ano}: ${c.detail || 'falhou'}`, 'erro');
    } else {
      estado.importados = [...(estado.importados || []), ano];
      await logar(estado,
        `${ano}: ${c.total_periodos} período(s), ${c.em_aberto.length} em aberto, devido R$ ${c.total_em_aberto_formatado}`, 'ok');
    }
  } catch (e) {
    await logar(estado, `${ano}: falha ao enviar (${e.message})`, 'erro');
  }

  estado.feitos = [...(estado.feitos || []), ano];
  estado.anoAtual = null;
  await gravar(estado);
  return proximoAno(estado);
}

/* Auto-descoberta: manda o mapa da aplicação autenticada (forms, campos, links)
   para o painel. Serve para montar o "Modo API" sem adivinhar endpoints e sem
   exigir nenhuma ação do usuário. Roda uma vez por página, em silêncio. */
/* Explora as rotas do próprio app autenticado via fetch (same-origin: os cookies
   vão automaticamente) e manda o mapa de cada uma. Objetivo: descobrir se existe
   algum ponto de troca de CNPJ sem precisar de nenhuma ação do usuário. */
async function explorarRotas(api) {
  const RAIZ = '/SimplesNacional/Aplicacoes/ATSPO/pgmei.app';
  const rotas = ['/Home/inicio', '/consulta/extrato', '/consulta/pendencia',
                 '/consulta/dasEmitidos', '/identificacao', '/Identificacao'];
  for (const rota of rotas) {
    try {
      const r = await fetch(RAIZ + rota, { credentials: 'include' });
      const txt = await r.text();
      const doc = new DOMParser().parseFromString(txt, 'text/html');
      const forms = [...doc.querySelectorAll('form')].slice(0, 20).map((f) => ({
        action: f.getAttribute('action') || '',
        method: (f.getAttribute('method') || 'get').toLowerCase(),
        id: f.id || '',
        campos: [...f.querySelectorAll('input,select,textarea')].slice(0, 30).map((c) => ({
          nome: c.name || '', tipo: (c.tagName === 'SELECT' ? 'select' : (c.type || 'text')), id: c.id || '',
        })),
      }));
      const links = [...doc.querySelectorAll('a[href]')].slice(0, 60).map((a) => ({
        href: a.getAttribute('href') || '', texto: (a.innerText || a.textContent || '').trim().slice(0, 80),
      }));
      await fetch(`${api}/api/extensao/mapa`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: 'EXPLORADA ' + rota + ' [' + r.status + ']',
          titulo: (doc.title || '').slice(0, 200), forms, links,
        }),
      });
      await new Promise((s) => setTimeout(s, 1200)); // espaçamento educado
    } catch (e) { /* silencioso */ }
  }
}

async function enviarMapa(api) {
  try {
    const forms = [...document.querySelectorAll('form')].slice(0, 40).map((f) => ({
      action: f.getAttribute('action') || '',
      method: (f.getAttribute('method') || 'get').toLowerCase(),
      id: f.id || '',
      campos: [...f.querySelectorAll('input,select,textarea')].slice(0, 40).map((c) => ({
        nome: c.name || '',
        tipo: (c.tagName === 'SELECT' ? 'select' : (c.type || 'text')),
        id: c.id || '',
        opcoes: c.tagName === 'SELECT'
          ? [...c.options].slice(0, 30).map((o) => ((o.value || o.text || '').trim()))
          : undefined,
      })),
    }));
    const links = [...document.querySelectorAll('a[href]')].slice(0, 120).map((a) => ({
      href: a.getAttribute('href') || '',
      texto: (a.innerText || '').trim().slice(0, 80),
    }));
    await fetch(`${api}/api/extensao/mapa`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: location.href, titulo: document.title, forms, links }),
    });
  } catch (e) { /* silencioso: nunca atrapalha a importação */ }
}

(async function () {
  const { estado, api } = await lerEstado();
  if (!estado || !estado.ativo) return;

  // evita rodar duas vezes no MESMO documento (injeção dupla)
  if (window.__dpRodou) return;
  window.__dpRodou = true;

  enviarMapa(api);      // mapa da página atual
  explorarRotas(api);   // varre as rotas do app sozinha

  // trava global: nunca martelar o site da Receita
  estado.passos = (estado.passos || 0) + 1;
  if (estado.passos > MAX_PASSOS) {
    await parar(estado, 'Parei por segurança (limite de passos atingido).');
    return;
  }
  await gravar(estado);

  if (!api) { await parar(estado, 'Configure o endereço do painel.'); return; }

  if (document.querySelector('#cnpj') && !selectAno() && !tabelaNaTela()) {
    await parar(estado, 'Você está na tela de identificação. Faça login, abra "Emitir Guia (DAS)" de um CNPJ e clique em Importar.');
    return;
  }

  if (!estado.cnpj) {
    const cnpj = detectarCnpj();
    if (!cnpj) { await parar(estado, 'Não achei o CNPJ na tela. Abra a emissão de um CNPJ.'); return; }
    estado.cnpj = cnpj;
    await logar(estado, `CNPJ ${fmtCnpj(cnpj)} detectado.`, 'ok');
  }

  if (!estado.anos || !estado.anos.length) {
    let anos = anosDoSeletor();
    if (!anos.length) { const a = anoDaPagina(); anos = a ? [a] : []; }
    if (!anos.length) { await parar(estado, 'Não achei os anos disponíveis nesta tela.'); return; }
    estado.anos = anos;
    estado.feitos = [];
    estado.importados = [];
    estado.tent = {};
    await logar(estado, `Anos a importar: ${anos.join(', ')}`);
    await gravar(estado);
  }

  // tabela na tela -> importa; senão trata o alerta e vai pro próximo ano
  if (tabelaNaTela()) return importarAnoAtual(estado, api);

  // Voltamos de um POST e NÃO há tabela: este ano simplesmente não tem dados
  // (ex.: "Contribuinte não optante pelo SIMEI neste ano-calendário").
  // Marca como feito na PRIMEIRA vez e segue — garante progresso, sem loop.
  const alerta = alertaDaPagina();
  if (estado.anoAtual) {
    const ano = estado.anoAtual;
    estado.feitos = [...(estado.feitos || []), ano];
    await logar(estado, `${ano}: ${alerta || 'sem dados para este ano'} — pulando.`, 'erro');
    estado.anoAtual = null;
    await gravar(estado);
  }

  return proximoAno(estado);
})();

})();  // fim do IIFE
