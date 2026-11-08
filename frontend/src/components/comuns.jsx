import { ROTULOS_STATUS, formatarData } from "../utils/validacao";
import { useApi } from "../utils/hooks";

export function Alerta({ tipo = "erro", children }) {
  if (!children) return null;
  return (
    <div className={`alerta ${tipo}`} role={tipo === "erro" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function Status({ valor }) {
  return <span className={`status status-${valor}`}>{ROTULOS_STATUS[valor] || valor}</span>;
}

export function Paginacao({ total, limite, offset, onMudar }) {
  if (!total || total <= limite) return null;
  const pagina = Math.floor(offset / limite) + 1;
  const paginas = Math.ceil(total / limite);
  return (
    <nav className="paginacao" aria-label="Paginação">
      <button disabled={pagina <= 1} onClick={() => onMudar(offset - limite)}>
        ‹ Anterior
      </button>
      <span>
        Página {pagina} de {paginas} ({total} resultados)
      </span>
      <button disabled={pagina >= paginas} onClick={() => onMudar(offset + limite)}>
        Próxima ›
      </button>
    </nav>
  );
}

/** Renderiza o trecho destacado do Postgres ([[termo]]) sem usar innerHTML (evita XSS). */
export function Destaque({ texto }) {
  if (!texto) return null;
  const partes = texto.split(/(\[\[.*?\]\])/g);
  return (
    <p className="trecho">
      {partes.map((p, i) =>
        p.startsWith("[[") && p.endsWith("]]") ? <mark key={i}>{p.slice(2, -2)}</mark> : <span key={i}>{p}</span>,
      )}
    </p>
  );
}

/** Histórico de alterações: quem, o quê, quando (endpoints /historico/). */
export function Historico({ url }) {
  const { dados, erro, carregando } = useApi(url);
  if (carregando) return <p className="mudo">Carregando histórico…</p>;
  if (erro) return <Alerta>{erro}</Alerta>;
  const itens = dados?.historico || [];
  if (!itens.length) return <p className="mudo">Sem alterações registradas.</p>;
  return (
    <table className="tabela compacta">
      <caption>Histórico de alterações</caption>
      <thead>
        <tr>
          <th>Quando</th>
          <th>Quem</th>
          <th>Tipo</th>
          <th>O que mudou</th>
        </tr>
      </thead>
      <tbody>
        {itens.map((h) => (
          <tr key={h.versao}>
            <td>{formatarData(h.data_hora)}</td>
            <td title={h.usuario_id || "sistema"}>{h.usuario_id ? h.usuario_id.slice(0, 8) : "sistema"}</td>
            <td>{h.tipo}</td>
            <td>
              {h.alteracoes.length
                ? h.alteracoes.map((a) => (
                    <div key={a.campo}>
                      <strong>{a.campo}</strong>: {String(a.anterior ?? "—")} → {String(a.novo ?? "—")}
                    </div>
                  ))
                : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const ETAPAS = [
  { id: "rascunho", rotulo: "Rascunho" },
  { id: "em_avaliacao", rotulo: "Em avaliação" },
  { id: "aprovada_orientador", rotulo: "Aprovada pelo orientador" },
  { id: "banca", rotulo: "Banca" },
  { id: "resultado", rotulo: "Resultado" },
  { id: "publicada", rotulo: "Publicada" },
];

function etapaAtual(m, banca) {
  if (m.status === "publicada") return 5;
  if (m.status === "aprovada" || m.status === "reprovada") return 4;
  if (banca && ["agendada", "realizada", "em_organizacao"].includes(banca.status)) return 3;
  if (m.aprovacao_orientador === "aprovada") return 2;
  if (m.status === "em_avaliacao") return 1;
  return 0;
}

export function LinhaDoTempo({ monografia, banca }) {
  const atual = etapaAtual(monografia, banca);
  return (
    <ol className="linha-tempo" aria-label="Andamento da submissão">
      {ETAPAS.map((e, i) => (
        <li
          key={e.id}
          className={i < atual ? "feita" : i === atual ? "atual" : ""}
          aria-current={i === atual ? "step" : undefined}
        >
          <span className="bolinha">{i < atual ? "✓" : i + 1}</span>
          <span>{e.id === "resultado" && monografia.status === "reprovada" ? "Reprovada" : e.rotulo}</span>
        </li>
      ))}
    </ol>
  );
}
