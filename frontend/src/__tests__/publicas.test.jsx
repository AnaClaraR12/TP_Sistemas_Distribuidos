import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Busca, DetalhePublico, Home } from "../pages/Publicas";
import { falha, pagina, resposta, simularApi } from "./apiFalsa";

const CURSOS = [
  { id: "c1", nome: "Sistemas de Informação", total_publicadas: 3 },
  { id: "c2", nome: "Engenharia", total_publicadas: 1 },
];
const ORIENTADORES = [{ id: "p1", nome: "Prof. João" }];
const MONO = {
  id: "m1",
  titulo: "Filas de eventos",
  resumo: "Estudo sobre RabbitMQ.",
  palavras_chave: ["rabbitmq", "redis"],
  autor_nome: "Ana",
  orientador_nome: "Prof. João",
  curso_nome: "Sistemas de Informação",
  ano_defesa: 2026,
  trecho: "uso de [[filas]] de eventos",
};

function Url() {
  const l = useLocation();
  return <output data-testid="url">{l.pathname + l.search}</output>;
}

function rodar(elemento, rota = "/") {
  return render(
    <MemoryRouter initialEntries={[rota]}>
      <Routes>
        <Route path="/" element={elemento} />
        <Route path="/repositorio" element={elemento} />
        <Route path="/repositorio/:id" element={elemento} />
      </Routes>
      <Url />
    </MemoryRouter>,
  );
}

describe("Home (pública)", () => {
  it("mostra cursos e o total publicado, sem login", async () => {
    simularApi({ "GET /api/repositorio/cursos/": CURSOS });
    rodar(<Home />);
    expect(await screen.findByText("4 monografias publicadas em 2 cursos.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Engenharia/ })).toHaveAttribute("href", "/repositorio?curso=c2");
  });

  it("busca leva para o repositório com o termo", async () => {
    simularApi({ "GET /api/repositorio/cursos/": [] });
    rodar(<Home />);
    await userEvent.type(screen.getByLabelText("Buscar monografias"), "sistemas distribuídos");
    await userEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(screen.getByTestId("url")).toHaveTextContent("/repositorio?busca=sistemas%20distribu%C3%ADdos");
  });
});

describe("Busca no repositório", () => {
  const rotasBase = { "GET /api/repositorio/cursos/": CURSOS, "GET /api/repositorio/orientadores/": ORIENTADORES };

  it("usa os filtros da URL, mostra resultados, trecho destacado e status do cache", async () => {
    const chamadas = simularApi({
      ...rotasBase,
      "GET /api/repositorio/monografias/": resposta(pagina([MONO]), { headers: { "x-cache": "HIT" } }),
    });
    rodar(<Busca />, "/repositorio?busca=filas&ano_defesa=2026");
    expect(await screen.findByRole("link", { name: "Filas de eventos" })).toHaveAttribute("href", "/repositorio/m1");
    expect(screen.getByText("filas").tagName).toBe("MARK");
    expect(screen.getByText(/cache: HIT/)).toBeInTheDocument();
    const busca = chamadas.find((c) => c.url === "/api/repositorio/monografias/");
    expect(busca.params).toMatchObject({ busca: "filas", ano_defesa: "2026", limit: 10 });
  });

  it("filtros por autor, orientador, curso e palavras-chave vão para a API", async () => {
    const chamadas = simularApi({ ...rotasBase, "GET /api/repositorio/monografias/": pagina([]) });
    rodar(<Busca />, "/repositorio");
    await screen.findByText(/Nenhuma monografia encontrada/);
    await userEvent.type(screen.getByLabelText("Autor"), "ana");
    await userEvent.selectOptions(screen.getByLabelText("Orientador"), "p1");
    await userEvent.selectOptions(screen.getByLabelText("Curso"), "c2");
    await userEvent.type(screen.getByLabelText("Palavras-chave"), "redis");
    await waitFor(
      () => {
        const ultima = chamadas.filter((c) => c.url === "/api/repositorio/monografias/").at(-1);
        expect(ultima.params).toMatchObject({ autor: "ana", orientador: "p1", curso: "c2", palavras_chave: "redis" });
      },
      { timeout: 2000 },
    );
  });

  it("erro da API aparece como alerta", async () => {
    simularApi({ ...rotasBase, "GET /api/repositorio/monografias/": falha(503, { mensagem: "Serviço indisponível." }) });
    rodar(<Busca />, "/repositorio");
    expect(await screen.findByRole("alert")).toHaveTextContent("Serviço indisponível.");
  });
});

describe("Detalhe público", () => {
  it("mostra metadados, hash e link de download", async () => {
    simularApi({
      "GET /api/repositorio/monografias/m1/": {
        ...MONO,
        publicado_em: "2026-07-01T12:00:00Z",
        paginas: 42,
        arquivo_sha256: "ab".repeat(32),
        downloads: null,
        download_url: "/api/repositorio/monografias/m1/download/",
      },
    });
    rodar(<DetalhePublico />, "/repositorio/m1");
    expect(await screen.findByRole("heading", { name: "Filas de eventos" })).toBeInTheDocument();
    expect(screen.getByText("ab".repeat(32))).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Baixar PDF" })).toHaveAttribute("href", "/api/repositorio/monografias/m1/download/");
    expect(screen.getByText("—")).toBeInTheDocument(); // downloads indisponível (Redis fora)
  });

  it("monografia não publicada: 404 vira alerta", async () => {
    simularApi({ "GET /api/repositorio/monografias/x/": falha(404, { mensagem: "Recurso não encontrado." }) });
    rodar(<DetalhePublico />, "/repositorio/x");
    expect(await screen.findByRole("alert")).toHaveTextContent("Recurso não encontrado.");
  });
});
