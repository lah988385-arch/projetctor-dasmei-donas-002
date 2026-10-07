import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, User, Loader2, ShieldCheck } from "lucide-react";
import { api, setToken, formatApiError } from "./api";

export default function Login({ onLogin }) {
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [carregando, setCarregando] = useState(false);
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setErro("");
    setCarregando(true);
    try {
      const { data } = await api.post("/login", { usuario, senha });
      setToken(data.token);
      onLogin && onLogin(data.usuario);
      navigate("/donaspainel");
    } catch (err) {
      setErro(formatApiError(err.response?.data?.detail) || err.message);
    } finally {
      setCarregando(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4" data-testid="admin-login-page">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-emerald-500/10 blur-3xl" />
        <div className="absolute -bottom-24 -right-24 w-96 h-96 rounded-full bg-emerald-500/10 blur-3xl" />
      </div>
      <form
        onSubmit={submit}
        className="relative w-full max-w-sm bg-slate-900/80 backdrop-blur border border-slate-800 rounded-2xl p-8 shadow-2xl"
        data-testid="admin-login-form"
      >
        <div className="flex items-center gap-3 mb-8">
          <div className="w-11 h-11 rounded-xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center">
            <ShieldCheck className="w-6 h-6 text-emerald-400" />
          </div>
          <div>
            <h1 className="text-lg font-semibold text-white leading-tight">Painel Admin</h1>
            <p className="text-xs text-slate-400">Acesso restrito</p>
          </div>
        </div>

        <label className="block text-xs font-medium text-slate-400 mb-1.5">Usuário</label>
        <div className="relative mb-4">
          <User className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            data-testid="admin-login-usuario"
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            autoComplete="username"
            className="w-full bg-slate-800/70 border border-slate-700 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
            placeholder="donas"
          />
        </div>

        <label className="block text-xs font-medium text-slate-400 mb-1.5">Senha</label>
        <div className="relative mb-5">
          <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            data-testid="admin-login-senha"
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            autoComplete="current-password"
            className="w-full bg-slate-800/70 border border-slate-700 rounded-lg pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 focus:border-emerald-500/50"
            placeholder="••••••••"
          />
        </div>

        {erro && (
          <div data-testid="admin-login-erro" className="mb-4 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            {erro}
          </div>
        )}

        <button
          data-testid="admin-login-submit"
          type="submit"
          disabled={carregando}
          className="w-full bg-emerald-500 hover:bg-emerald-400 disabled:opacity-60 text-slate-950 font-semibold rounded-lg py-2.5 text-sm transition-colors flex items-center justify-center gap-2"
        >
          {carregando && <Loader2 className="w-4 h-4 animate-spin" />}
          {carregando ? "Entrando..." : "Entrar"}
        </button>
      </form>
    </div>
  );
}
