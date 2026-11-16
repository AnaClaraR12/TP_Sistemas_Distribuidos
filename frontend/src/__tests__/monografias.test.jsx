import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { DetalheMonografia, ListaMonografias, NovaMonografia } from "../pages/Monografias";
import { falha, pagina, simularApi } from "./apiFalsa";

const auth = vi.hoisted(() => ({ atual: {} }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth.atual }));

function como(papel, extra = {}) {
  auth.atual = { papel, temPapel: (...p) => p.includes(papel), ...extra };
}

const RASCUNHO = {
  id: "m1",
  titulo: "Filas de eventos",
  resumo: "Resumo.",
  palavras_chave: ["a", "b", "c"],
  status: "rascunho",
  aprovacao_orientador: "pendente",
  aluno_id: "a1",
  orientador_id: "p1",
  orientador_nome: "Prof. João",
  documentos: [],
  integridade_ok: true,
  arquivo_sha256: null,
};

function Url() {
  const l = useLocation();
  return <output data-testid="url">{l.pathname}</output>;
}

function rodar(elemento, rota = "/monografias/m1") {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/monografias" element={elemento} />
        <Route path="/monografias/nova" element={elemento} />
        <Route path="/monografias/:id" element={elemento} />
      </Routes>
      <Url />
    </MemoryRouter>,
  );
}

const semBanca = { "GET /api/bancas/": pagina([]), "GET /api/monografias/m1/historico/": { historico: [] } };

describe("Lista de monografias", () => {
  it("aluno vê as suas e o botão de nova; filtro de status vai para a API", async () => {
    como("aluno");
    const chamadas = simularApi({ "GET /api/monografias/": pagina([RASCUNHO]) });
    rodar(<ListaMonografias />, "/monografias");
    expect(await screen.findByRole("link", { name: "Filas de eventos" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Nova monografia" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Status"), "rascunho");
    await waitFor(() => expect(chamadas.at(-1).params).toMatchObject({ status: "rascunho", offset: 0 }));
  });

  it("professor não vê o botão de nova monografia", async () => {
    como("professor");
    simularApi({ "GET /api/monografias/": pagina([]) });
    rodar(<ListaMonografias />, "/monografias");
    expect(await screen.findByText("Nenhuma monografia.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nova monografia" })).toBeNull();
  });
});

