import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Layout() {
  const { usuario, config, sair } = useAuth();
  const [aberto, setAberto] = useState(false);
  const navegar = useNavigate();

  async function deslogar() {
    await sair();
    navegar("/");
  }

  const menus = config?.menus || [];
  return (
    <>
      <a href="#conteudo" className="pular">
        Pular para o conteúdo
      </a>
      <header className="topo">
        <Link to="/" className="marca">
          📚 Monografias
        </Link>
        <button className="menu-botao" aria-expanded={aberto} aria-controls="menu" onClick={() => setAberto(!aberto)}>
          Menu
        </button>
        <nav id="menu" className={aberto ? "aberto" : ""} aria-label="Principal" onClick={() => setAberto(false)}>
          <NavLink to="/repositorio">Repositório</NavLink>
          {usuario && <NavLink to="/dashboard">Dashboard</NavLink>}
          {menus
            .filter((m) => m.id !== "repositorio")
            .map((m) => (
              <NavLink key={m.id} to={m.rota} end>
                {m.titulo}
              </NavLink>
            ))}
          {usuario ? (
            <span className="usuario">
              <span title={usuario.email}>
                {usuario.nome || usuario.email} · <em>{usuario.papel}</em>
              </span>
              <button className="link" onClick={deslogar}>
                Sair
              </button>
            </span>
          ) : (
            <NavLink to="/login">Entrar</NavLink>
          )}
        </nav>
      </header>
      <main id="conteudo" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="rodape">Sistema Distribuído de Monografias — Sistemas Distribuídos</footer>
    </>
  );
}
