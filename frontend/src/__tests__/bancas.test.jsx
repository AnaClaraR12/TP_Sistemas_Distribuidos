import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axios from "axios";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { BancaExterna, DetalheBanca, ListaBancas, NovaBanca } from "../pages/Bancas";
import { falha, pagina, simularApi } from "./apiFalsa";

const auth = vi.hoisted(() => ({ atual: {} }));
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth.atual }));

function como(papel, extra = {}) {
  auth.atual = { papel, temPapel: (...p) => p.includes(papel), ...extra };
}

const PARECER = "Trabalho consistente, metodologia adequada e resultados bem discutidos ao longo do texto.";

const membro = (id, extra) => ({ id, nome: `Membro ${id}`, email: `${id}@x`, tipo: "interno", funcao: "membro", confirmacao: "pendente", ...extra });

const BANCA = {
  id: "b1",
  monografia: { titulo: "Filas de eventos" },
  monografia_id: "m1",
  status: "em_organizacao",
  data_hora_inicio: "2026-12-01T14:00:00Z",
  data_hora_fim: "2026-12-01T16:00:00Z",
  local: "Sala 10",
  link: null,
  total_avaliacoes: 0,
  membros: [
    membro("o", { funcao: "orientador", professor_id: "p1", confirmacao: "confirmado" }),
    membro("m2", { professor_id: "p2" }),
    membro("e", { tipo: "externo" }),
  ],
};

function Url() {
  const l = useLocation();
  return <output data-testid="url">{l.pathname}</output>;
}

function rodar(elemento, rota) {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/bancas" element={elemento} />
        <Route path="/bancas/nova" element={elemento} />
        <Route path="/bancas/:id" element={elemento} />
        <Route path="/banca/externo/:token" element={elemento} />
      </Routes>
      <Url />
    </MemoryRouter>,
  );
}

const detalhe = (banca, avaliacoes = []) => ({
  "GET /api/bancas/b1/": banca,
  "GET /api/bancas/b1/avaliacoes/": avaliacoes,
  "GET /api/bancas/b1/historico/": { historico: [] },
});

describe("Lista de bancas", () => {
  it("mostra confirmações e resultado; coordenador pode agendar", async () => {
    como("coordenador");
    simularApi({ "GET /api/bancas/": pagina([{ ...BANCA, resultado_final: "aprovada", media_final: "8.50" }]) });
    rodar(<ListaBancas />, "/bancas");
    expect(await screen.findByText("1/3")).toBeInTheDocument();
    expect(screen.getByText("aprovada (8.50)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agendar banca" })).toBeInTheDocument();
  });

  it("aluno não vê o botão de agendar", async () => {
    como("aluno");
    simularApi({ "GET /api/bancas/": pagina([]) });
    rodar(<ListaBancas />, "/bancas");
    expect(await screen.findByText("Nenhuma banca.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Agendar banca" })).toBeNull();
  });
});

describe("Nova banca", () => {
  it("defesa remota com membro interno e externo", async () => {
    como("coordenador");
    const chamadas = simularApi({
      "GET /api/monografias/": pagina([{ id: "m1", titulo: "Filas de eventos", orientador_id: "p1" }]),
      "GET /api/auth/professores/": pagina([
        { id: "p1", nome: "Orientador", departamento: "D" },
        { id: "p2", nome: "Prof. Maria", departamento: "D" },
      ]),
      "POST /api/bancas/": { id: "b9" },
    });
    rodar(<NovaBanca />, "/bancas/nova?monografia=m1");
    await screen.findByRole("option", { name: "Filas de eventos" });
    expect(screen.queryByLabelText(/Orientador/)).toBeNull(); // o orientador entra sozinho
    await userEvent.type(screen.getByLabelText("Data e hora"), "2026-12-01T14:00");
    await userEvent.click(screen.getByLabelText(/Remota/));
    await userEvent.type(screen.getByLabelText("Link da defesa remota"), "https://meet.exemplo/abc");
    await userEvent.click(screen.getByLabelText(/Prof. Maria/));
    await userEvent.click(screen.getByRole("button", { name: "+ Membro externo" }));
    await userEvent.type(screen.getByLabelText("Nome"), "Dra. Externa");
    await userEvent.type(screen.getByLabelText("E-mail"), "externa@outra.edu");
    await userEvent.click(screen.getByRole("button", { name: "Criar banca e enviar convites" }));

    await waitFor(() => expect(screen.getByTestId("url")).toHaveTextContent("/bancas/b9"));
    const post = chamadas.find((c) => c.metodo === "POST").corpo;
    expect(post).toMatchObject({
      monografia_id: "m1",
      duracao_minutos: 120,
      local: null,
      link: "https://meet.exemplo/abc",
      membros: [
        { tipo: "interno", professor_id: "p2" },
        { tipo: "externo", nome: "Dra. Externa", email: "externa@outra.edu", instituicao: "" },
      ],
    });
  });
});

