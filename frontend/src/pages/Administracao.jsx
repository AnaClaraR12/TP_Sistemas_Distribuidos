import { useState } from "react";
import { api, mensagemDeErro } from "../api/cliente";
import Carregando from "../components/Carregando";
import { Alerta, Paginacao } from "../components/comuns";
import { useApi } from "../utils/hooks";
import { formatarData } from "../utils/validacao";

/** CRUD genérico (tabela + formulário) usado por cursos, professores e alunos. */
function Crud({ titulo, url, campos, colunas }) {
  const [offset, setOffset] = useState(0);
  const { dados, erro, carregando, recarregar } = useApi(url, { params: { limit: 20, offset } });
  const vazio = Object.fromEntries(campos.map((c) => [c.nome, ""]));
  const [form, setForm] = useState(vazio);
  const [editando, setEditando] = useState(null);
  const [msg, setMsg] = useState(null);
  const [erroForm, setErroForm] = useState(null);

  async function salvar(e) {
    e.preventDefault();
    setErroForm(null);
    const corpo = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === "" ? null : v]));
    try {
      if (editando) await api.patch(`${url}${editando}/`, corpo);
      else await api.post(url, corpo);
      setMsg(editando ? "Registro atualizado." : "Registro criado.");
      setForm(vazio);
      setEditando(null);
      recarregar();
    } catch (err) {
      setErroForm(mensagemDeErro(err));
    }
  }

  async function excluir(id) {
    if (!window.confirm("Confirma a exclusão?")) return;
    try {
      await api.delete(`${url}${id}/`);
      recarregar();
    } catch (err) {
      setErroForm(mensagemDeErro(err));
    }
  }

  return (
    <section className="cartao">
      <h2>{titulo}</h2>
      <form className="form-inline" onSubmit={salvar}>
        {campos.map((c) => (
          <div key={c.nome} className="campo">
            <label htmlFor={`${titulo}-${c.nome}`}>{c.rotulo}</label>
            {c.opcoes ? (
              <select id={`${titulo}-${c.nome}`} value={form[c.nome] ?? ""} onChange={(e) => setForm({ ...form, [c.nome]: e.target.value })}>
                <option value="">—</option>
                {c.opcoes.map((o) => <option key={o.valor} value={o.valor}>{o.rotulo}</option>)}
              </select>
            ) : (
              <input id={`${titulo}-${c.nome}`} type={c.tipo || "text"} value={form[c.nome] ?? ""} required={c.obrigatorio} disabled={editando && c.fixo}
                onChange={(e) => setForm({ ...form, [c.nome]: e.target.value })} />
            )}
          </div>
        ))}
        <button type="submit" className="primario">{editando ? "Salvar" : "Adicionar"}</button>
        {editando && <button type="button" onClick={() => { setEditando(null); setForm(vazio); }}>Cancelar</button>}
      </form>
      <Alerta tipo="sucesso">{msg}</Alerta>
      <Alerta>{erroForm || erro}</Alerta>
      {carregando && <Carregando />}
      {dados && (
        <table className="tabela compacta">
          <thead><tr>{colunas.map((c) => <th key={c.nome}>{c.rotulo}</th>)}<th></th></tr></thead>
          <tbody>
            {dados.results.map((r) => (
              <tr key={r.id}>
                {colunas.map((c) => <td key={c.nome}>{r[c.nome] ?? "—"}</td>)}
                <td>
                  <button className="link" onClick={() => { setEditando(r.id); setForm(Object.fromEntries(campos.map((c) => [c.nome, r[c.nome] ?? ""]))); }}>editar</button>
                  <button className="link perigo" onClick={() => excluir(r.id)}>excluir</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {dados && <Paginacao total={dados.count} limite={20} offset={offset} onMudar={setOffset} />}
    </section>
  );
}

export function Cadastros() {
  const [aba, setAba] = useState("alunos");
  const { dados: cursos } = useApi("/api/auth/cursos/", { params: { limit: 50 } });
  const { dados: profs } = useApi("/api/auth/professores/", { params: { limit: 50 } });
  const optCursos = (cursos?.results || []).map((c) => ({ valor: c.id, rotulo: c.nome }));
  const optProfs = (profs?.results || []).map((p) => ({ valor: p.id, rotulo: p.nome }));
  return (
    <section>
      <h1>Cadastros</h1>
      <div role="tablist" className="abas">
        {["alunos", "professores", "cursos"].map((a) => (
          <button key={a} role="tab" aria-selected={aba === a} className={aba === a ? "ativa" : ""} onClick={() => setAba(a)}>{a}</button>
        ))}
      </div>
      {aba === "alunos" && (
        <Crud titulo="Alunos" url="/api/auth/alunos/"
          campos={[{ nome: "nome", rotulo: "Nome", obrigatorio: true }, { nome: "matricula", rotulo: "Matrícula", obrigatorio: true },
            { nome: "email", rotulo: "E-mail", tipo: "email", obrigatorio: true, fixo: true },
            { nome: "curso", rotulo: "Curso", opcoes: optCursos }, { nome: "orientador_atual", rotulo: "Orientador", opcoes: optProfs }]}
          colunas={[{ nome: "nome", rotulo: "Nome" }, { nome: "matricula", rotulo: "Matrícula" }, { nome: "email", rotulo: "E-mail" },
            { nome: "curso_nome", rotulo: "Curso" }, { nome: "orientador_nome", rotulo: "Orientador" }]} />
      )}
      {aba === "professores" && (
        <Crud titulo="Professores" url="/api/auth/professores/"
          campos={[{ nome: "nome", rotulo: "Nome", obrigatorio: true }, { nome: "email", rotulo: "E-mail", tipo: "email", obrigatorio: true, fixo: true },
            { nome: "departamento", rotulo: "Departamento", obrigatorio: true }, { nome: "area_pesquisa", rotulo: "Área de pesquisa" }]}
          colunas={[{ nome: "nome", rotulo: "Nome" }, { nome: "email", rotulo: "E-mail" }, { nome: "departamento", rotulo: "Departamento" },
            { nome: "area_pesquisa", rotulo: "Área" }, { nome: "papel", rotulo: "Papel" }]} />
      )}
      {aba === "cursos" && (
        <Crud titulo="Cursos" url="/api/auth/cursos/"
          campos={[{ nome: "nome", rotulo: "Nome", obrigatorio: true }, { nome: "codigo", rotulo: "Código", obrigatorio: true },
            { nome: "coordenador", rotulo: "Coordenador", opcoes: optProfs }]}
          colunas={[{ nome: "codigo", rotulo: "Código" }, { nome: "nome", rotulo: "Nome" }, { nome: "coordenador_nome", rotulo: "Coordenador" }]} />
      )}
    </section>
  );
}

export function Auditoria() {
  const [f, setF] = useState({ acao: "", email: "", inicio: "", fim: "", nivel: "" });
  const [offset, setOffset] = useState(0);
  const params = Object.fromEntries(Object.entries({ ...f, offset, limit: 30 }).filter(([, v]) => v !== ""));
  if (params.inicio) params.inicio = new Date(params.inicio).toISOString();
  if (params.fim) params.fim = new Date(params.fim).toISOString();
  const { dados, erro, carregando } = useApi("/api/auth/auditoria/", { params });
  const mudar = (c) => (e) => { setF({ ...f, [c]: e.target.value }); setOffset(0); };
  return (
    <section>
      <h1>Auditoria</h1>
      <div className="filtros">
        <div className="campo"><label htmlFor="a-acao">Ação</label><input id="a-acao" value={f.acao} onChange={mudar("acao")} placeholder="login, upload_arquivo…" /></div>
        <div className="campo"><label htmlFor="a-email">Usuário (e-mail)</label><input id="a-email" value={f.email} onChange={mudar("email")} /></div>
        <div className="campo"><label htmlFor="a-ini">De</label><input id="a-ini" type="datetime-local" value={f.inicio} onChange={mudar("inicio")} /></div>
        <div className="campo"><label htmlFor="a-fim">Até</label><input id="a-fim" type="datetime-local" value={f.fim} onChange={mudar("fim")} /></div>
        <div className="campo"><label htmlFor="a-nivel">Nível</label>
          <select id="a-nivel" value={f.nivel} onChange={mudar("nivel")}><option value="">Todos</option><option value="info">info</option><option value="critico">crítico</option></select>
        </div>
      </div>
      {carregando && <Carregando />}
      <Alerta>{erro}</Alerta>
      {dados && (
        <table className="tabela compacta">
          <thead><tr><th>Quando</th><th>Usuário</th><th>Ação</th><th>Recurso</th><th>IP</th><th>Serviço</th><th>Nível</th></tr></thead>
          <tbody>
            {dados.results.map((r) => (
              <tr key={r.id} className={r.nivel === "critico" ? "critico" : ""}>
                <td>{formatarData(r.criado_em)}</td><td>{r.usuario_email || "—"}</td><td>{r.acao}</td>
                <td>{r.recurso} {r.recurso_id && <small className="mudo">{r.recurso_id.slice(0, 8)}</small>}</td>
                <td>{r.ip || "—"}</td><td>{r.servico_origem}</td><td>{r.nivel}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {dados && <Paginacao total={dados.count} limite={30} offset={offset} onMudar={setOffset} />}
    </section>
  );
}

export function Usuarios() {
  const { dados, erro, carregando, recarregar } = useApi("/api/auth/admin/usuarios/", { params: { limit: 50 } });
  const [erroAcao, setErroAcao] = useState(null);
  async function alternar(u) {
    try {
      await api.patch(`/api/auth/admin/usuarios/${u.id}/`, { is_active: !u.is_active });
      recarregar();
    } catch (e) {
      setErroAcao(mensagemDeErro(e));
    }
  }
  return (
    <section>
      <h1>Usuários</h1>
      <p className="mudo">Área administrativa: acessível apenas pela rede institucional.</p>
      {carregando && <Carregando />}
      <Alerta>{erro || erroAcao}</Alerta>
      {dados && (
        <table className="tabela compacta">
          <thead><tr><th>E-mail</th><th>Nome</th><th>Papel</th><th>Último login</th><th>IP</th><th>Ativo</th></tr></thead>
          <tbody>
            {dados.results.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td><td>{u.nome}</td><td>{u.papel}</td><td>{formatarData(u.last_login)}</td><td>{u.ultimo_login_ip || "—"}</td>
                <td><button className="link" onClick={() => alternar(u)}>{u.is_active ? "✅ desativar" : "⛔ ativar"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function Notificacoes() {
  const { dados, erro, carregando, recarregar } = useApi("/api/notificacoes/minhas/", { params: { limit: 50 } });
  return (
    <section>
      <h1>Notificações</h1>
      {carregando && <Carregando />}
      <Alerta>{erro}</Alerta>
      <ul className="notificacoes">
        {(dados?.results || []).map((n) => (
          <li key={n.id} className={`cartao ${n.lida_em ? "lida" : ""}`}>
            <strong>{n.assunto}</strong> <span className="mudo">{formatarData(n.criada_em)}</span>
            <pre>{n.corpo}</pre>
            {!n.lida_em && <button className="link" onClick={async () => { await api.post(`/api/notificacoes/${n.id}/lida/`); recarregar(); }}>marcar como lida</button>}
          </li>
        ))}
        {dados && !dados.results.length && <p>Nenhuma notificação.</p>}
      </ul>
    </section>
  );
}
