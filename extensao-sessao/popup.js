const $ = (id) => document.getElementById(id);
const API_PADRAO = "https://emergent-dasmei.preview.emergentagent.com";

function render(log) {
  const el = $("log");
  el.innerHTML = "";
  (log || []).forEach((l) => {
    const d = document.createElement("div");
    if (l.tipo) d.className = l.tipo;
    d.textContent = l.texto;
    el.appendChild(d);
  });
  el.scrollTop = el.scrollHeight;
}

function parseCnpjs(txt) {
  return (txt || "")
    .split(/[\s,;]+/)
    .map((s) => s.replace(/\D/g, ""))
    .filter((s) => s.length === 14);
}

chrome.storage.local.get(["config", "estado"], (d) => {
  $("painel").value = (d.config && d.config.api) || API_PADRAO;
  if (d.config && Array.isArray(d.config.cnpjs)) $("cnpjs").value = d.config.cnpjs.join("\n");
  if (d.estado) render(d.estado.log);
});

chrome.storage.onChanged.addListener((changes) => {
  if (changes.estado) render(changes.estado.newValue && changes.estado.newValue.log);
});

$("importar").addEventListener("click", async () => {
  const api = $("painel").value.trim().replace(/\/+$/, "");
  if (!api) { render([{ texto: "Preencha o endereço do painel.", tipo: "err" }]); return; }

  const cnpjs = parseCnpjs($("cnpjs").value);

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/receita\.fazenda\.gov\.br/.test(tab.url || "")) {
    render([{ texto: "Abra a aba do PGMEI logado (receita.fazenda.gov.br) e tente de novo.", tipo: "err" }]);
    return;
  }

  await chrome.storage.local.set({
    config: { api, cnpjs },
    estado: {
      ativo: true,
      fila: cnpjs,
      idx: 0,
      iniciado: false,
      tent: {},
      log: [{ texto: cnpjs.length ? `Preparando ${cnpjs.length} CNPJ(s)...` : "Importando o CNPJ aberto...", tipo: "ok" }],
    },
  });

  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
  } catch (e) {
    render([{ texto: "Erro ao iniciar: " + e.message, tipo: "err" }]);
  }
});

$("parar").addEventListener("click", async () => {
  const { estado } = await chrome.storage.local.get("estado");
  await chrome.storage.local.set({ estado: { ...(estado || {}), ativo: false } });
});
