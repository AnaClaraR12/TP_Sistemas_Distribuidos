import axios from "axios";

/**
 * Cliente HTTP único: todas as chamadas passam pelo gateway (mesma origem).
 * - injeta Authorization: Bearer <access> (token mantido só em memória);
 * - em 401 tenta UM refresh automático (refresh guardado em sessionStorage);
 * - nunca loga tokens.
 */
const CHAVE_REFRESH = "tcc.refresh";

let accessToken = null;
let aoDeslogar = () => {};
let refreshEmAndamento = null;

export const api = axios.create({ baseURL: "/", timeout: 30000 });

export function definirSessao({ access, refresh }) {
  accessToken = access || null;
  try {
    if (refresh) sessionStorage.setItem(CHAVE_REFRESH, refresh);
  } catch {
    /* armazenamento indisponível: sessão só em memória */
  }
}

export function limparSessao() {
  accessToken = null;
  try {
    sessionStorage.removeItem(CHAVE_REFRESH);
  } catch {
    /* ignore */
  }
}

export function refreshSalvo() {
  try {
    return sessionStorage.getItem(CHAVE_REFRESH);
  } catch {
    return null;
  }
}

export function registrarLogout(fn) {
  aoDeslogar = fn;
}

export async function renovarToken() {
  const refresh = refreshSalvo();
  if (!refresh) throw new Error("sem refresh");
  if (!refreshEmAndamento) {
    refreshEmAndamento = axios
      .post("/api/auth/token/refresh/", { refresh })
      .then((r) => {
        definirSessao(r.data);
        return r.data.access;
      })
      .finally(() => {
        refreshEmAndamento = null;
      });
  }
  return refreshEmAndamento;
}

api.interceptors.request.use((config) => {
  if (accessToken && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  async (erro) => {
    const original = erro.config;
    const status = erro.response?.status;
    const rotaDeToken = original?.url?.includes("/api/auth/token/");
    if (status === 401 && original && !original._repetida && !rotaDeToken && refreshSalvo()) {
      original._repetida = true;
      try {
        const novo = await renovarToken();
        original.headers.Authorization = `Bearer ${novo}`;
        return api(original);
      } catch {
        limparSessao();
        aoDeslogar();
      }
    }
    return Promise.reject(erro);
  },
);

/** Extrai a mensagem do JSON de erro padrão {"codigo","mensagem","detalhes"}. */
export function mensagemDeErro(erro) {
  const d = erro?.response?.data;
  if (d?.mensagem) {
    const det = d.detalhes && typeof d.detalhes === "object" ? d.detalhes : {};
    const campos = Object.entries(det)
      .filter(([, v]) => Array.isArray(v) && typeof v[0] === "string")
      .map(([k, v]) => `${k}: ${v.join(" ")}`);
    return campos.length ? `${d.mensagem} (${campos.join("; ")})` : d.mensagem;
  }
  if (erro?.response?.status === 413) return "Arquivo muito grande.";
  if (erro?.message === "Network Error") return "Não foi possível conectar ao servidor.";
  return erro?.message || "Erro inesperado.";
}

/** Baixa um arquivo protegido (com Bearer) e abre em nova aba. */
export async function abrirArquivoProtegido(url) {
  const r = await api.get(url, { responseType: "blob" });
  const objeto = URL.createObjectURL(r.data);
  window.open(objeto, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(objeto), 60000);
}