describe("Detalhe da banca", () => {
  it("agendar com confirmações pendentes mostra quem falta", async () => {
    como("coordenador");
    simularApi({
      ...detalhe(BANCA),
      "POST /api/bancas/b1/agendar/": falha(409, {
        codigo: "confirmacoes_pendentes",
        mensagem: "Nem todos os membros confirmaram disponibilidade.",
        detalhes: { membros: [{ membro: "Membro m2", confirmacao: "pendente" }] },
      }),
    });
    rodar(<DetalheBanca />, "/bancas/b1");
    await userEvent.click(await screen.findByRole("button", { name: "Agendar (etapa 2)" }));
    expect(await screen.findByText("Nem todos os membros confirmaram disponibilidade.")).toBeInTheDocument();
    expect(screen.getByText("Membro m2 — pendente")).toBeInTheDocument();
  });

  it("conflito de horário lista a banca que conflita", async () => {
    como("coordenador");
    simularApi({
      ...detalhe(BANCA),
      "POST /api/bancas/b1/agendar/": falha(409, {
        codigo: "conflito_horario",
        mensagem: "Conflito de horário com outras bancas dos mesmos membros.",
        detalhes: { conflitos: [{ membro: "Membro o", inicio: "2026-12-01T15:00:00Z", fim: "2026-12-01T17:00:00Z" }] },
      }),
    });
    rodar(<DetalheBanca />, "/bancas/b1");
    await userEvent.click(await screen.findByRole("button", { name: "Agendar (etapa 2)" }));
    expect(await screen.findByText(/Membro o — conflito com banca de/)).toBeInTheDocument();
  });

  it("membro interno confirma disponibilidade", async () => {
    como("professor", { professorId: "p2" });
    const chamadas = simularApi({ ...detalhe(BANCA), "POST /api/bancas/b1/membros/m2/confirmar/": {} });
    rodar(<DetalheBanca />, "/bancas/b1");
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar disponibilidade" }));
    await waitFor(() => expect(chamadas.find((c) => c.metodo === "POST").corpo).toEqual({ resposta: "confirmado" }));
    expect(screen.queryByRole("button", { name: "Agendar (etapa 2)" })).toBeNull(); // não é gestor
  });

  it("depois da defesa o membro lança a avaliação", async () => {
    como("professor", { professorId: "p2" });
    const realizada = { ...BANCA, status: "realizada", membros: BANCA.membros.map((m) => ({ ...m, confirmacao: "confirmado" })) };
    const chamadas = simularApi({ ...detalhe(realizada), "POST /api/bancas/b1/avaliacoes/": {} });
    rodar(<DetalheBanca />, "/bancas/b1");
    await userEvent.type(await screen.findByLabelText(/Nota/), "9");
    await userEvent.type(screen.getByLabelText(/Parecer/), PARECER);
    await userEvent.selectOptions(screen.getByLabelText("Recomendação"), "aprovado_sem_ressalvas");
    await userEvent.click(screen.getByRole("button", { name: "Lançar avaliação" }));
    await waitFor(() =>
      expect(chamadas.find((c) => c.metodo === "POST").corpo).toEqual({ nota: "9", parecer: PARECER, recomendacao: "aprovado_sem_ressalvas" }),
    );
  });

  it("avaliador exclui a própria avaliação enquanto o resultado está aberto", async () => {
    como("professor", { professorId: "p2" });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const realizada = { ...BANCA, status: "realizada", membros: BANCA.membros.map((m) => ({ ...m, confirmacao: "confirmado" })) };
    const minha = { id: "av1", membro: "m2", membro_nome: "Membro m2", nota: "8.0", recomendacao: "reprovado", parecer: PARECER };
    const chamadas = simularApi({ ...detalhe(realizada, [minha]), "DELETE /api/bancas/b1/avaliacoes/av1/": {} });
    rodar(<DetalheBanca />, "/bancas/b1");
    await userEvent.click(await screen.findByRole("button", { name: "Excluir minha avaliação" }));
    expect(await screen.findByText("Avaliação excluída.")).toBeInTheDocument();
    expect(chamadas.some((c) => c.metodo === "DELETE" && c.url === "/api/bancas/b1/avaliacoes/av1/")).toBe(true);
  });

  it("cancelar a confirmação não exclui", async () => {
    como("professor", { professorId: "p2" });
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const realizada = { ...BANCA, status: "realizada", membros: BANCA.membros.map((m) => ({ ...m, confirmacao: "confirmado" })) };
    const minha = { id: "av1", membro: "m2", membro_nome: "Membro m2", nota: "8.0", recomendacao: "reprovado", parecer: PARECER };
    const chamadas = simularApi(detalhe(realizada, [minha]));
    rodar(<DetalheBanca />, "/bancas/b1");
    await userEvent.click(await screen.findByRole("button", { name: "Excluir minha avaliação" }));
    expect(chamadas.some((c) => c.metodo === "DELETE")).toBe(false);
  });

  it("resultado fechado: avaliação aparece só para leitura", async () => {
    como("professor", { professorId: "p2" });
    const fechada = {
      ...BANCA,
      status: "realizada",
      resultado_calculado_em: "2026-12-01T18:00:00Z",
      resultado_final: "aprovada",
      media_final: "8.00",
      membros: BANCA.membros.map((m) => ({ ...m, confirmacao: "confirmado" })),
    };
    simularApi(detalhe(fechada, [{ id: "av1", membro: "m2", membro_nome: "Membro m2", nota: "8.0", recomendacao: "aprovado_com_ressalvas", parecer: PARECER }]));
    rodar(<DetalheBanca />, "/bancas/b1");
    expect(await screen.findByText(/resultado fechado; edição bloqueada/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /avaliação/ })).toBeNull();
  });
});

