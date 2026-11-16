import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { PorCurso, TaxaAprovacao } from "../charts/Graficos";
import { Auditoria, Cadastros, Notificacoes, Usuarios } from "../pages/Administracao";
import Dashboard from "../pages/Dashboard";
import { falha, pagina, simularApi } from "./apiFalsa";

const auth = vi.hoisted(() => ({ atual: {} }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth.atual }));

// jsdom não tem canvas: cada gráfico vira um <div> com os rótulos e valores recebidos
vi.mock("react-chartjs-2", () => {
  const Falso = ({ data }) => (
    <div data-testid="grafico">{data.labels?.map((l, i) => `${l}=${data.datasets[0].data[i]}`).join(";")}</div>
  );
  return { Bar: Falso, Line: Falso, Doughnut: Falso };
});

const RESUMO = {
  total: 5,
  por_status: { publicada: 1, em_avaliacao: 1 },
  por_curso: [{ curso_nome: "SI", total: 4, publicadas: 1 }, { curso_nome: "ENG", total: 1, publicadas: 0 }],
  por_orientador: [{ orientador_nome: "Prof A", total: 4 }],
  por_ano: [{ ano: 2025, total: 1, aprovadas: 1 }, { ano: 2026, total: 3, aprovadas: 2 }],
  taxa_aprovacao: { geral: { aprovadas: 3, reprovadas: 1, taxa: 0.75 }, por_ano: [{ ano: 2026, taxa: 0.6667 }] },
  tempo_medio_submissao_defesa: { geral_dias: 16.0, amostra: 4, por_curso: [{ curso_nome: "SI", media_dias: 20 }] },
};

function rodar(elemento) {
  return render(<MemoryRouter>{elemento}</MemoryRouter>);
}

