import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Historico, LinhaDoTempo, Paginacao, Status } from "../components/comuns";
import { useApi, useDebounce } from "../utils/hooks";
import { formatarBytes, formatarData, validarPdf } from "../utils/validacao";
import { falha, simularApi } from "./apiFalsa";

describe("useApi", () => {
  it("carrega, guarda os dados e recarrega", async () => {
    let n = 0;
    const chamadas = simularApi({ "GET /api/x/": () => ({ n: ++n }) });
    const { result } = renderHook(() => useApi("/api/x/", { params: { status: "rascunho" } }));
    await waitFor(() => expect(result.current.dados).toEqual({ n: 1 }));
    expect(chamadas[0].params).toEqual({ status: "rascunho" });
    await act(() => result.current.recarregar());
    expect(result.current.dados).toEqual({ n: 2 });
  });

  it("erro vira mensagem legível", async () => {
    simularApi({ "GET /api/x/": falha(403, { mensagem: "Sem acesso." }) });
    const { result } = renderHook(() => useApi("/api/x/"));
    await waitFor(() => expect(result.current.erro).toBe("Sem acesso."));
    expect(result.current.carregando).toBe(false);
  });

  it("ativo=false não faz requisição", async () => {
    const chamadas = simularApi({});
    renderHook(() => useApi("/api/x/", { ativo: false }));
    await new Promise((ok) => setTimeout(ok, 20));
    expect(chamadas).toHaveLength(0);
  });
});

describe("useDebounce", () => {
  it("só entrega o valor depois do intervalo", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 400), { initialProps: { v: "a" } });
    rerender({ v: "ab" });
    expect(result.current).toBe("a");
    act(() => vi.advanceTimersByTime(400));
    expect(result.current).toBe("ab");
    vi.useRealTimers();
  });
});

describe("validarPdf", () => {
  const arq = (nome, tamanho, tipo = "application/pdf") => {
    const f = new File(["x"], nome, { type: tipo });
    Object.defineProperty(f, "size", { value: tamanho });
    return f;
  };

  it("limite exato de 50 MB passa, um byte a mais não", () => {
    expect(validarPdf(arq("a.pdf", 50 * 1024 * 1024))).toBeNull();
    expect(validarPdf(arq("a.pdf", 50 * 1024 * 1024 + 1))).toMatch(/50 MB/);
  });

  it("arquivo vazio, ausente e extensão maiúscula", () => {
    expect(validarPdf(arq("a.pdf", 0))).toBe("Arquivo vazio.");
    expect(validarPdf(null)).toMatch(/Selecione/);
    expect(validarPdf(arq("TCC.PDF", 10))).toBeNull();
  });
});

describe("formatação", () => {
  it("bytes e datas", () => {
    expect(formatarBytes(512 * 1024)).toBe("512.0 KB");
    expect(formatarBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(formatarBytes(null)).toBe("—");
    expect(formatarData(null)).toBe("—");
    expect(formatarData("2026-07-01T12:00:00Z", false)).toMatch(/2026/);
  });
});

describe("componentes comuns", () => {
  it("Status mostra o rótulo em português", () => {
    render(<Status valor="em_avaliacao" />);
    expect(screen.getByText("Em avaliação")).toBeInTheDocument();
  });

  it("Paginacao some quando cabe em uma página e navega quando não cabe", async () => {
    const { container, rerender } = render(<Paginacao total={10} limite={20} offset={0} onMudar={() => {}} />);
    expect(container).toBeEmptyDOMElement();
    const onMudar = vi.fn();
    rerender(<Paginacao total={45} limite={20} offset={20} onMudar={onMudar} />);
    expect(screen.getByText(/Página 2 de 3/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Próxima/ }));
    await userEvent.click(screen.getByRole("button", { name: /Anterior/ }));
    expect(onMudar.mock.calls).toEqual([[40], [0]]);
  });

  it.each([
    [{ status: "rascunho", aprovacao_orientador: "pendente" }, undefined, "Rascunho"],
    [{ status: "em_avaliacao", aprovacao_orientador: "pendente" }, undefined, "Em avaliação"],
    [{ status: "em_avaliacao", aprovacao_orientador: "aprovada" }, undefined, "Aprovada pelo orientador"],
    [{ status: "em_avaliacao", aprovacao_orientador: "aprovada" }, { status: "agendada" }, "Banca"],
    [{ status: "aprovada" }, undefined, "Resultado"],
    [{ status: "reprovada" }, undefined, "Reprovada"],
    [{ status: "publicada" }, undefined, "Publicada"],
  ])("LinhaDoTempo marca a etapa atual (%j)", (monografia, banca, etapa) => {
    render(<LinhaDoTempo monografia={monografia} banca={banca} />);
    expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent(etapa);
  });

  it("Historico mostra quem, o quê e quando", async () => {
    simularApi({
      "GET /api/monografias/1/historico/": {
        historico: [
          {
            versao: 2,
            tipo: "alteracao",
            usuario_id: "a1b2c3d4-0000",
            data_hora: "2026-05-10T14:00:00Z",
            alteracoes: [{ campo: "titulo", anterior: "Velho", novo: "Novo" }],
          },
          { versao: 1, tipo: "criacao", usuario_id: null, data_hora: "2026-05-09T14:00:00Z", alteracoes: [] },
        ],
      },
    });
    render(<Historico url="/api/monografias/1/historico/" />);
    expect(await screen.findByText("titulo")).toBeInTheDocument();
    expect(screen.getByText(/Velho → Novo/)).toBeInTheDocument();
    expect(screen.getByText("a1b2c3d4")).toBeInTheDocument();
    expect(screen.getByText("sistema")).toBeInTheDocument();
  });

  it("Historico vazio", async () => {
    simularApi({ "GET /h/": { historico: [] } });
    render(<Historico url="/h/" />);
    expect(await screen.findByText("Sem alterações registradas.")).toBeInTheDocument();
  });
});
