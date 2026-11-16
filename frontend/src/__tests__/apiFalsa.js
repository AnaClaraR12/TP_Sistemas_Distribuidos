import axios, { AxiosError } from "axios";
import { api } from "../api/cliente";

// Substitui o adaptador HTTP do axios: as requisições passam pelos interceptadores
// de verdade, mas a resposta vem da tabela `rotas` ("GET /api/x/": dados).
// Um valor do tipo { status, data } com status >= 400 vira erro HTTP.

const adaptadoresOriginais = { api: api.defaults.adapter, axios: axios.defaults.adapter };

export function falha(status, data = {}) {
  return { __falha: true, status, data };
}

export function resposta(data, { status = 200, headers = {} } = {}) {
  return { __resposta: true, data, status, headers };
}

export function simularApi(rotas, { cliente = api } = {}) {
  const chamadas = [];
  cliente.defaults.adapter = async (config) => {
    const metodo = config.method.toUpperCase();
    const chave = `${metodo} ${config.url}`;
    let corpo = config.data;
    if (typeof corpo === "string") {
      try {
        corpo = JSON.parse(corpo);
      } catch {
        /* não era JSON */
      }
    }
    const headers = config.headers?.toJSON ? config.headers.toJSON() : { ...config.headers };
    chamadas.push({ metodo, url: config.url, params: config.params, corpo, headers });
    if (!(chave in rotas)) {
      const resposta = { status: 404, data: { codigo: "nao_encontrado", mensagem: `sem rota falsa: ${chave}` }, headers: {}, config };
      throw new AxiosError("404", "ERR_BAD_REQUEST", config, null, resposta);
    }
    let valor = rotas[chave];
    if (typeof valor === "function") valor = await valor(config, corpo);
    if (valor?.__falha) {
      const resposta = { status: valor.status, data: valor.data, headers: {}, config };
      throw new AxiosError(String(valor.status), "ERR_BAD_REQUEST", config, null, resposta);
    }
    if (valor?.__resposta) {
      return { data: valor.data, status: valor.status, statusText: "OK", headers: valor.headers, config };
    }
    return { data: valor, status: 200, statusText: "OK", headers: {}, config };
  };
  return chamadas;
}

export function restaurarApi() {
  api.defaults.adapter = adaptadoresOriginais.api;
  axios.defaults.adapter = adaptadoresOriginais.axios;
}

export const pagina = (results) => ({ count: results.length, next: null, previous: null, results });
