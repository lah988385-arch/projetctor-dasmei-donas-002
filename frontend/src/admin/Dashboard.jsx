import { useEffect, useState } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { Users, UserCheck, FileText, Search, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { api, fmtData } from "./api";

function Card({ icon: Icon, rotulo, valor, sub, accent, testid }) {
  return (
    <div data-testid={testid} className="bg-slate-900 border border-slate-800 rounded-xl p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wide">{rotulo}</span>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${accent}`}>
          <Icon className="w-4 h-4" />
        </div>
      </div>
      <div className="text-3xl font-bold text-white">{valor}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

export default function Dashboard() {
  const [dados, setDados] = useState(null);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    api.get("/dashboard").then(({ data }) => setDados(data)).finally(() => setCarregando(false));
  }, []);

  if (carregando) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400" data-testid="dashboard-loading">
        <Loader2 className="w-6 h-6 animate-spin" />
      </div>
    );
  }
  if (!dados) return <div className="text-slate-400">Não foi possível carregar os dados.</div>;

  return (
    <div data-testid="admin-dashboard" className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-white">Dashboard</h2>
        <p className="text-sm text-slate-400">Visão geral dos acessos e documentos gerados.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card testid="card-acessos" icon={Users} rotulo="Acessos" valor={dados.total_acessos}
          sub={`${dados.acessos_hoje} hoje`} accent="bg-sky-500/15 text-sky-400" />
        <Card testid="card-validos" icon={UserCheck} rotulo="CNPJs válidos" valor={dados.acessos_validos}
          sub="identificações aceitas" accent="bg-emerald-500/15 text-emerald-400" />
        <Card testid="card-consultas" icon={Search} rotulo="Consultas" valor={dados.total_consultas}
          sub="consultas de CNPJ" accent="bg-violet-500/15 text-violet-400" />
        <Card testid="card-faturas" icon={FileText} rotulo="Faturas geradas" valor={dados.total_faturas}
          sub={`${dados.faturas_mes} neste mês`} accent="bg-amber-500/15 text-amber-400" />
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5" data-testid="dashboard-chart">
        <h3 className="text-sm font-semibold text-white mb-4">Acessos nos últimos 14 dias</h3>
        <div className="w-full h-[260px]">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            <AreaChart data={dados.serie_acessos} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="gAcessos" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
              <XAxis dataKey="dia" stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
              <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, color: "#fff" }}
                labelStyle={{ color: "#94a3b8" }}
              />
              <Area type="monotone" dataKey="acessos" stroke="#10b981" strokeWidth={2} fill="url(#gAcessos)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-5" data-testid="dashboard-recentes">
        <h3 className="text-sm font-semibold text-white mb-4">Últimos acessos</h3>
        <div className="space-y-1">
          {dados.recentes.length === 0 && <p className="text-sm text-slate-500">Nenhum acesso registrado.</p>}
          {dados.recentes.map((r, i) => (
            <div key={i} className="flex items-center justify-between py-2 border-b border-slate-800/60 last:border-0">
              <div className="flex items-center gap-2">
                {r.valido ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ) : (
                  <XCircle className="w-4 h-4 text-red-400" />
                )}
                <span className="text-sm text-slate-200 font-mono">{r.cnpj || "—"}</span>
              </div>
              <span className="text-xs text-slate-500">{fmtData(r.em)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
