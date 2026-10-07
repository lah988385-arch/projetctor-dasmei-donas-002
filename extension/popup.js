const BASE_PGMEI = 'https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/Identificacao';
const API_PADRAO = 'https://pgmei-study.preview.emergentagent.com';

const elCnpj = document.getElementById('cnpj');
const elDe = document.getElementById('de');
const elAte = document.getElementById('ate');
const elAuto = document.getElementById('auto');
const elApi = document.getElementById('api');
const elLog = document.getElementById('log');

const anoAtual = new Date().getFullYear();
for (let a = anoAtual; a >= 2009; a--) {
  elDe.insertAdjacentHTML('beforeend', `<option value="${a}">${a}</option>`);
  elAte.insertAdjacentHTML('beforeend', `<option value="${a}">${a}</option>`);
}
elDe.value = String(anoAtual - 2);
elAte.value = String(anoAtual);

function mascara(valor) {
  const d = (valor || '').replace(/\D/g, '').slice(0, 14);
  return d
    .replace(/^(\d{2})(\d)/, '$1.$2')
    .replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d)/, '.$1/$2')
    .replace(/(\d{4})(\d)/, '$1-$2');
}

elCnpj.addEventListener('input', () => { elCnpj.value = mascara(elCnpj.value); });

function pintarLog(estado) {
  const itens = (estado && estado.log) || [];
  elLog.innerHTML = itens.slice(-40).reverse()
    .map((i) => `<div class="${i.tipo || ''}">${i.texto}</div>`).join('');
}

async function carregar() {
  const { estado, config } = await chrome.storage.local.get(['estado', 'config']);
  elApi.value = (config && config.api) || API_PADRAO;
  if (estado && estado.cnpj) elCnpj.value = mascara(estado.cnpj);
  pintarLog(estado);
}

chrome.storage.onChanged.addListener((mud) => {
  if (mud.estado) pintarLog(mud.estado.newValue);
});

document.getElementById('salvar').addEventListener('click', async () => {
  const api = (elApi.value || API_PADRAO).replace(/\/+$/, '');
  await chrome.storage.local.set({ config: { api } });
  elApi.value = api;
});

document.getElementById('importar').addEventListener('click', async () => {
  const cnpj = elCnpj.value.replace(/\D/g, '');
  if (cnpj.length !== 14) {
    pintarLog({ log: [{ texto: 'Informe os 14 dígitos do CNPJ.', tipo: 'erro' }] });
    return;
  }
  const de = Number(elDe.value);
  const ate = Number(elAte.value);
  const anos = [];
  for (let a = Math.min(de, ate); a <= Math.max(de, ate); a++) anos.push(a);

  const api = (elApi.value || API_PADRAO).replace(/\/+$/, '');
  await chrome.storage.local.set({
    config: { api },
    estado: {
      ativo: true, cnpj, anos, feitos: [], indice: 0, enviarAuto: elAuto.checked,
      tentativas: 0,
      log: [{ texto: `Iniciando ${anos[0]}–${anos[anos.length - 1]} para ${mascara(cnpj)}...` }],
    },
  });
  const [aba] = await chrome.tabs.query({ url: 'https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/*' });
  if (aba) {
    await chrome.tabs.update(aba.id, { active: true, url: BASE_PGMEI });
  } else {
    await chrome.tabs.create({ url: BASE_PGMEI });
  }
});

document.getElementById('parar').addEventListener('click', async () => {
  const { estado } = await chrome.storage.local.get('estado');
  await chrome.storage.local.set({
    estado: { ...(estado || {}), ativo: false, log: [...(((estado || {}).log) || []), { texto: 'Interrompido.' }] },
  });
});

carregar();