describe("Nova monografia (rascunho)", () => {
  it("cria o rascunho com orientador e palavras-chave e abre o detalhe", async () => {
    como("aluno");
    const chamadas = simularApi({
      "GET /api/repositorio/orientadores/": [{ id: "p1", nome: "Prof. João", departamento: "DCOMP" }],
      "POST /api/monografias/": { id: "m9" },
    });
    rodar(<NovaMonografia />, "/monografias/nova");
    await userEvent.type(screen.getByLabelText("Título"), "Cache distribuído");
    await userEvent.type(screen.getByLabelText(/Palavras-chave/), "redis, cache , , filas");
    await userEvent.selectOptions(await screen.findByLabelText("Orientador"), "p1");
    await userEvent.click(screen.getByRole("button", { name: "Criar rascunho" }));
    await waitFor(() => expect(screen.getByTestId("url")).toHaveTextContent("/monografias/m9"));
    const post = chamadas.find((c) => c.metodo === "POST");
    expect(post.corpo).toEqual({ titulo: "Cache distribuído", resumo: "", palavras_chave: ["redis", "cache", "filas"], orientador_id: "p1" });
  });

  it("erro de validação do servidor aparece no formulário", async () => {
    como("aluno");
    simularApi({
      "GET /api/repositorio/orientadores/": [],
      "POST /api/monografias/": falha(400, { mensagem: "Dados inválidos.", detalhes: { titulo: ["Muito longo."] } }),
    });
    rodar(<NovaMonografia />, "/monografias/nova");
    await userEvent.type(screen.getByLabelText("Título"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Criar rascunho" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("titulo: Muito longo.");
  });
});

describe("Detalhe da monografia", () => {
  it("aluno dono do rascunho: upload habilitado e submissão bloqueada sem PDF", async () => {
    como("aluno", { alunoId: "a1" });
    simularApi({ "GET /api/monografias/m1/": RASCUNHO, ...semBanca });
    rodar(<DetalheMonografia />);
    expect(await screen.findByLabelText(/PDF da monografia/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submeter para o orientador" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Editar dados" })).toBeInTheDocument();
  });

  it("quem não é o autor não edita nem envia PDF do rascunho", async () => {
    como("professor", { professorId: "p1" });
    simularApi({ "GET /api/monografias/m1/": RASCUNHO, ...semBanca });
    rodar(<DetalheMonografia />);
    await screen.findByRole("heading", { name: "Filas de eventos" });
    expect(screen.queryByLabelText(/PDF da monografia/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Editar dados" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Excluir monografia" })).toBeNull();
  });

  it("aluno submete depois do upload", async () => {
    como("aluno", { alunoId: "a1" });
    const comPdf = { ...RASCUNHO, arquivo_sha256: "f".repeat(64), arquivo_nome_original: "tcc.pdf", arquivo_tamanho_bytes: 2048 };
    const chamadas = simularApi({
      "GET /api/monografias/m1/": comPdf,
      "POST /api/monografias/m1/submeter/": { ...comPdf, status: "em_avaliacao" },
      ...semBanca,
    });
    rodar(<DetalheMonografia />);
    await userEvent.click(await screen.findByRole("button", { name: "Submeter para o orientador" }));
    expect(await screen.findByText(/Monografia submetida!/)).toBeInTheDocument();
    expect(chamadas.some((c) => c.url === "/api/monografias/m1/submeter/")).toBe(true);
  });

  it("orientador aprova a submissão pendente", async () => {
    como("professor", { professorId: "p1" });
    const chamadas = simularApi({
      "GET /api/monografias/m1/": { ...RASCUNHO, status: "em_avaliacao", arquivo_sha256: "f".repeat(64) },
      "POST /api/monografias/m1/aprovar-orientador/": {},
      ...semBanca,
    });
    rodar(<DetalheMonografia />);
    await userEvent.click(await screen.findByRole("button", { name: "Aprovar submissão" }));
    expect(await screen.findByText(/A banca já pode ser agendada/)).toBeInTheDocument();
    expect(chamadas.some((c) => c.url === "/api/monografias/m1/aprovar-orientador/")).toBe(true);
  });

  it("devolução exige motivo de pelo menos 10 caracteres", async () => {
    como("professor", { professorId: "p1" });
    const chamadas = simularApi({
      "GET /api/monografias/m1/": { ...RASCUNHO, status: "em_avaliacao" },
      "POST /api/monografias/m1/rejeitar-orientador/": {},
      ...semBanca,
    });
    rodar(<DetalheMonografia />);
    const botao = await screen.findByRole("button", { name: "Rejeitar / devolver" });
    await userEvent.type(screen.getByLabelText(/Motivo da devolução/), "curto");
    expect(botao).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Motivo da devolução/), " demais aqui");
    await userEvent.click(botao);
    await waitFor(() => expect(chamadas.find((c) => c.metodo === "POST").corpo).toEqual({ motivo: "curto demais aqui" }));
  });

  it("outro professor não vê as ações do orientador", async () => {
    como("professor", { professorId: "p2" });
    simularApi({ "GET /api/monografias/m1/": { ...RASCUNHO, status: "em_avaliacao" }, ...semBanca });
    rodar(<DetalheMonografia />);
    await screen.findByRole("heading", { name: "Filas de eventos" });
    expect(screen.queryByRole("button", { name: "Aprovar submissão" })).toBeNull();
  });

  it("aprovada pelo orientador e sem banca: oferece agendar", async () => {
    como("coordenador");
    simularApi({ "GET /api/monografias/m1/": { ...RASCUNHO, status: "em_avaliacao", aprovacao_orientador: "aprovada" }, ...semBanca });
    rodar(<DetalheMonografia />);
    expect(await screen.findByRole("link", { name: "Agendar banca" })).toHaveAttribute("href", "/bancas/nova?monografia=m1");
  });

  it("coordenação valida o termo e vê as pendências de publicação", async () => {
    como("coordenador");
    const chamadas = simularApi({
      "GET /api/monografias/m1/": {
        ...RASCUNHO,
        status: "aprovada",
        aprovacao_orientador: "aprovada",
        pendencias_publicacao: ["termo_autorizacao_assinado"],
        documentos: [{ id: "d1", tipo: "termo_autorizacao_publicacao", arquivo_nome_original: "termo.pdf", assinado_validado: false }],
      },
      "POST /api/monografias/m1/documentos/d1/validar-assinatura/": {},
      ...semBanca,
    });
    rodar(<DetalheMonografia />);
    expect(await screen.findByText(/Para publicar falta: termo_autorizacao_assinado/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Validar assinatura" }));
    await waitFor(() => expect(chamadas.some((c) => c.url.endsWith("/validar-assinatura/"))).toBe(true));
  });

  it("publicada não pode ser excluída nem receber documentos", async () => {
    como("admin");
    simularApi({ "GET /api/monografias/m1/": { ...RASCUNHO, status: "publicada", aprovacao_orientador: "aprovada" }, ...semBanca });
    rodar(<DetalheMonografia />);
    await screen.findByRole("heading", { name: "Documentos complementares" });
    expect(screen.queryByRole("button", { name: "Excluir monografia" })).toBeNull();
    expect(screen.queryByLabelText("Tipo de documento")).toBeNull();
  });

  it("sem acesso: mostra o erro da API", async () => {
    como("aluno", { alunoId: "a9" });
    simularApi({ "GET /api/monografias/m1/": falha(403, { mensagem: "Você não tem acesso a esta monografia." }), ...semBanca });
    rodar(<DetalheMonografia />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Você não tem acesso a esta monografia.");
  });
});
