import { useEffect, useState } from "react";
import { Routes, Route, NavLink, useNavigate, Navigate } from "react-router-dom";
import { LayoutDashboard, FileText, Settings, LogOut, ShieldCheck, Loader2 } from "lucide-react";
import { Toaster } from "sonner";
import { api, getToken, clearToken } from "./api";
import Login from "./Login";
import Dashboard from "./Dashboard";
import Faturas from "./Faturas";
import Configuracoes from "./Configuracoes";

const navItens = [
  { to: "/donaspainel", fim: true, icon: LayoutDashboard, label: "Dashboard", testid: "nav-dashboard" },
  { to: "/donaspainel/faturas", icon: FileText, label: "Faturas geradas", testid: "nav-faturas" },
  { to: "/donaspainel/configuracoes", icon: Settings, label: "Configurações", testid: "nav-configuracoes" },
];

function Shell({ usuario, onLogout }) {
  return (
    <div className="min-h-screen bg-slate-950 flex" data-testid="admin-shell">
      <aside className="w-60 shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-slate-800">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
          </div>
          <span className="font-semibold text-white">DonasPainel</span>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {navItens.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.fim}
              data-testid={it.testid}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive ? "bg-emerald-500/15 text-emerald-400" : "text-slate-400 hover:text-white hover:bg-slate-800/60"
                }`
              }
            >
              <it.icon className="w-5 h-5" />
              {it.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-3 border-t border-slate-800">
          <div className="px-3 py-2 text-xs text-slate-500">Logado como <span className="text-slate-300">{usuario}</span></div>
          <button
            data-testid="admin-logout"
            onClick={onLogout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
          >
            <LogOut className="w-5 h-5" /> Sair
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <div className="max-w-5xl mx-auto px-6 py-8">
          <Routes>
            <Route index element={<Dashboard />} />
            <Route path="faturas" element={<Faturas />} />
            <Route path="configuracoes" element={<Configuracoes />} />
            <Route path="*" element={<Navigate to="/donaspainel" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

export default function AdminApp() {
  const [estado, setEstado] = useState("checando"); // checando | autenticado | deslogado
  const [usuario, setUsuario] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    if (!getToken()) {
      setEstado("deslogado");
      return;
    }
    api
      .get("/me")
      .then(({ data }) => {
        setUsuario(data.usuario);
        setEstado("autenticado");
      })
      .catch(() => {
        clearToken();
        setEstado("deslogado");
      });
  }, []);

  const logout = () => {
    clearToken();
    setEstado("deslogado");
    navigate("/donaspainel");
  };

  const aoLogar = (u) => {
    setUsuario(u);
    setEstado("autenticado");
  };

  return (
    <>
      <Toaster position="top-right" theme="dark" richColors />
      {estado === "checando" && (
        <div className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-400">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      )}
      {estado === "deslogado" && <Login onLogin={aoLogar} />}
      {estado === "autenticado" && <Shell usuario={usuario} onLogout={logout} />}
    </>
  );
}