describe("Dashboard por papel", () => {
  it("coordenador vê os cinco indicadores do enunciado", async () => {
    auth.atual = { usuario: { nome: "Coord" }, papel: "coordenador", config: { papel: "coordenador", widgets: ["kpis", "bancas_pendentes"] } };
    simularApi({ "GET /api/relatorios/resumo/": { dados: RESUMO }, "GET /api/bancas/": pagina([]) });
    rodar(<Dashboard />);
    expect(await screen.findByText("Monografias por curso")).toBeInTheDocument();
    const graficos = screen.getAllByTestId("grafico").map((g) => g.textContent);
    expect(graficos).toContain("SI=4;ENG=1"); // por curso
    expect(graficos).toContain("Prof A=4"); // por orientador
    expect(graficos).toContain("2025=1;2026=3"); // por ano de defesa
    expect(screen.getByText("Taxa de aprovação: 75.0%")).toBeInTheDocument();
    expect(screen.getByText("16")).toBeInTheDocument(); // tempo médio em dias
    expect(screen.getByRole("heading", { name: "Bancas em organização (0)" })).toBeInTheDocument();
  });

  it("aluno vê as próprias submissões e o motivo de devolução", async () => {
    auth.atual = { usuario: { nome: "Ana" }, papel: "aluno", config: { papel: "aluno", widgets: ["linha_do_tempo_submissao"] } };
    simularApi({
      "GET /api/monografias/": pagina([
        { id: "m1", titulo: "Filas", status: "rascunho", aprovacao_orientador: "rejeitada", motivo_rejeicao: "Faltou a metodologia." },
      ]),
    });
    rodar(<Dashboard />);
    expect(await screen.findByText(/Devolvida pelo orientador: Faltou a metodologia./)).toBeInTheDocument();
    expect(screen.queryByText("Monografias por curso")).toBeNull();
  });

  it("aluno sem monografias é convidado a criar o rascunho", async () => {
    auth.atual = { usuario: { nome: "Ana" }, papel: "aluno", config: { papel: "aluno", widgets: ["linha_do_tempo_submissao"] } };
    simularApi({ "GET /api/monografias/": pagina([]) });
    rodar(<Dashboard />);
    expect(await screen.findByRole("link", { name: "Criar rascunho" })).toHaveAttribute("href", "/monografias/nova");
  });

  it("orientador vê só as pendências que são dele", async () => {
    auth.atual = { usuario: { nome: "Prof" }, papel: "professor", professorId: "p1", config: { papel: "professor", widgets: ["pendencias_aprovacao"] } };
    simularApi({
      "GET /api/monografias/": pagina([
        { id: "m1", titulo: "Minha orientanda", orientador_id: "p1", texto_extraido: false },
        { id: "m2", titulo: "De outro", orientador_id: "p9" },
      ]),
    });
    rodar(<Dashboard />);
    expect(await screen.findByRole("heading", { name: "Aguardando sua aprovação (1)" })).toBeInTheDocument();
    expect(screen.getByText("processando PDF…")).toBeInTheDocument();
    expect(screen.queryByText("De outro")).toBeNull();
  });

  it("erro dos relatórios aparece no painel", async () => {
    auth.atual = { usuario: { nome: "Coord" }, papel: "coordenador", config: { papel: "coordenador", widgets: ["kpis"] } };
    simularApi({ "GET /api/relatorios/resumo/": falha(503, { mensagem: "Relatórios indisponíveis." }) });
    rodar(<Dashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Relatórios indisponíveis.");
  });
});

describe("Gráficos com base vazia", () => {
  it("sem dados mostram aviso, sem dividir por zero", () => {
    render(
      <>
        <PorCurso dados={[]} />
        <TaxaAprovacao dados={{ geral: { aprovadas: 0, reprovadas: 0, taxa: null }, por_ano: [] }} />
      </>,
    );
    expect(screen.getAllByText("Sem dados para exibir.")).toHaveLength(3);
    expect(screen.getByText("Taxa de aprovação")).toBeInTheDocument();
  });
});

describe("Administração", () => {
  it("cadastra aluno mandando null nos campos vazios", async () => {
    const chamadas = simularApi({
      "GET /api/auth/cursos/": pagina([{ id: "c1", nome: "SI" }]),
      "GET /api/auth/professores/": pagina([]),
      "GET /api/auth/alunos/": pagina([]),
      "POST /api/auth/alunos/": { id: "a1" },
    });
    rodar(<Cadastros />);
    const form = await screen.findByRole("heading", { name: "Alunos" });
    const secao = form.closest("section");
    await userEvent.type(within(secao).getByLabelText("Nome"), "Ana");
    await userEvent.type(within(secao).getByLabelText("Matrícula"), "2026001");
    await userEvent.type(within(secao).getByLabelText("E-mail"), "ana@ufvjm.edu.br");
    await userEvent.selectOptions(within(secao).getByLabelText("Curso"), "c1");
    await userEvent.click(within(secao).getByRole("button", { name: "Adicionar" }));
    expect(await screen.findByText("Registro criado.")).toBeInTheDocument();
    expect(chamadas.find((c) => c.metodo === "POST").corpo).toEqual({
      nome: "Ana",
      matricula: "2026001",
      email: "ana@ufvjm.edu.br",
      curso: "c1",
      orientador_atual: null,
    });
  });

  it("exclusão recusada pela API mostra o motivo", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    simularApi({
      "GET /api/auth/cursos/": pagina([{ id: "c1", nome: "SI", codigo: "SI" }]),
      "GET /api/auth/professores/": pagina([]),
      "GET /api/auth/alunos/": pagina([]),
      "DELETE /api/auth/cursos/c1/": falha(409, { mensagem: "Curso possui alunos vinculados." }),
    });
    rodar(<Cadastros />);
    await userEvent.click(await screen.findByRole("tab", { name: "cursos" }));
    await userEvent.click(await screen.findByRole("button", { name: "excluir" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Curso possui alunos vinculados.");
  });

  it("auditoria filtra por ação e mostra quem fez o quê", async () => {
    const chamadas = simularApi({
      "GET /api/auth/auditoria/": pagina([
        { id: 1, criado_em: "2026-05-01T10:00:00Z", usuario_email: "ana@x", acao: "upload_arquivo", recurso: "monografia", recurso_id: "m1", ip: "10.0.0.1", servico_origem: "monografias-service", nivel: "info" },
      ]),
    });
    rodar(<Auditoria />);
    expect(await screen.findByText("upload_arquivo")).toBeInTheDocument();
    expect(screen.getByText("ana@x")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Ação"), "login");
    expect(chamadas.at(-1).params).toMatchObject({ acao: "login", offset: 0, limit: 30 });
  });

  it("admin desativa usuário", async () => {
    const chamadas = simularApi({
      "GET /api/auth/admin/usuarios/": pagina([{ id: "u1", email: "ana@x", nome: "Ana", papel: "aluno", is_active: true }]),
      "PATCH /api/auth/admin/usuarios/u1/": {},
    });
    rodar(<Usuarios />);
    await userEvent.click(await screen.findByRole("button", { name: /desativar/ }));
    expect(chamadas.find((c) => c.metodo === "PATCH").corpo).toEqual({ is_active: false });
  });

  it("fora da rede institucional: mostra o 403", async () => {
    simularApi({
      "GET /api/auth/admin/usuarios/": falha(403, {
        codigo: "fora_da_rede_institucional",
        mensagem: "A área administrativa só pode ser acessada pela rede institucional (IP/VPN).",
      }),
    });
    rodar(<Usuarios />);
    expect(await screen.findByRole("alert")).toHaveTextContent("rede institucional");
  });

  it("notificações: marca como lida", async () => {
    const chamadas = simularApi({
      "GET /api/notificacoes/minhas/": pagina([{ id: "n1", assunto: "Banca agendada", corpo: "Detalhes", criada_em: "2026-05-01T10:00:00Z", lida_em: null }]),
      "POST /api/notificacoes/n1/lida/": {},
    });
    rodar(<Notificacoes />);
    await userEvent.click(await screen.findByRole("button", { name: "marcar como lida" }));
    expect(chamadas.some((c) => c.url === "/api/notificacoes/n1/lida/")).toBe(true);
  });
});
