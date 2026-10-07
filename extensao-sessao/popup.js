const $ = (id) => document.getElementById(id);

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

chrome.storage.local.get(["config", "estado"], (d) => {
  if (d.config && d.config.api) $("painel").value = d.config.api;
  if (d.estado) render(d.estado.log);
});

// atualiza o log em tempo real enquanto a extensão trabalha
chrome.storage.onChanged.addListener((changes) => {
  if (changes.estado) render(changes.estado.newValue && changes.estado.newValue.log);
});

$("importar").addEventListener("click", async () => {
  const api = $("painel").value.trim().replace(/\/+$/, "");
  if (!api) { render([{ texto: "Preencha o endereço do painel.", tipo: "err" }]); return; }

  await chrome.storage.local.set({
    config: { api },
    estado: { ativo: true, log: [{ texto: "Iniciando...", tipo: "ok" }] },
  });

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/receita\.fazenda\.gov\.br/.test(tab.url || "")) {
    render([{ texto: "Abra a aba do PGMEI (receita.fazenda.gov.br) e tente de novo.", tipo: "err" }]);
    return;
  }
  // dispara o worker imediatamente na aba atual; o loop segue via content_script
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
