import { useCallback, useEffect, useState } from "react";
import { api, mensagemDeErro } from "../api/cliente";

export function useDebounce(valor, ms = 400) {
  const [atrasado, setAtrasado] = useState(valor);
  useEffect(() => {
    const t = setTimeout(() => setAtrasado(valor), ms);
    return () => clearTimeout(t);
  }, [valor, ms]);
  return atrasado;
}

/** GET com estados de carregamento/erro e função de recarga. */
export function useApi(url, { params, ativo = true } = {}) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [carregando, setCarregando] = useState(false);
  const chave = JSON.stringify(params || {});

  const carregar = useCallback(async () => {
    if (!url || !ativo) return;
    setCarregando(true);
    setErro(null);
    try {
      const r = await api.get(url, { params: JSON.parse(chave) });
      setDados(r.data);
      return r;
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setCarregando(false);
    }
  }, [url, chave, ativo]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  return { dados, erro, carregando, recarregar: carregar, setDados };
}
