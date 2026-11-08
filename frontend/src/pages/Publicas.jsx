import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, mensagemDeErro } from "../api/cliente";
import Carregando from "../components/Carregando";
import { Alerta, Destaque, Paginacao } from "../components/comuns";
import { useApi, useDebounce } from "../utils/hooks";
import { formatarData } from "../utils/validacao";

export function Home() {
  const [termo, setTermo] = useState("");
  const navegar = useNavigate();
  const { dados: cursos } = useApi("/api/repositorio/cursos/");
  const total = (cursos || []).reduce((s, c) => s + c.total_publicadas, 0);
  return (
    <section className="hero">
      <h1>Repositório de Monografias</h1>
      <p>Pesquise trabalhos de conclusão de curso aprovados e publicados — acesso livre, sem login.</p>
      <form
        className="busca-hero"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          navegar(`/repositorio?busca=${encodeURIComponent(termo)}`);
        }}
      >
        <label htmlFor="busca-home" className="sr-only">
          Buscar monografias
        </label>
        <input id="busca-home" value={termo} onChange={(e) => setTermo(e.target.value)} placeholder="ex.: sistemas distribuídos" />
        <button type="submit">Buscar</button>
      </form>
      <p className="mudo">
        {total} monografias publicadas em {cursos?.length || 0} cursos.
      </p>
      <div className="cards-cursos">
        {(cursos || []).map((c) => (
          <Link key={c.id} className="cartao" to={`/repositorio?curso=${c.id}`}>
            <strong>{c.nome}</strong>
            <span>{c.total_publicadas} publicadas</span>
          </Link>
        ))}
      </div>
      <p>
        Aluno, orientador ou coordenador? <Link to="/login">Entre no sistema</Link>.
      </p>
    </section>
  );
}

const LIMITE = 10;

