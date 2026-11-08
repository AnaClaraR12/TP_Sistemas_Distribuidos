import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { mensagemDeErro } from "../api/cliente";
import { useAuth } from "../auth/AuthContext";
import { Alerta } from "../components/comuns";

export default function Login() {
  const { entrar, usuario } = useAuth();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const navegar = useNavigate();
  const local = useLocation();

  if (usuario) return <Navigate to="/dashboard" replace />;

  async function enviar(e) {
    e.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await entrar(email.trim(), senha);
      navegar(local.state?.de || "/dashboard", { replace: true });
    } catch (err) {
      setErro(mensagemDeErro(err));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="cartao estreito">
      <h1>Entrar</h1>
      <form className="form" onSubmit={enviar}>
        <label htmlFor="email">E-mail institucional</label>
        <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="senha">Senha</label>
        <input id="senha" type="password" autoComplete="current-password" required value={senha} onChange={(e) => setSenha(e.target.value)} />
        <Alerta>{erro}</Alerta>
        <button type="submit" disabled={enviando}>
          {enviando ? "Entrando…" : "Entrar"}
        </button>
      </form>
      <p className="mudo">
        <a href="/api/auth/contas/password/reset/">Esqueci minha senha</a> · Contas são criadas pela coordenação.
      </p>
    </section>
  );
}
