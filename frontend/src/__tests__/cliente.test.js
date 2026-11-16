import axios from "axios";
import { describe, expect, it, vi } from "vitest";
import { api, definirSessao, mensagemDeErro, refreshSalvo, registrarLogout } from "../api/cliente";
import { falha, simularApi } from "./apiFalsa";

describe("cliente HTTP", () => {
  it("manda o access token no cabeçalho Authorization", async () => {
    const chamadas = simularApi({ "GET /api/x/": { ok: true } });
    definirSessao({ access: "A1", refresh: "R1" });
    await api.get("/api/x/");
    expect(chamadas[0].headers.Authorization).toBe("Bearer A1");
  });

  it("sem sessão não manda Authorization", async () => {
    const chamadas = simularApi({ "GET /api/x/": {} });
    await api.get("/api/x/");
    expect(chamadas[0].headers.Authorization).toBeUndefined();
  });

  it("guarda o refresh na sessionStorage da aba", () => {
    definirSessao({ access: "A1", refresh: "R1" });
    expect(refreshSalvo()).toBe("R1");
  });

  it("em 401 renova o token uma vez e repete a requisição", async () => {
    let tentativas = 0;
    const chamadas = simularApi({
      "GET /api/x/": () => (++tentativas === 1 ? falha(401) : { ok: true }),
    });
    const refresh = vi.spyOn(axios, "post").mockResolvedValue({ data: { access: "A2", refresh: "R2" } });
    definirSessao({ access: "A1", refresh: "R1" });

    const r = await api.get("/api/x/");

    expect(r.data).toEqual({ ok: true });
    expect(refresh).toHaveBeenCalledWith("/api/auth/token/refresh/", { refresh: "R1" });
    expect(chamadas.map((c) => c.headers.Authorization)).toEqual(["Bearer A1", "Bearer A2"]);
    expect(refreshSalvo()).toBe("R2");
  });

  it("duas requisições com 401 ao mesmo tempo disparam um único refresh", async () => {
    const vistos = new Set();
    simularApi({
      "GET /api/a/": (config) => (config.headers.Authorization === "Bearer A2" ? { a: 1 } : falha(401)),
      "GET /api/b/": (config) => (config.headers.Authorization === "Bearer A2" ? { b: 1 } : falha(401)),
    });
    const refresh = vi.spyOn(axios, "post").mockImplementation(async () => {
      vistos.add("refresh");
      await new Promise((ok) => setTimeout(ok, 10));
      return { data: { access: "A2" } };
    });
    definirSessao({ access: "A1", refresh: "R1" });
    const [a, b] = await Promise.all([api.get("/api/a/"), api.get("/api/b/")]);
    expect([a.data, b.data]).toEqual([{ a: 1 }, { b: 1 }]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("refresh falhou: limpa a sessão, avisa o logout e devolve o 401", async () => {
    simularApi({ "GET /api/x/": falha(401) });
    vi.spyOn(axios, "post").mockRejectedValue(new Error("refresh expirado"));
    const aoDeslogar = vi.fn();
    registrarLogout(aoDeslogar);
    definirSessao({ access: "A1", refresh: "R1" });

    await expect(api.get("/api/x/")).rejects.toMatchObject({ response: { status: 401 } });
    expect(aoDeslogar).toHaveBeenCalled();
    expect(refreshSalvo()).toBeNull();
  });

  it("não tenta refresh em 401 da própria rota de token", async () => {
    simularApi({ "POST /api/auth/token/": falha(401, { mensagem: "Credenciais inválidas." }) });
    const refresh = vi.spyOn(axios, "post");
    definirSessao({ access: "A1", refresh: "R1" });
    await expect(api.post("/api/auth/token/", {})).rejects.toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("não tenta refresh quando não há refresh salvo", async () => {
    simularApi({ "GET /api/x/": falha(401) });
    const refresh = vi.spyOn(axios, "post");
    await expect(api.get("/api/x/")).rejects.toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("mensagemDeErro", () => {
  const erro = (status, data) => ({ response: { status, data } });

  it("usa a mensagem do formato padrão da API", () => {
    expect(mensagemDeErro(erro(409, { codigo: "x", mensagem: "Regra violada.", detalhes: {} }))).toBe("Regra violada.");
  });

  it("acrescenta erros de validação por campo", () => {
    const e = erro(400, { mensagem: "Dados inválidos.", detalhes: { titulo: ["Obrigatório."], outro: { x: 1 } } });
    expect(mensagemDeErro(e)).toBe("Dados inválidos. (titulo: Obrigatório.)");
  });

  it("413 sem corpo vira 'Arquivo muito grande.'", () => {
    expect(mensagemDeErro(erro(413, "<html>"))).toBe("Arquivo muito grande.");
  });

  it("falha de rede", () => {
    expect(mensagemDeErro({ message: "Network Error" })).toBe("Não foi possível conectar ao servidor.");
  });

  it("qualquer outra coisa", () => {
    expect(mensagemDeErro({ message: "timeout of 30000ms exceeded" })).toBe("timeout of 30000ms exceeded");
    expect(mensagemDeErro(undefined)).toBe("Erro inesperado.");
  });
});