export function Busca() {
  const [params, setParams] = useSearchParams();
  const [filtros, setFiltros] = useState(() => Object.fromEntries(params.entries()));
  const atrasado = useDebounce(filtros, 400);
  const [resultado, setResultado] = useState(null);
  const [cache, setCache] = useState("");
  const [erro, setErro] = useState(null);
  const [carregando, setCarregando] = useState(false);
  const { dados: cursos } = useApi("/api/repositorio/cursos/");
  const { dados: orientadores } = useApi("/api/repositorio/orientadores/");

  useEffect(() => {
    const limpos = Object.fromEntries(Object.entries(atrasado).filter(([, v]) => v !== "" && v != null));
    setParams(limpos, { replace: true });
    setCarregando(true);
    setErro(null);
    api
      .get("/api/repositorio/monografias/", { params: { limit: LIMITE, ...limpos } })
      .then((r) => {
        setResultado(r.data);
        setCache([r.headers["x-cache"], r.headers["x-proxy-cache"]].filter(Boolean).join(" / "));
      })
      .catch((e) => setErro(mensagemDeErro(e)))
      .finally(() => setCarregando(false));
  }, [atrasado, setParams]);

  const mudar = (campo) => (e) => setFiltros((f) => ({ ...f, [campo]: e.target.value, offset: campo === "offset" ? e.target.value : 0 }));

  return (
    <section>
      <h1>Pesquisa no repositório</h1>
      <form className="filtros" role="search" onSubmit={(e) => e.preventDefault()}>
        <div className="campo largo">
          <label htmlFor="f-busca">Busca livre</label>
          <input id="f-busca" value={filtros.busca || ""} onChange={mudar("busca")} placeholder="título, resumo, palavras-chave ou texto do PDF" />
        </div>
        <div className="campo">
          <label htmlFor="f-titulo">Título</label>
          <input id="f-titulo" value={filtros.titulo || ""} onChange={mudar("titulo")} />
        </div>
        <div className="campo">
          <label htmlFor="f-autor">Autor</label>
          <input id="f-autor" value={filtros.autor || ""} onChange={mudar("autor")} />
        </div>
        <div className="campo">
          <label htmlFor="f-orientador">Orientador</label>
          <select id="f-orientador" value={filtros.orientador || ""} onChange={mudar("orientador")}>
            <option value="">Todos</option>
            {(orientadores || []).map((o) => (
              <option key={o.id} value={o.id}>
                {o.nome}
              </option>
            ))}
          </select>
        </div>
        <div className="campo">
          <label htmlFor="f-curso">Curso</label>
          <select id="f-curso" value={filtros.curso || ""} onChange={mudar("curso")}>
            <option value="">Todos</option>
            {(cursos || []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.nome}
              </option>
            ))}
          </select>
        </div>
        <div className="campo">
          <label htmlFor="f-ano">Ano de defesa</label>
          <input id="f-ano" inputMode="numeric" value={filtros.ano_defesa || ""} onChange={mudar("ano_defesa")} />
        </div>
        <div className="campo">
          <label htmlFor="f-pc">Palavras-chave</label>
          <input id="f-pc" value={filtros.palavras_chave || ""} onChange={mudar("palavras_chave")} placeholder="separe por vírgula" />
        </div>
        <div className="campo">
          <label htmlFor="f-ordem">Ordenar por</label>
          <select id="f-ordem" value={filtros.ordenar || "relevancia"} onChange={mudar("ordenar")}>
            <option value="relevancia">Relevância</option>
            <option value="recentes">Mais recentes</option>
            <option value="titulo">Título</option>
          </select>
        </div>
      </form>
      {carregando && <Carregando texto="Buscando…" />}
      <Alerta>{erro}</Alerta>
      {resultado && (
        <>
          <p className="mudo" aria-live="polite">
            {resultado.count} resultado(s){cache && <span className="selo">cache: {cache}</span>}
          </p>
          {resultado.count === 0 && <p>Nenhuma monografia encontrada com esses filtros.</p>}
          <ul className="resultados">
            {resultado.results.map((m) => (
              <li key={m.id} className="cartao">
                <h2>
                  <Link to={`/repositorio/${m.id}`}>{m.titulo}</Link>
                </h2>
                <p className="meta">
                  {m.autor_nome} · Orientação: {m.orientador_nome} · {m.curso_nome} · {m.ano_defesa}
                </p>
                {m.trecho ? <Destaque texto={m.trecho} /> : <p className="trecho">{m.resumo?.slice(0, 280)}</p>}
                <p className="tags">
                  {m.palavras_chave.map((p) => (
                    <span key={p} className="tag">
                      {p}
                    </span>
                  ))}
                </p>
              </li>
            ))}
          </ul>
          <Paginacao total={resultado.count} limite={LIMITE} offset={Number(filtros.offset || 0)} onMudar={(o) => setFiltros((f) => ({ ...f, offset: o }))} />
        </>
      )}
    </section>
  );
}

export function DetalhePublico() {
  const { id } = useParams();
  const { dados: m, erro, carregando } = useApi(`/api/repositorio/monografias/${id}/`);
  if (carregando) return <Carregando />;
  if (erro) return <Alerta>{erro}</Alerta>;
  if (!m) return null;
  return (
    <article className="cartao detalhe">
      <Link to="/repositorio">‹ Voltar à pesquisa</Link>
      <h1>{m.titulo}</h1>
      <dl className="metadados">
        <dt>Autor</dt>
        <dd>{m.autor_nome}</dd>
        <dt>Orientador</dt>
        <dd>{m.orientador_nome}</dd>
        <dt>Curso</dt>
        <dd>{m.curso_nome}</dd>
        <dt>Ano de defesa</dt>
        <dd>{m.ano_defesa}</dd>
        <dt>Publicado em</dt>
        <dd>{formatarData(m.publicado_em, false)}</dd>
        <dt>Páginas</dt>
        <dd>{m.paginas}</dd>
        <dt>SHA-256</dt>
        <dd className="hash">{m.arquivo_sha256}</dd>
        <dt>Downloads</dt>
        <dd>{m.downloads ?? "—"}</dd>
      </dl>
      <h2>Resumo</h2>
      <p>{m.resumo}</p>
      <p className="tags">
        {m.palavras_chave.map((p) => (
          <span key={p} className="tag">
            {p}
          </span>
        ))}
      </p>
      <a className="botao" href={m.download_url} target="_blank" rel="noopener noreferrer">
        Baixar PDF
      </a>
    </article>
  );
}
