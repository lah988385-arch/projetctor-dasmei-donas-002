// Utilitários de CNPJ para a tela do PGMEI (estudo de front-end).

export function onlyDigits(value: string): string {
  return (value || "").replace(/\D/g, "");
}

// Aplica a máscara 00.000.000/0000-00 progressivamente enquanto digita.
export function maskCNPJ(value: string): string {
  const d = onlyDigits(value).slice(0, 14);
  let out = d;
  if (d.length > 2) out = `${d.slice(0, 2)}.${d.slice(2)}`;
  if (d.length > 5) out = `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5)}`;
  if (d.length > 8) out = `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8)}`;
  if (d.length > 12) out = `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
  return out;
}

// Valida os dígitos verificadores do CNPJ.
export function isValidCNPJ(value: string): boolean {
  const n = onlyDigits(value);
  if (n.length !== 14) return false;
  if (/^(\d)\1{13}$/.test(n)) return false; // rejeita sequências repetidas

  const calcDV = (base: string, pesos: number[]): number => {
    const soma = base
      .split("")
      .reduce((acc, dig, i) => acc + parseInt(dig, 10) * pesos[i], 0);
    const resto = soma % 11;
    return resto < 2 ? 0 : 11 - resto;
  };

  const pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  const pesos2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2];
  const dv1 = calcDV(n.slice(0, 12), pesos1);
  const dv2 = calcDV(n.slice(0, 12) + String(dv1), pesos2);
  return n[12] === String(dv1) && n[13] === String(dv2);
}
