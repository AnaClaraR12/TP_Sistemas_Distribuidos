import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axios from "axios";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { definirSessao, refreshSalvo } from "../api/cliente";
import { AuthProvider, useAuth } from "../auth/AuthContext";
import RotaProtegida from "../auth/RotaProtegida";
import Layout from "../components/Layout";
import Login from "../pages/Login";
import { falha, simularApi } from "./apiFalsa";

const ALUNA = { id: "u1", email: "ana@ufvjm.edu.br", nome: "Ana", papel: "aluno", vinculos: { aluno: { id: "a1" } } };
const CONFIG = { papel: "aluno", widgets: [], menus: [{ id: "monografias", titulo: "Minhas monografias", rota: "/monografias" }] };

function perfil(usuario = ALUNA, config = CONFIG) {
  return { "GET /api/auth/me/": usuario, "GET /api/auth/me/dashboard-config/": config };
}

function app(rota, rotas) {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <AuthProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<p>início</p>} />
            <Route path="/login" element={<Login />} />
            <Route path="/dashboard" element={<RotaProtegida><p>painel</p></RotaProtegida>} />
            <Route path="/usuarios" element={<RotaProtegida papeis={["admin"]}><p>usuários</p></RotaProtegida>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("RotaProtegida", () => {
  it("sem sessão manda para o login", async () => {
    app("/dashboard", {});
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });

  it("papel sem permissão vê 'Acesso negado'", async () => {
    simularApi(perfil());
    vi.spyOn(axios, "post").mockResolvedValue({ data: { access: "A" } });
    definirSessao({ refresh: "R" });
    app("/usuarios");
    expect(await screen.findByText("Acesso negado")).toBeInTheDocument();
    expect(screen.getByText(/Seu perfil \(aluno\)/)).toBeInTheDocument();
  });

  it("papel permitido vê a página", async () => {
    simularApi(perfil());
    vi.spyOn(axios, "post").mockResolvedValue({ data: { access: "A" } });
    definirSessao({ refresh: "R" });
    app("/dashboard");
    expect(await screen.findByText("painel")).toBeInTheDocument();
  });
});

describe("AuthProvider", () => {
  it("restaura a sessão da aba a partir do refresh salvo", async () => {
    simularApi(perfil());
    const refresh = vi.spyOn(axios, "post").mockResolvedValue({ data: { access: "A2" } });
    definirSessao({ refresh: "R1" });
    app("/", {});
    expect(await screen.findByText(/Ana/)).toBeInTheDocument();
    expect(refresh).toHaveBeenCalledWith("/api/auth/token/refresh/", { refresh: "R1" });
  });

  it("refresh salvo inválido: começa deslogado e limpa a sessão", async () => {
    vi.spyOn(axios, "post").mockRejectedValue(new Error("expirado"));
    definirSessao({ refresh: "R1" });
    app("/");
    expect(await screen.findByRole("link", { name: "Entrar" })).toBeInTheDocument();
    expect(refreshSalvo()).toBeNull();
  });

  it("expõe os vínculos do usuário", async () => {
    simularApi(perfil());
    vi.spyOn(axios, "post").mockResolvedValue({ data: { access: "A" } });
    definirSessao({ refresh: "R" });
    let visto;
    function Espiao() {
      visto = useAuth();
      return null;
    }
    render(
      <MemoryRouter>
        <AuthProvider>
          <Espiao />
        </AuthProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(visto.usuario).not.toBeNull());
    expect(visto.papel).toBe("aluno");
    expect(visto.alunoId).toBe("a1");
    expect(visto.temPapel("aluno", "admin")).toBe(true);
    expect(visto.temPapel("admin")).toBe(false);
  });
});

describe("Login", () => {
  it("credenciais erradas mostram a mensagem da API", async () => {
    simularApi({ "POST /api/auth/token/": falha(401, { codigo: "credenciais_invalidas", mensagem: "E-mail ou senha inválidos." }) });
    app("/login");
    await userEvent.type(await screen.findByLabelText("E-mail institucional"), "ana@ufvjm.edu.br");
    await userEvent.type(screen.getByLabelText("Senha"), "errada");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha inválidos.");
  });

  it("login certo carrega o perfil e vai para o dashboard", async () => {
    const chamadas = simularApi({ "POST /api/auth/token/": { access: "A", refresh: "R" }, ...perfil() });
    app("/login");
    await userEvent.type(await screen.findByLabelText("E-mail institucional"), "  ana@ufvjm.edu.br ");
    await userEvent.type(screen.getByLabelText("Senha"), "SenhaForte#2026");
    await userEvent.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByText("painel")).toBeInTheDocument();
    expect(chamadas[0].corpo).toEqual({ email: "ana@ufvjm.edu.br", password: "SenhaForte#2026" });
    expect(refreshSalvo()).toBe("R");
  });
});

describe("Layout", () => {
  it("visitante vê repositório e 'Entrar'", async () => {
    app("/");
    expect(await screen.findByRole("link", { name: "Repositório" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Entrar" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Dashboard" })).toBeNull();
  });

  it("logado vê os menus do papel e sai", async () => {
    const chamadas = simularApi({ ...perfil(), "POST /api/auth/logout/": {} });
    vi.spyOn(axios, "post").mockResolvedValue({ data: { access: "A" } });
    definirSessao({ refresh: "R" });
    app("/");
    expect(await screen.findByRole("link", { name: "Minhas monografias" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sair" }));
    expect(await screen.findByRole("link", { name: "Entrar" })).toBeInTheDocument();
    expect(chamadas.some((c) => c.url === "/api/auth/logout/")).toBe(true);
    expect(refreshSalvo()).toBeNull();
  });
});
