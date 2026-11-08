import { useState } from "react";
import { api, mensagemDeErro } from "../api/cliente";
import { MAX_UPLOAD_MB, validarPdf } from "../utils/validacao";

const MENSAGENS = {
  formato_invalido: "O arquivo não é um PDF válido.",
  arquivo_muito_grande: `O arquivo excede ${MAX_UPLOAD_MB} MB.`,
  arquivo_duplicado: "Este arquivo já foi submetido em outra monografia.",
  upload_em_andamento: "Já existe um envio/processamento em andamento. Aguarde alguns instantes.",
  limite_submissoes: "Limite de envios por hora atingido. Tente mais tarde.",
};

/**
 * Upload de PDF com barra de progresso e validação no cliente (formato e tamanho).
 * `url` recebe multipart com o campo "arquivo" (+ campos extras, ex.: tipo do documento).
 */
export default function UploadPdf({ url, extras = {}, rotulo = "Arquivo PDF", onSucesso, maxMb = MAX_UPLOAD_MB }) {
  const [arquivo, setArquivo] = useState(null);
  const [progresso, setProgresso] = useState(0);
  const [erro, setErro] = useState(null);
  const [ok, setOk] = useState(null);
  const [enviando, setEnviando] = useState(false);

  function escolher(e) {
    const f = e.target.files?.[0] || null;
    setOk(null);
    setProgresso(0);
    setArquivo(f);
    setErro(f ? validarPdf(f, maxMb) : null);
  }

  async function enviar(e) {
    e.preventDefault();
    const problema = validarPdf(arquivo, maxMb);
    if (problema) return setErro(problema);
    const form = new FormData();
    form.append("arquivo", arquivo);
    Object.entries(extras).forEach(([k, v]) => form.append(k, v));
    setEnviando(true);
    setErro(null);
    try {
      const r = await api.post(url, form, {
        onUploadProgress: (ev) => ev.total && setProgresso(Math.round((ev.loaded * 100) / ev.total)),
      });
      setOk(r.status === 200 ? "Arquivo idêntico ao já enviado (nada mudou)." : "Arquivo enviado com sucesso.");
      onSucesso?.(r.data);
    } catch (err) {
      const codigo = err?.response?.data?.codigo;
      setErro(MENSAGENS[codigo] || mensagemDeErro(err));
      setProgresso(0);
    } finally {
      setEnviando(false);
    }
  }

  const idCampo = `pdf-${rotulo.replace(/\W+/g, "-")}`;
  return (
    <form className="upload" onSubmit={enviar} aria-label={`Envio de ${rotulo.toLowerCase()}`}>
      <label htmlFor={idCampo}>{rotulo} (máx. {maxMb} MB)</label>
      <input id={idCampo} type="file" accept="application/pdf,.pdf" onChange={escolher} disabled={enviando} />
      {progresso > 0 && (
        <progress max="100" value={progresso} aria-label="Progresso do envio">
          {progresso}%
        </progress>
      )}
      {erro && (
        <p className="alerta erro" role="alert">
          {erro}
        </p>
      )}
      {ok && (
        <p className="alerta sucesso" role="status">
          {ok}
        </p>
      )}
      <button type="submit" disabled={enviando || !arquivo || Boolean(erro)}>
        {enviando ? `Enviando… ${progresso}%` : "Enviar"}
      </button>
    </form>
  );
}
