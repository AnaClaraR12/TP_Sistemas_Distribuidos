import axios from "axios";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { abrirArquivoProtegido, api, mensagemDeErro } from "../api/cliente";
import { useAuth } from "../auth/AuthContext";
import Carregando from "../components/Carregando";
import { Alerta, Historico, Status } from "../components/comuns";
import FormAvaliacao from "../components/FormAvaliacao";
import { useApi } from "../utils/hooks";
import { RECOMENDACOES, formatarData } from "../utils/validacao";

export function ListaBancas() {
  const [params] = useSearchParams();
  const minhas = params.get("minhas");
  const { temPapel } = useAuth();
  const { dados, erro, carregando } = useApi("/api/bancas/", { params: { minhas: minhas || undefined } });
  return (
    <section>
      <div className="cabecalho">
        <h1>{minhas ? "Minhas bancas" : "Bancas"}</h1>
        {temPapel("coordenador", "admin", "professor") && <Link className="botao" to="/bancas/nova">Agendar banca</Link>}
      </div>
      {carregando && <Carregando />}
      <Alerta>{erro}</Alerta>
      {dados && (
        <table className="tabela">
          <thead><tr><th>Monografia</th><th>Data/hora</th><th>Local/Link</th><th>Status</th><th>Confirmações</th><th>Resultado</th></tr></thead>
          <tbody>
            {dados.results.map((b) => (
              <tr key={b.id}>
                <td><Link to={`/bancas/${b.id}`}>{b.monografia?.titulo || b.monografia_id}</Link></td>
                <td>{formatarData(b.data_hora_inicio)}</td>
                <td>{b.local || "remota"}</td>
                <td><Status valor={b.status} /></td>
                <td>{b.membros.filter((m) => m.confirmacao === "confirmado").length}/{b.membros.length}</td>
                <td>{b.resultado_final ? `${b.resultado_final} (${b.media_final})` : "—"}</td>
              </tr>
            ))}
            {!dados.results.length && <tr><td colSpan={6}>Nenhuma banca.</td></tr>}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function NovaBanca() {
  const [params] = useSearchParams();
  const navegar = useNavigate();
  const { dados: monos } = useApi("/api/monografias/", { params: { status: "em_avaliacao", aprovacao_orientador: "aprovada", limit: 50 } });
  const { dados: profs } = useApi("/api/auth/professores/", { params: { limit: 50 } });
  const [form, setForm] = useState({ monografia_id: params.get("monografia") || "", data: "", duracao: 120, modalidade: "presencial", local: "", link: "" });
  const [internos, setInternos] = useState([]);
  const [externos, setExternos] = useState([]);
  const [erro, setErro] = useState(null);
  const mudar = (c) => (e) => setForm({ ...form, [c]: e.target.value });

  const monoSel = monos?.results?.find((m) => m.id === form.monografia_id);

  async function enviar(e) {
    e.preventDefault();
    setErro(null);
    if (!form.data) return setErro("Informe data e hora.");
    const membros = [
      ...internos.map((id) => ({ tipo: "interno", professor_id: id })),
      ...externos.filter((x) => x.nome && x.email).map((x) => ({ tipo: "externo", ...x })),
    ];
    try {
      const r = await api.post("/api/bancas/", {
        monografia_id: form.monografia_id,
        data_hora_inicio: new Date(form.data).toISOString(),
        duracao_minutos: Number(form.duracao),
        local: form.modalidade === "presencial" ? form.local : null,
        link: form.modalidade === "remota" ? form.link : null,
        membros,
      });
      navegar(`/bancas/${r.data.id}`);
    } catch (err) {
      setErro(mensagemDeErro(err));
    }
  }

  return (
    <section className="cartao estreito">
      <h1>Agendar banca (etapa 1: convites)</h1>
      <p className="mudo">A banca só passa a "agendada" depois que todos os membros confirmarem (etapa 2).</p>
      <form className="form" onSubmit={enviar}>
        <label htmlFor="mono">Monografia (aprovada pelo orientador)</label>
        <select id="mono" value={form.monografia_id} onChange={mudar("monografia_id")} required>
          <option value="">Selecione…</option>
          {(monos?.results || []).map((m) => <option key={m.id} value={m.id}>{m.titulo}</option>)}
        </select>
        <label htmlFor="data">Data e hora</label>
        <input id="data" type="datetime-local" value={form.data} onChange={mudar("data")} required />
        <label htmlFor="duracao">Duração (min)</label>
        <input id="duracao" type="number" min={15} max={600} value={form.duracao} onChange={mudar("duracao")} />
        <fieldset>
          <legend>Modalidade</legend>
          <label><input type="radio" name="mod" value="presencial" checked={form.modalidade === "presencial"} onChange={mudar("modalidade")} /> Presencial</label>
          <label><input type="radio" name="mod" value="remota" checked={form.modalidade === "remota"} onChange={mudar("modalidade")} /> Remota</label>
        </fieldset>
        {form.modalidade === "presencial" ? (
          <><label htmlFor="local">Local</label><input id="local" value={form.local} onChange={mudar("local")} required /></>
        ) : (
          <><label htmlFor="link">Link da defesa remota</label><input id="link" type="url" value={form.link} onChange={mudar("link")} required /></>
        )}
        <fieldset>
          <legend>Membros internos (o orientador é incluído automaticamente)</legend>
          {(profs?.results || []).filter((p) => p.id !== monoSel?.orientador_id).map((p) => (
            <label key={p.id} className="checkbox">
              <input type="checkbox" checked={internos.includes(p.id)} onChange={(e) => setInternos(e.target.checked ? [...internos, p.id] : internos.filter((x) => x !== p.id))} />
              {p.nome} <span className="mudo">({p.departamento})</span>
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Membros externos (acesso por token temporário)</legend>
          {externos.map((x, i) => (
            <div key={i} className="linha-externo">
              <input aria-label="Nome" placeholder="Nome" value={x.nome} onChange={(e) => setExternos(externos.map((y, j) => (j === i ? { ...y, nome: e.target.value } : y)))} />
              <input aria-label="E-mail" type="email" placeholder="E-mail" value={x.email} onChange={(e) => setExternos(externos.map((y, j) => (j === i ? { ...y, email: e.target.value } : y)))} />
              <input aria-label="Instituição" placeholder="Instituição" value={x.instituicao} onChange={(e) => setExternos(externos.map((y, j) => (j === i ? { ...y, instituicao: e.target.value } : y)))} />
              <button type="button" className="link" onClick={() => setExternos(externos.filter((_, j) => j !== i))}>remover</button>
            </div>
          ))}
          <button type="button" onClick={() => setExternos([...externos, { nome: "", email: "", instituicao: "" }])}>+ Membro externo</button>
        </fieldset>
        <Alerta>{erro}</Alerta>
        <button type="submit" className="primario">Criar banca e enviar convites</button>
      </form>
    </section>
  );
}

export function DetalheBanca() {
  const { id } = useParams();
  const { professorId, papel } = useAuth();
  const { dados: b, erro, carregando, recarregar } = useApi(`/api/bancas/${id}/`);
  const { dados: avaliacoes, recarregar: recarregarAv } = useApi(`/api/bancas/${id}/avaliacoes/`);
  const [msg, setMsg] = useState(null);
  const [erroAcao, setErroAcao] = useState(null);
  const [conflitos, setConflitos] = useState([]);
  const [motivo, setMotivo] = useState("");

  if (carregando && !b) return <Carregando />;
  if (erro) return <Alerta>{erro}</Alerta>;
  if (!b) return null;

  const eu = b.membros.find((m) => m.professor_id && m.professor_id === professorId);
  const minhaAv = avaliacoes?.find((a) => a.membro === eu?.id);
  const gestor = ["admin", "coordenador"].includes(papel) || b.membros.some((m) => m.funcao === "orientador" && m.professor_id === professorId);
  const aberta = b.status === "realizada" && !b.resultado_calculado_em;

  async function acao(fn, sucesso) {
    setErroAcao(null);
    setMsg(null);
    setConflitos([]);
    try {
      await fn();
      setMsg(sucesso);
      await recarregar();
      await recarregarAv();
    } catch (e) {
      setErroAcao(mensagemDeErro(e));
      setConflitos(e?.response?.data?.detalhes?.conflitos || e?.response?.data?.detalhes?.membros || []);
    }
  }

  return (
    <section>
      <div className="cabecalho">
        <h1>Banca — {b.monografia?.titulo}</h1>
        <Status valor={b.status} />
      </div>
      <Alerta tipo="sucesso">{msg}</Alerta>
      <Alerta>{erroAcao}</Alerta>
      {conflitos.length > 0 && (
        <ul className="alerta erro">
          {conflitos.map((c, i) => (
            <li key={i}>{c.membro} {c.confirmacao ? `— ${c.confirmacao}` : `— conflito com banca de ${formatarData(c.inicio)} a ${formatarData(c.fim)}`}</li>
          ))}
        </ul>
      )}
      <div className="colunas">
        <article className="cartao">
          <h2>Dados</h2>
          <dl className="metadados">
            <dt>Início</dt><dd>{formatarData(b.data_hora_inicio)}</dd>
            <dt>Término previsto</dt><dd>{formatarData(b.data_hora_fim)}</dd>
            <dt>{b.local ? "Local" : "Link"}</dt><dd>{b.local || <a href={b.link} target="_blank" rel="noopener noreferrer">{b.link}</a>}</dd>
            <dt>Resultado</dt><dd>{b.resultado_final ? `${b.resultado_final} — média ${b.media_final}${b.exige_correcao ? " (com ressalvas)" : ""}` : "aguardando avaliações"}</dd>
            <dt>Avaliações</dt><dd>{b.total_avaliacoes}/{b.membros.filter((m) => m.confirmacao === "confirmado").length}</dd>
          </dl>
          {(eu || gestor) && <button onClick={() => abrirArquivoProtegido(`/api/bancas/${id}/pdf/`)}>Baixar PDF da monografia</button>}
          {gestor && b.status === "em_organizacao" && (
            <button className="primario" onClick={() => acao(() => api.post(`/api/bancas/${id}/agendar/`), "Banca agendada! Membros e aluno serão notificados.")}>Agendar (etapa 2)</button>
          )}
          {["admin", "coordenador"].includes(papel) && b.status === "agendada" && (
            <button onClick={() => acao(() => api.post(`/api/bancas/${id}/marcar-realizada/`), "Banca marcada como realizada; avaliações liberadas.")}>Marcar como realizada</button>
          )}
          {gestor && ["em_organizacao", "agendada"].includes(b.status) && (
            <div className="form">
              <label htmlFor="motivo-c">Motivo do cancelamento</label>
              <input id="motivo-c" value={motivo} onChange={(e) => setMotivo(e.target.value)} />
              <button className="perigo" disabled={motivo.length < 5} onClick={() => acao(() => api.post(`/api/bancas/${id}/cancelar/`, { motivo }), "Banca cancelada.")}>Cancelar banca</button>
            </div>
          )}
        </article>
        <article className="cartao">
          <h2>Membros</h2>
          <table className="tabela compacta">
            <thead><tr><th>Nome</th><th>Tipo</th><th>Função</th><th>Confirmação</th><th>Avaliou</th><th></th></tr></thead>
            <tbody>
              {b.membros.map((m) => (
                <tr key={m.id}>
                  <td>{m.nome}<br /><small className="mudo">{m.email}</small></td>
                  <td>{m.tipo}</td>
                  <td>{m.funcao}</td>
                  <td><Status valor={m.confirmacao} /></td>
                  <td>{m.avaliou ? "✓" : "—"}</td>
                  <td>
                    {gestor && b.status === "em_organizacao" && m.funcao !== "orientador" && (
                      <button className="link" onClick={() => acao(() => api.delete(`/api/bancas/${id}/membros/${m.id}/`), "Membro removido.")}>remover</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {eu && eu.confirmacao === "pendente" && ["em_organizacao", "agendada"].includes(b.status) && (
            <div className="acoes">
              <button className="primario" onClick={() => acao(() => api.post(`/api/bancas/${id}/membros/${eu.id}/confirmar/`, { resposta: "confirmado" }), "Disponibilidade confirmada.")}>Confirmar disponibilidade</button>
              <button onClick={() => acao(() => api.post(`/api/bancas/${id}/membros/${eu.id}/confirmar/`, { resposta: "recusado" }), "Convite recusado.")}>Recusar</button>
            </div>
          )}
        </article>
      </div>

      {eu && eu.confirmacao === "confirmado" && (aberta || minhaAv) && (
        <article className="cartao">
          <h2>{minhaAv ? "Minha avaliação" : "Lançar avaliação"}</h2>
          {aberta ? (
            <FormAvaliacao
              key={minhaAv?.id || "nova"}
              inicial={minhaAv}
              rotuloBotao={minhaAv ? "Salvar alterações" : "Lançar avaliação"}
              onEnviar={async (dados) => {
                if (minhaAv) await api.patch(`/api/bancas/${id}/avaliacoes/${minhaAv.id}/`, dados);
                else await api.post(`/api/bancas/${id}/avaliacoes/`, dados);
                setMsg("Avaliação registrada.");
                await recarregar();
                await recarregarAv();
              }}
            />
          ) : (
            <p>Nota {minhaAv.nota} — {RECOMENDACOES[minhaAv.recomendacao]} (resultado fechado; edição bloqueada)</p>
          )}
        </article>
      )}

      {avaliacoes?.length > 0 && (
        <article className="cartao">
          <h2>Avaliações</h2>
          {avaliacoes.map((a) => (
            <div key={a.id} className="avaliacao">
              <strong>{a.membro_nome}</strong> ({a.membro_tipo}) — nota {a.nota} — {RECOMENDACOES[a.recomendacao]}
              <p>{a.parecer}</p>
            </div>
          ))}
        </article>
      )}
      <article className="cartao">
        <Historico url={`/api/bancas/${id}/historico/`} />
      </article>
    </section>
  );
}

/** Página do membro externo: sem login, autenticada pelo token do convite. */
export function BancaExterna() {
  const { token } = useParams();
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const [msg, setMsg] = useState(null);
  const cliente = useCallback((metodo, url, corpo) => axios({ method: metodo, url, data: corpo, headers: { "X-Banca-Token": token } }), [token]);

  const carregar = useCallback(async () => {
    try {
      const r = await cliente("get", "/api/bancas/externo/minha-banca/");
      setDados(r.data);
      setErro(null);
    } catch (e) {
      setErro(mensagemDeErro(e));
    }
  }, [cliente]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  if (erro && !dados) return <Alerta>{erro}</Alerta>;
  if (!dados) return <Carregando />;
  const { banca, membro, monografia, minha_avaliacao: av } = dados;
  const aberta = banca.status === "realizada" && !banca.resultado_fechado;

  async function responder(resposta) {
    try {
      await cliente("post", "/api/bancas/externo/confirmar/", { resposta });
      setMsg(resposta === "confirmado" ? "Disponibilidade confirmada. Obrigado!" : "Convite recusado.");
      await carregar();
    } catch (e) {
      setErro(mensagemDeErro(e));
    }
  }

  return (
    <section className="cartao estreito">
      <h1>Banca de defesa</h1>
      <p>Olá, <strong>{membro.nome}</strong>. Você foi convidado(a) como membro externo.</p>
      <Alerta tipo="sucesso">{msg}</Alerta>
      <Alerta>{erro}</Alerta>
      <dl className="metadados">
        <dt>Monografia</dt><dd>{monografia.titulo}</dd>
        <dt>Data/hora</dt><dd>{formatarData(banca.data_hora_inicio)} ({banca.duracao_minutos} min)</dd>
        <dt>{banca.local ? "Local" : "Link"}</dt><dd>{banca.local || banca.link}</dd>
        <dt>Status</dt><dd><Status valor={banca.status} /></dd>
        <dt>Sua confirmação</dt><dd><Status valor={membro.confirmacao} /></dd>
      </dl>
      <a className="botao" href={dados.pdf_url} target="_blank" rel="noopener noreferrer">Baixar PDF da monografia</a>
      {membro.confirmacao === "pendente" && ["em_organizacao", "agendada"].includes(banca.status) && (
        <div className="acoes">
          <button className="primario" onClick={() => responder("confirmado")}>Confirmar disponibilidade</button>
          <button onClick={() => responder("recusado")}>Recusar</button>
        </div>
      )}
      {membro.confirmacao === "confirmado" && aberta && (
        <>
          <h2>{av ? "Editar minha avaliação" : "Lançar avaliação"}</h2>
          <FormAvaliacao
            inicial={av}
            rotuloBotao={av ? "Salvar alterações" : "Lançar avaliação"}
            onEnviar={async (d) => {
              await cliente(av ? "patch" : "post", "/api/bancas/externo/avaliacao/", d);
              setMsg("Avaliação registrada. Obrigado!");
              await carregar();
            }}
          />
        </>
      )}
      {banca.resultado_fechado && <p>O resultado desta banca já foi fechado. Seu acesso será encerrado.</p>}
    </section>
  );
}
