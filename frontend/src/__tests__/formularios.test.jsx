import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { api } from "../api/cliente";
import { Destaque } from "../components/comuns";
import FormAvaliacao from "../components/FormAvaliacao";
import UploadPdf from "../components/UploadPdf";
import { validarAvaliacao, validarPdf } from "../utils/validacao";

const PARECER = "Trabalho consistente, metodologia adequada e resultados bem discutidos ao longo do texto.";

function arquivo(nome, tamanho, tipo = "application/pdf") {
  const f = new File(["%PDF-1.4"], nome, { type: tipo });
  Object.defineProperty(f, "size", { value: tamanho });
  return f;
}

describe("validações espelhadas do servidor", () => {
  it("aceita PDF dentro do limite", () => {
    expect(validarPdf(arquivo("tcc.pdf", 10 * 1024 * 1024))).toBeNull();
  });
  it("rejeita extensão, tipo e tamanho", () => {
    expect(validarPdf(arquivo("tcc.txt", 10))).toMatch(/PDF/);
    expect(validarPdf(arquivo("tcc.pdf", 10, "text/plain"))).toMatch(/PDF/);
    expect(validarPdf(arquivo("tcc.pdf", 51 * 1024 * 1024))).toMatch(/50 MB/);
  });
  it("valida avaliação", () => {
    expect(validarAvaliacao({ nota: "8.5", parecer: PARECER, recomendacao: "aprovado_sem_ressalvas" })).toEqual({});
    const e = validarAvaliacao({ nota: "10.5", parecer: "curto", recomendacao: "" });
    expect(Object.keys(e).sort()).toEqual(["nota", "parecer", "recomendacao"]);
    expect(validarAvaliacao({ nota: "8.55", parecer: PARECER, recomendacao: "reprovado" }).nota).toMatch(/casa decimal/);
  });
});

describe("UploadPdf", () => {
  it("bloqueia arquivo acima de 50 MB sem chamar a API", async () => {
    const espiao = vi.spyOn(api, "post");
    render(<UploadPdf url="/api/monografias/1/arquivo/" />);
    await userEvent.upload(screen.getByLabelText(/Arquivo PDF/), arquivo("grande.pdf", 60 * 1024 * 1024));
    expect(screen.getByRole("alert")).toHaveTextContent("50 MB");
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
    expect(espiao).not.toHaveBeenCalled();
  });

  it("envia multipart e mostra mensagem de duplicado vinda do servidor", async () => {
    vi.spyOn(api, "post").mockRejectedValueOnce({ response: { status: 409, data: { codigo: "arquivo_duplicado", mensagem: "x" } } });
    render(<UploadPdf url="/api/monografias/1/arquivo/" />);
    await userEvent.upload(screen.getByLabelText(/Arquivo PDF/), arquivo("tcc.pdf", 1000));
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("já foi submetido"));
    const [url, form] = api.post.mock.calls[0];
    expect(url).toBe("/api/monografias/1/arquivo/");
    expect(form.get("arquivo").name).toBe("tcc.pdf");
  });

  it("informa upload em andamento (409)", async () => {
    vi.spyOn(api, "post").mockRejectedValueOnce({ response: { status: 409, data: { codigo: "upload_em_andamento" } } });
    render(<UploadPdf url="/x/" />);
    await userEvent.upload(screen.getByLabelText(/Arquivo PDF/), arquivo("tcc.pdf", 1000));
    await userEvent.click(screen.getByRole("button", { name: "Enviar" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("em andamento"));
  });
});

describe("FormAvaliacao", () => {
  it("mostra erros de validação e não envia", async () => {
    const onEnviar = vi.fn();
    render(<FormAvaliacao onEnviar={onEnviar} />);
    await userEvent.type(screen.getByLabelText(/Nota/), "11");
    await userEvent.type(screen.getByLabelText(/Parecer/), "curto");
    await userEvent.click(screen.getByRole("button", { name: "Lançar avaliação" }));
    expect(screen.getByText("A nota deve estar entre 0 e 10.")).toBeInTheDocument();
    expect(screen.getByText(/pelo menos 50 caracteres/)).toBeInTheDocument();
    expect(onEnviar).not.toHaveBeenCalled();
  });

  it("envia dados válidos com nota normalizada", async () => {
    const onEnviar = vi.fn().mockResolvedValue();
    render(<FormAvaliacao onEnviar={onEnviar} />);
    await userEvent.type(screen.getByLabelText(/Nota/), "8,5");
    await userEvent.type(screen.getByLabelText(/Parecer/), PARECER);
    await userEvent.selectOptions(screen.getByLabelText("Recomendação"), "aprovado_com_ressalvas");
    await userEvent.click(screen.getByRole("button", { name: "Lançar avaliação" }));
    await waitFor(() => expect(onEnviar).toHaveBeenCalledWith({ nota: "8.5", parecer: PARECER, recomendacao: "aprovado_com_ressalvas" }));
  });

  it("exibe erro do servidor (ex.: resultado fechado)", async () => {
    const onEnviar = vi.fn().mockRejectedValue({ response: { data: { mensagem: "O resultado já foi fechado." } } });
    render(<FormAvaliacao inicial={{ nota: "7.0", parecer: PARECER, recomendacao: "reprovado" }} onEnviar={onEnviar} rotuloBotao="Salvar" />);
    await userEvent.click(screen.getByRole("button", { name: "Salvar" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("resultado já foi fechado"));
  });
});

describe("Destaque", () => {
  it("destaca termos sem interpretar HTML (proteção XSS)", () => {
    const { container } = render(<Destaque texto={'filas de [[eventos]] <img src=x onerror="alert(1)">'} />);
    expect(container.querySelector("mark")).toHaveTextContent("eventos");
    expect(container.querySelector("img")).toBeNull();
  });
});
