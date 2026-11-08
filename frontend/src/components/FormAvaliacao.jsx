import { useState } from "react";
import { RECOMENDACOES, validarAvaliacao } from "../utils/validacao";

/** Formulário de avaliação (nota 0–10 com 1 casa, parecer ≥ 50, recomendação). */
export default function FormAvaliacao({ inicial, onEnviar, rotuloBotao = "Lançar avaliação" }) {
  const [dados, setDados] = useState({
    nota: inicial?.nota ?? "",
    parecer: inicial?.parecer ?? "",
    recomendacao: inicial?.recomendacao ?? "",
  });
  const [erros, setErros] = useState({});
  const [erroServidor, setErroServidor] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const mudar = (campo) => (e) => setDados((d) => ({ ...d, [campo]: e.target.value }));

  async function enviar(e) {
    e.preventDefault();
    const v = validarAvaliacao(dados);
    setErros(v);
    if (Object.keys(v).length) return;
    setEnviando(true);
    setErroServidor(null);
    try {
      await onEnviar({ ...dados, nota: String(dados.nota).replace(",", ".") });
    } catch (err) {
      setErroServidor(err?.response?.data?.mensagem || "Não foi possível salvar a avaliação.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form className="form" onSubmit={enviar} aria-label="Avaliação da banca" noValidate>
      <label htmlFor="nota">Nota (0 a 10)</label>
      <input id="nota" inputMode="decimal" value={dados.nota} onChange={mudar("nota")} aria-invalid={!!erros.nota} />
      {erros.nota && <small className="erro-campo">{erros.nota}</small>}

      <label htmlFor="parecer">Parecer (mínimo 50 caracteres)</label>
      <textarea id="parecer" rows={6} value={dados.parecer} onChange={mudar("parecer")} aria-invalid={!!erros.parecer} />
      <small className="mudo">{dados.parecer.trim().length}/50</small>
      {erros.parecer && <small className="erro-campo">{erros.parecer}</small>}

      <label htmlFor="recomendacao">Recomendação</label>
      <select id="recomendacao" value={dados.recomendacao} onChange={mudar("recomendacao")} aria-invalid={!!erros.recomendacao}>
        <option value="">Selecione…</option>
        {Object.entries(RECOMENDACOES).map(([v, r]) => (
          <option key={v} value={v}>
            {r}
          </option>
        ))}
      </select>
      {erros.recomendacao && <small className="erro-campo">{erros.recomendacao}</small>}

      {erroServidor && (
        <p className="alerta erro" role="alert">
          {erroServidor}
        </p>
      )}
      <button type="submit" disabled={enviando}>
        {enviando ? "Salvando…" : rotuloBotao}
      </button>
    </form>
  );
}
