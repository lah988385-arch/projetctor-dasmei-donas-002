/* Roda nas páginas do PGMEI oficial, na sessão do próprio usuário.
   Preenche o CNPJ, aguarda o captcha ser resolvido por ele e, já autenticado,
   percorre os anos-calendário enviando o HTML da emissão para o app de estudo. */

const API_PADRAO = 'https://pgmei-study.preview.emergentagent.com';
const MAX_TENTATIVAS = 3;

async function lerEstado() {
  const { estado, config } = await chrome.storage.local.get(['estado', 'config']);
  return { estado, api: ((config && config.api) || API_PADRAO).replace(/\/+$/, '') };
}

async function gravar(estado) {
  await chrome.storage.local.set({ estado });
}

async function logar(estado, texto, tipo) {
  estado.log = [...(estado.log || []), { texto, tipo }].slice(-60);
  await gravar(estado);
}

function digitar(campo, valor) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(campo, valor);
  campo.dispatchEvent(new Event('input', { bubbles: true }));
  campo.dispatchEvent(new Event('change', { bubbles: true }));
  campo.dispatchEvent(new Event('keyup', { bubbles: true }));
}

function anoDaPagina() {
  const pa = document.querySelector('input[name=pa]');
  if (pa && /^\d{6}$/.test(pa.value)) return Number(pa.value.slice(0, 4));
  const sel = document.querySelector('select[name=ano], #ano');
  if (sel && sel.value) return Number(String(sel.value).slice(0, 4));
  return null;
}

function enviarFormulario(elemento) {
  const form = elemento.closest('form') || document.querySelector('form');
  if (!form) return false;
  const botao = form.querySelector('button[type=submit], input[type=submit]');
  if (botao) { botao.click(); return true; }
  if (form.requestSubmit) { form.requestSubmit(); return true; }
  form.submit();
  return true;
}

async function naIdentificacao(estado) {
  const campo = document.querySelector('#cnpj');
  if (!campo) return;
  if (campo.value.replace(/\D/g, '') !== estado.cnpj) digitar(campo, estado.cnpj);

  const alerta = [...document.querySelectorAll('.alert-danger, .alert-warning')]
    .map((a) => a.innerText.trim()).filter((t) => t && !/JavaScript/i.test(t))[0];
  if (alerta) {
    estado.tentativas = (estado.tentativas || 0) + 1;
    await logar(estado, alerta, 'erro');
    if (estado.tentativas >= MAX_TENTATIVAS) {
      estado.ativo = false;
      await logar(estado, 'Resolva o captcha manualmente e clique em Continuar.', 'erro');
    }
    return;
  }

  if (estado.enviarAuto && !estado.enviou) {
    estado.enviou = true;
    await logar(estado, 'CNPJ preenchido. Enviando...');
    setTimeout(() => enviarFormulario(campo), 600);
  } else {
    await logar(estado, 'CNPJ preenchido. Resolva o captcha e clique em Continuar.');
  }
}

async function irParaEmissao(estado) {
  const link = [...document.querySelectorAll('a[href]')]
    .find((a) => /emissao/i.test(a.getAttribute('href')));
  if (!link) {
    await logar(estado, 'Não achei o menu "Emitir Guia de Pagamento (DAS)" nesta tela.', 'erro');
    return;
  }
  await logar(estado, 'Autenticado. Abrindo a emissão de DAS...', 'ok');
  link.click();
}

async function selecionarAno(estado, ano) {
  const sel = document.querySelector('select[name=ano], #ano');
  if (!sel) {
    await logar(estado, 'Não achei o seletor de ano-calendário.', 'erro');
    estado.ativo = false;
    await gravar(estado);
    return;
  }
  const existe = [...sel.options].some((o) => String(o.value) === String(ano));
  if (!existe) {
    estado.feitos = [...(estado.feitos || []), ano];
    await logar(estado, `${ano}: não disponível para este CNPJ.`);
    return proximoAno(estado);
  }
  sel.value = String(ano);
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  await logar(estado, `Abrindo ${ano}...`);
  setTimeout(() => enviarFormulario(sel), 400);
}

async function proximoAno(estado) {
  const pendentes = (estado.anos || []).filter((a) => !(estado.feitos || []).includes(a));
  if (!pendentes.length) {
    estado.ativo = false;
    await logar(estado, 'Concluído. Abra o app de estudo para ver os valores.', 'ok');
    return;
  }
  return selecionarAno(estado, pendentes[0]);
}

async function enviarAnoAtual(estado, api) {
  const ano = anoDaPagina();
  if (!ano) {
    await logar(estado, 'Não consegui identificar o ano desta tela.', 'erro');
    return;
  }
  if ((estado.feitos || []).includes(ano)) return proximoAno(estado);

  await logar(estado, `Lendo ${ano}...`);
  try {
    const resposta = await fetch(`${api}/api/apuracao/importar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cnpj: estado.cnpj, ano, html: document.documentElement.outerHTML }),
    });
    const corpo = await resposta.json();
    if (!resposta.ok) {
      await logar(estado, `${ano}: ${corpo.detail || 'falhou'}`, 'erro');
    } else {
      await logar(estado, `${ano}: ${corpo.total_periodos} período(s), `
        + `${corpo.em_aberto.length} em aberto, devido R$ ${corpo.total_em_aberto_formatado}`, 'ok');
    }
  } catch (erro) {
    await logar(estado, `${ano}: falha ao enviar (${erro.message})`, 'erro');
  }

  estado.feitos = [...(estado.feitos || []), ano];
  await gravar(estado);
  return proximoAno(estado);
}

(async function () {
  const { estado, api } = await lerEstado();
  if (!estado || !estado.ativo) return;

  if (/Identificacao/i.test(location.href) || document.querySelector('#cnpj')) {
    return naIdentificacao(estado);
  }
  estado.enviou = false;
  estado.tentativas = 0;
  if (document.querySelector('tr.pa, input[name=pa]')) return enviarAnoAtual(estado, api);
  if (document.querySelector('select[name=ano], #ano')) return proximoAno(estado);
  return irParaEmissao(estado);
})();
