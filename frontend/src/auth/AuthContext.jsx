import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, definirSessao, limparSessao, refreshSalvo, registrarLogout, renovarToken } from "../api/cliente";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [usuario, setUsuario] = useState(null);
  const [config, setConfig] = useState(null);
  const [carregando, setCarregando] = useState(true);

  const carregarPerfil = useCallback(async () => {
    const [me, cfg] = await Promise.all([api.get("/api/auth/me/"), api.get("/api/auth/me/dashboard-config/")]);
    setUsuario(me.data);
    setConfig(cfg.data);
  }, []);

  const sair = useCallback(async () => {
    try {
      await api.post("/api/auth/logout/", { refresh: refreshSalvo() });
    } catch {
      /* já expirado */
    }
    limparSessao();
    setUsuario(null);
    setConfig(null);
  }, []);

  useEffect(() => {
    registrarLogout(() => {
      setUsuario(null);
      setConfig(null);
    });
    // restaura a sessão a partir do refresh da aba (sessionStorage)
    (async () => {
      if (refreshSalvo()) {
        try {
          await renovarToken();
          await carregarPerfil();
        } catch {
          limparSessao();
        }
      }
      setCarregando(false);
    })();
  }, [carregarPerfil]);

  const entrar = useCallback(
    async (email, senha) => {
      const r = await api.post("/api/auth/token/", { email, password: senha });
      definirSessao(r.data);
      await carregarPerfil();
    },
    [carregarPerfil],
  );

  const valor = useMemo(() => {
    const papel = usuario?.papel;
    return {
      usuario,
      config,
      carregando,
      entrar,
      sair,
      papel,
      alunoId: usuario?.vinculos?.aluno?.id,
      professorId: usuario?.vinculos?.professor?.id,
      temPapel: (...p) => p.includes(papel),
    };
  }, [usuario, config, carregando, entrar, sair]);

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
