import { useEffect, useState } from "react";
import { FileText, Loader2 } from "lucide-react";
import { api, fmtData } from "./api";

function fmtCnpj(c) {
  const n = (c || "").replace(/\D/g, "");
  if (n.length !== 14) return c || "—";
  return `${n.slice(0, 2)}.${n.slice(2, 5)}.${n.slice(5, 8)}/${n.slice(8, 12)}-${n.slice(12)}`;
}

export default function Faturas() {
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    api.get("/faturas").then(({ data }) => setDados(data)).finally(() => setCarregando(false));
  }, []);

  if (carregando) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400" data-testid="faturas-loading">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    );
  }

  return (
    <div data-testid="admin-faturas" className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Faturas geradas</h2>
        <p className="text-sm text-slate-400">{dados?.total ?? 0} documento(s) DAS gerado(s).</p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm" data-testid="faturas-tabela">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-b border-slate-800">
              <th className="px-5 py-3 font-medium">CNPJ</th>
              <th className="px-5 py-3 font-medium">Ano</th>
              <th className="px-5 py-3 font-medium">Períodos</th>
              <th className="px-5 py-3 font-medium text-right">Gerado em</th>
            </tr>
          </thead>
          <tbody>
            {(!dados || dados.itens.length === 0) && (
              <tr>
                <td colSpan={4} className="px-5 py-10 text-center text-slate-500">
                  <FileText className="w-8 h-8 mx-auto mb-2 opacity-40" />
                  Nenhuma fatura gerada ainda.
                </td>
              </tr>
            )}
            {dados?.itens.map((f, i) => (
              <tr key={f.id || i} data-testid={`fatura-row-${i}`} className="border-b border-slate-800/60 last:border-0 hover:bg-slate-800/40 transition-colors">
                <td className="px-5 py-3 font-mono text-slate-200">{fmtCnpj(f.cnpj)}</td>
                <td className="px-5 py-3 text-slate-300">{f.ano ?? "—"}</td>
                <td className="px-5 py-3">
                  <span className="inline-flex items-center justify-center min-w-[2rem] px-2 py-0.5 rounded-md bg-amber-500/15 text-amber-400 text-xs font-medium">
                    {f.qtd_periodos}
                  </span>
                  <span className="ml-2 text-xs text-slate-500 font-mono">{(f.periodos || []).slice(0, 4).join(", ")}{(f.periodos || []).length > 4 ? "…" : ""}</span>
                </td>
                <td className="px-5 py-3 text-right text-slate-400">{fmtData(f.em)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
