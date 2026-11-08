import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { abrirArquivoProtegido, api, mensagemDeErro } from "../api/cliente";
import { useAuth } from "../auth/AuthContext";
import Carregando from "../components/Carregando";
import { Alerta, Historico, LinhaDoTempo, Paginacao, Status } from "../components/comuns";
import UploadPdf from "../components/UploadPdf";
import { useApi, useDebounce } from "../utils/hooks";
import { formatarBytes, formatarData } from "../utils/validacao";

export function ListaMonografias() {
  const { temPapel } = useAuth();
  const [busca, setBusca] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const atrasada = useDebounce(busca);
  const { dados, erro, carregando } = useApi("/api/monografias/", { params: { busca: atrasada || undefined, status: status || undefined, offset, limit: 20 } });
  return (
    <section>
      <div className="cabecalho">
        <h1>Monografias</h1>
        {temPapel("aluno", "admin") && (
          <Link className="botao" to="/monografias/nova">
            Nova monografia
          </Link>
        )}
      </div>
      <div className="filtros">
        <div className="campo largo">
          <label htmlFor="m-busca">Buscar</label>
          <input id="m-busca" value={busca} onChange={(e) => { setBusca(e.target.value); setOffset(0); }} />
        </div>
        <div className="campo">
          <label htmlFor="m-status">Status</label>
          <select id="m-status" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
            <option value="">Todos</option>
            {["rascunho", "em_avaliacao", "aprovada", "reprovada", "publicada"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>
      {carregando && <Carregando />}
      <Alerta>{erro}</Alerta>
      {dados && (
        <table className="tabela">
          <thead>
            <tr><th>Título</th><th>Status</th><th>Orientador</th><th>Aprovação</th><th>Atualizada</th></tr>
          </thead>
          <tbody>
            {dados.results.map((m) => (
              <tr key={m.id}>
                <td><Link to={`/monografias/${m.id}`}>{m.titulo}</Link></td>
                <td><Status valor={m.status} /></td>
                <td>{m.orientador_nome || "—"}</td>
                <td><Status valor={m.aprovacao_orientador} /></td>
                <td>{formatarData(m.atualizado_em)}</td>
              </tr>
            ))}
            {!dados.results.length && <tr><td colSpan={5}>Nenhuma monografia.</td></tr>}
          </tbody>
        </table>
      )}
      {dados && <Paginacao total={dados.count} limite={20} offset={offset} onMudar={setOffset} />}
    </section>
  );
}

function FormMetadados({ inicial = {}, onSalvar, rotulo }) {
  const { dados: orientadores } = useApi("/api/repositorio/orientadores/");
  const [d, setD] = useState({
    titulo: inicial.titulo || "",
    resumo: inicial.resumo || "",
    palavras: (inicial.palavras_chave || []).join(", "),
    orientador_id: inicial.orientador_id || "",
  });
  const [erro, setErro] = useState(null);
  const mudar = (c) => (e) => setD({ ...d, [c]: e.target.value });

  async function enviar(e) {
    e.preventDefault();
    setErro(null);
    const palavras = d.palavras.split(",").map((p) => p.trim()).filter(Boolean);
    if (!d.titulo.trim()) return setErro("Informe o título.");
    try {
      await onSalvar({ titulo: d.titulo, resumo: d.resumo, palavras_chave: palavras, orientador_id: d.orientador_id || null });
    } catch (err) {
      setErro(mensagemDeErro(err));
    }
  }
  return (
    <form className="form" onSubmit={enviar}>
      <label htmlFor="titulo">Título</label>
      <input id="titulo" value={d.titulo} onChange={mudar("titulo")} required maxLength={300} />
      <label htmlFor="resumo">Resumo</label>
      <textarea id="resumo" rows={6} value={d.resumo} onChange={mudar("resumo")} />
      <label htmlFor="palavras">Palavras-chave (mínimo 3, separadas por vírgula)</label>
      <input id="palavras" value={d.palavras} onChange={mudar("palavras")} />
      <label htmlFor="orientador">Orientador</label>
      <select id="orientador" value={d.orientador_id} onChange={mudar("orientador_id")}>
        <option value="">Selecione…</option>
        {(orientadores || []).map((o) => (
          <option key={o.id} value={o.id}>{o.nome} — {o.departamento}</option>
        ))}
      </select>
      <Alerta>{erro}</Alerta>
      <button type="submit">{rotulo}</button>
    </form>
  );
}

export function NovaMonografia() {
  const navegar = useNavigate();
  return (
    <section className="cartao estreito">
      <h1>Nova monografia (rascunho)</h1>
      <FormMetadados
        rotulo="Criar rascunho"
        onSalvar={async (dados) => {
          const r = await api.post("/api/monografias/", dados);
          navegar(`/monografias/${r.data.id}`);
        }}
      />
    </section>
  );
}

const TIPOS_DOC = {
  termo_autorizacao_publicacao: "Termo de autorização de publicação (assinado)",
  versao_corrigida: "Versão corrigida",
  comprovante_correcao_ortografica: "Comprovante de correção ortográfica",
  ata_defesa: "Ata de defesa",
};

export function DetalheMonografia() {
  const { id } = useParams();
  const { alunoId, professorId, papel } = useAuth();
  const { dados: m, erro, carregando, recarregar } = useApi(`/api/monografias/${id}/`);
  const { dados: bancas } = useApi("/api/bancas/", { params: { monografia: id } });
  const [msg, setMsg] = useState(null);
  const [erroAcao, setErroAcao] = useState(null);
  const [editando, setEditando] = useState(false);
  const [motivo, setMotivo] = useState("");
  const [tipoDoc, setTipoDoc] = useState("termo_autorizacao_publicacao");
  const navegar = useNavigate();

  if (carregando && !m) return <Carregando />;
  if (erro) return <Alerta>{erro}</Alerta>;
  if (!m) return null;

  const dono = papel === "admin" || m.aluno_id === alunoId;
  const orientador = papel === "admin" || m.orientador_id === professorId;
  const coordenacao = papel === "admin" || papel === "coordenador";
  const banca = bancas?.results?.find((b) => b.status !== "cancelada");

  async function acao(fn, sucesso) {
    setErroAcao(null);
    setMsg(null);
    try {
      await fn();
      setMsg(sucesso);
      await recarregar();
    } catch (e) {
      setErroAcao(mensagemDeErro(e));
    }
  }

  return (
    <section>
      <div className="cabecalho">
        <h1>{m.titulo}</h1>
        <Status valor={m.status} />
      </div>
      <LinhaDoTempo monografia={m} banca={banca} />
      <Alerta tipo="sucesso">{msg}</Alerta>
      <Alerta>{erroAcao}</Alerta>

      <div className="colunas">
        <article className="cartao">
          <h2>Dados</h2>
          {editando ? (
            <FormMetadados
              inicial={m}
              rotulo="Salvar"
              onSalvar={async (dados) => {
                await api.patch(`/api/monografias/${id}/`, dados);
                setEditando(false);
                await recarregar();
              }}
            />
          ) : (
            <dl className="metadados">
              <dt>Resumo</dt><dd>{m.resumo || "—"}</dd>
              <dt>Palavras-chave</dt><dd>{m.palavras_chave.join(", ") || "—"}</dd>
              <dt>Orientador</dt><dd>{m.orientador_nome || "—"}</dd>
              <dt>Aprovação do orientador</dt><dd><Status valor={m.aprovacao_orientador} /> {formatarData(m.aprovada_orientador_em)}</dd>
              <dt>Submetida em</dt><dd>{formatarData(m.submetida_em)}</dd>
              <dt>Resultado da banca</dt><dd>{m.resultado_banca || "—"}{m.exige_correcao ? " (com ressalvas)" : ""}</dd>
              <dt>Publicada em</dt><dd>{formatarData(m.publicada_em)}</dd>
            </dl>
          )}
          {dono && m.status === "rascunho" && !editando && <button onClick={() => setEditando(true)}>Editar dados</button>}
          {m.motivo_rejeicao && m.aprovacao_orientador === "rejeitada" && <Alerta tipo="aviso">Motivo da devolução: {m.motivo_rejeicao}</Alerta>}
        </article>

        <article className="cartao">
          <h2>Arquivo e integridade</h2>
          <dl className="metadados">
            <dt>Arquivo</dt><dd>{m.arquivo_nome_original || "não enviado"} ({formatarBytes(m.arquivo_tamanho_bytes)})</dd>
            <dt>SHA-256</dt><dd className="hash">{m.arquivo_sha256 || "—"}</dd>
            <dt>SHA-256 aprovado</dt><dd className="hash">{m.arquivo_sha256_aprovado || "—"}</dd>
            <dt>Integridade</dt><dd>{m.integridade_ok ? "✅ íntegro" : "❌ VIOLADA"} {m.integridade_verificada_em && `(verificada ${formatarData(m.integridade_verificada_em)})`}</dd>
            <dt>Texto extraído</dt><dd>{m.texto_extraido ? "sim" : m.status === "em_avaliacao" ? "processando…" : "não"}</dd>
          </dl>
          {m.arquivo_sha256 && <button onClick={() => abrirArquivoProtegido(`/api/monografias/${id}/arquivo/download/`)}>Visualizar PDF</button>}
          {m.arquivo_sha256 && (
            <button onClick={() => acao(() => api.post(`/api/monografias/${id}/verificar-integridade/`), "Integridade verificada.")}>
              Verificar integridade
            </button>
          )}
          {dono && m.status === "rascunho" && (
            <>
              <UploadPdf url={`/api/monografias/${id}/arquivo/`} rotulo="PDF da monografia" onSucesso={recarregar} />
              <button
                className="primario"
                disabled={!m.arquivo_sha256}
                onClick={() => acao(() => api.post(`/api/monografias/${id}/submeter/`), "Monografia submetida! O orientador será notificado.")}
              >
                Submeter para o orientador
              </button>
            </>
          )}
        </article>
      </div>

      {orientador && m.status === "em_avaliacao" && m.aprovacao_orientador === "pendente" && (
        <article className="cartao">
          <h2>Avaliação do orientador</h2>
          <button className="primario" onClick={() => acao(() => api.post(`/api/monografias/${id}/aprovar-orientador/`), "Submissão aprovada. A banca já pode ser agendada.")}>
            Aprovar submissão
          </button>
          <div className="form">
            <label htmlFor="motivo">Motivo da devolução (mín. 10 caracteres)</label>
            <textarea id="motivo" rows={3} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
            <button className="perigo" disabled={motivo.trim().length < 10} onClick={() => acao(() => api.post(`/api/monografias/${id}/rejeitar-orientador/`, { motivo }), "Submissão devolvida ao aluno.")}>
              Rejeitar / devolver
            </button>
          </div>
        </article>
      )}

      {(orientador || coordenacao) && m.status === "em_avaliacao" && m.aprovacao_orientador === "aprovada" && !banca && (
        <p><Link className="botao" to={`/bancas/nova?monografia=${id}`}>Agendar banca</Link></p>
      )}
      {banca && <p>Banca: <Link to={`/bancas/${banca.id}`}>{formatarData(banca.data_hora_inicio)}</Link> <Status valor={banca.status} /></p>}

      {["em_avaliacao", "aprovada", "publicada"].includes(m.status) && (
        <article className="cartao">
          <h2>Documentos complementares</h2>
          {m.pendencias_publicacao?.length > 0 && <Alerta tipo="aviso">Para publicar falta: {m.pendencias_publicacao.join(", ")}</Alerta>}
          <table className="tabela compacta">
            <thead><tr><th>Tipo</th><th>Arquivo</th><th>Enviado</th><th>Assinatura</th><th></th></tr></thead>
            <tbody>
              {m.documentos.map((d) => (
                <tr key={d.id}>
                  <td>{TIPOS_DOC[d.tipo]}</td>
                  <td>{d.arquivo_nome_original}</td>
                  <td>{formatarData(d.criado_em)}</td>
                  <td>{d.tipo === "termo_autorizacao_publicacao" ? (d.assinado_validado ? "✅ validada" : "pendente") : "—"}</td>
                  <td>
                    {coordenacao && d.tipo === "termo_autorizacao_publicacao" && !d.assinado_validado && (
                      <button onClick={() => acao(() => api.post(`/api/monografias/${id}/documentos/${d.id}/validar-assinatura/`), "Termo validado.")}>Validar assinatura</button>
                    )}
                  </td>
                </tr>
              ))}
              {!m.documentos.length && <tr><td colSpan={5}>Nenhum documento.</td></tr>}
            </tbody>
          </table>
          {orientador && m.exige_correcao && !m.correcao_validada && m.documentos.some((d) => d.tipo === "versao_corrigida") && (
            <button className="primario" onClick={() => acao(() => api.post(`/api/monografias/${id}/validar-correcao/`), "Versão corrigida validada.")}>
              Validar versão corrigida
            </button>
          )}
          {m.status !== "publicada" && (dono || coordenacao || orientador) && (
            <div className="form">
              <label htmlFor="tipo-doc">Tipo de documento</label>
              <select id="tipo-doc" value={tipoDoc} onChange={(e) => setTipoDoc(e.target.value)}>
                {Object.entries(TIPOS_DOC).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
              </select>
              <UploadPdf url={`/api/monografias/${id}/documentos/`} extras={{ tipo: tipoDoc }} rotulo="Documento" onSucesso={recarregar} />
            </div>
          )}
        </article>
      )}

      {(dono && m.status === "rascunho") || coordenacao ? (
        m.status !== "publicada" && (
          <button className="perigo" onClick={() => window.confirm("Excluir esta monografia?") && acao(async () => { await api.delete(`/api/monografias/${id}/`); navegar("/monografias"); }, "Excluída.")}>
            Excluir monografia
          </button>
        )
      ) : null}

      <article className="cartao">
        <Historico url={`/api/monografias/${id}/historico/`} />
      </article>
    </section>
  );
}