describe("Membro externo (acesso por token)", () => {
  const MINHA = {
    banca: { status: "agendada", data_hora_inicio: "2026-12-01T14:00:00Z", duracao_minutos: 120, local: null, link: "https://meet/x" },
    membro: { nome: "Dra. Externa", confirmacao: "pendente" },
    monografia: { titulo: "Filas de eventos" },
    minha_avaliacao: null,
    pdf_url: "/api/bancas/externo/pdf/?assinatura=abc",
  };

  it("usa o token do convite no cabeçalho e confirma", async () => {
    const chamadas = simularApi(
      { "GET /api/bancas/externo/minha-banca/": MINHA, "POST /api/bancas/externo/confirmar/": {} },
      { cliente: axios },
    );
    rodar(<BancaExterna />, "/banca/externo/tok123");
    expect(await screen.findByText("Dra. Externa")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar disponibilidade" }));
    expect(await screen.findByText(/Disponibilidade confirmada/)).toBeInTheDocument();
    expect(chamadas.every((c) => c.headers["X-Banca-Token"] === "tok123")).toBe(true);
    expect(chamadas[1].corpo).toEqual({ resposta: "confirmado" });
    expect(chamadas.some((c) => "Authorization" in c.headers)).toBe(false);
  });

  it("token expirado mostra o erro", async () => {
    simularApi({ "GET /api/bancas/externo/minha-banca/": falha(401, { mensagem: "Token expirado." }) }, { cliente: axios });
    rodar(<BancaExterna />, "/banca/externo/velho");
    expect(await screen.findByRole("alert")).toHaveTextContent("Token expirado.");
  });

  it("banca realizada: externo confirmado avalia", async () => {
    const chamadas = simularApi(
      {
        "GET /api/bancas/externo/minha-banca/": { ...MINHA, banca: { ...MINHA.banca, status: "realizada" }, membro: { nome: "Dra. Externa", confirmacao: "confirmado" } },
        "POST /api/bancas/externo/avaliacao/": {},
      },
      { cliente: axios },
    );
    rodar(<BancaExterna />, "/banca/externo/tok123");
    await userEvent.type(await screen.findByLabelText(/Nota/), "7,5");
    await userEvent.type(screen.getByLabelText(/Parecer/), PARECER);
    await userEvent.selectOptions(screen.getByLabelText("Recomendação"), "aprovado_com_ressalvas");
    await userEvent.click(screen.getByRole("button", { name: "Lançar avaliação" }));
    expect(await screen.findByText(/Avaliação registrada/)).toBeInTheDocument();
    expect(chamadas.find((c) => c.metodo === "POST").corpo).toEqual({ nota: "7.5", parecer: PARECER, recomendacao: "aprovado_com_ressalvas" });
  });

  it("externo exclui a própria avaliação pelo token", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const av = { nota: "8.0", parecer: PARECER, recomendacao: "aprovado_sem_ressalvas" };
    const chamadas = simularApi(
      {
        "GET /api/bancas/externo/minha-banca/": {
          ...MINHA,
          banca: { ...MINHA.banca, status: "realizada" },
          membro: { nome: "Dra. Externa", confirmacao: "confirmado" },
          minha_avaliacao: av,
        },
        "DELETE /api/bancas/externo/avaliacao/": {},
      },
      { cliente: axios },
    );
    rodar(<BancaExterna />, "/banca/externo/tok123");
    await userEvent.click(await screen.findByRole("button", { name: "Excluir minha avaliação" }));
    expect(await screen.findByText("Avaliação excluída.")).toBeInTheDocument();
    const del = chamadas.find((c) => c.metodo === "DELETE");
    expect(del.headers["X-Banca-Token"]).toBe("tok123");
  });
});
