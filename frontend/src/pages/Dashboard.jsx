import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import PainelGraficos, { PorAno } from "../charts/Graficos";
import Carregando from "../components/Carregando";
import { Alerta, LinhaDoTempo, Status } from "../components/comuns";
import { useApi } from "../utils/hooks";
import { formatarData } from "../utils/validacao";

function MinhasSubmissoes() {
  const { dados, erro, carregando } = useApi("/api/monografias/");
  if (carregando) return <Carregando />;
  if (erro) return <Alerta>{erro}</Alerta>;
  const itens = dados?.results || [];
  return (
    <section className="cartao">
      <h2>Minhas submissões</h2>
      {!itens.length && (
        <p>
          Você ainda não tem monografias. <Link to="/monografias/nova">Criar rascunho</Link>
        </p>
      )}
      {itens.map((m) => (
        <div key={m.id} className="item-dashboard">
          <h3>
            <Link to={`/monografias/${m.id}`}>{m.titulo}</Link> <Status valor={m.status} />
          </h3>
          <LinhaDoTempo monografia={m} />
          {m.motivo_rejeicao && m.aprovacao_orientador === "rejeitada" && (
            <Alerta tipo="aviso">Devolvida pelo orientador: {m.motivo_rejeicao}</Alerta>
          )}
          {m.pendencias_publicacao?.length > 0 && (
            <p className="mudo">Pendências para publicação: {m.pendencias_publicacao.join(", ")}</p>
          )}
        </div>
      ))}
    </section>
  );
}

function PendenciasAprovacao() {
  const { dados, carregando } = useApi("/api/monografias/", { params: { status: "em_avaliacao", aprovacao_orientador: "pendente" } });
  const { professorId } = useAuth();
  if (carregando) return <Carregando />;
  const itens = (dados?.results || []).filter((m) => m.orientador_id === professorId);
  return (
    <section className="cartao">
      <h2>Aguardando sua aprovação ({itens.length})</h2>
      {!itens.length && <p className="mudo">Nenhuma pendência.</p>}
      <ul>
        {itens.map((m) => (
          <li key={m.id}>
            <Link to={`/monografias/${m.id}`}>{m.titulo}</Link> — submetida em {formatarData(m.submetida_em)}
            {!m.texto_extraido && <span className="selo">processando PDF…</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function MinhasBancas() {
  const { dados, carregando } = useApi("/api/bancas/", { params: { minhas: 1 } });
  if (carregando) return <Carregando />;
  const itens = dados?.results || [];
  return (
    <section className="cartao">
      <h2>Minhas bancas ({itens.length})</h2>
      {!itens.length && <p className="mudo">Nenhuma banca.</p>}
      <ul>
        {itens.map((b) => (
          <li key={b.id}>
            <Link to={`/bancas/${b.id}`}>{b.monografia?.titulo || b.id}</Link> — {formatarData(b.data_hora_inicio)} <Status valor={b.status} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function BancasPendentes() {
  const { dados } = useApi("/api/bancas/", { params: { status: "em_organizacao" } });
  const itens = dados?.results || [];
  return (
    <section className="cartao">
      <h2>Bancas em organização ({itens.length})</h2>
      <ul>
        {itens.map((b) => (
          <li key={b.id}>
            <Link to={`/bancas/${b.id}`}>{b.monografia?.titulo || b.id}</Link> —{" "}
            {b.membros.filter((m) => m.confirmacao === "confirmado").length}/{b.membros.length} confirmações
          </li>
        ))}
      </ul>
      <Link className="botao" to="/bancas/nova">
        Agendar nova banca
      </Link>
    </section>
  );
}

function Notificacoes() {
  const { dados } = useApi("/api/notificacoes/minhas/", { params: { nao_lidas: 1, limit: 5 } });
  const itens = dados?.results || [];
  return (
    <section className="cartao">
      <h2>Notificações não lidas ({dados?.count ?? 0})</h2>
      <ul>
        {itens.map((n) => (
          <li key={n.id}>
            {n.assunto} <span className="mudo">— {formatarData(n.criada_em)}</span>
          </li>
        ))}
      </ul>
      <Link to="/notificacoes">Ver todas</Link>
    </section>
  );
}

function GraficoAnoProfessor() {
  const { dados } = useApi("/api/relatorios/monografias-por-ano-defesa/");
  return <PorAno dados={dados?.dados} />;
}

const WIDGETS = {
  linha_do_tempo_submissao: MinhasSubmissoes,
  pendencias_aprovacao: PendenciasAprovacao,
  minhas_bancas: MinhasBancas,
  bancas_pendentes: BancasPendentes,
  notificacoes: Notificacoes,
  grafico_por_ano: GraficoAnoProfessor,
};

export default function Dashboard() {
  const { config, usuario } = useAuth();
  if (!config) return <Carregando />;
  const temGraficos = config.widgets.includes("kpis");
  return (
    <section>
      <h1>Olá, {usuario?.nome || usuario?.email}</h1>
      <p className="mudo">Painel do perfil: {config.papel}</p>
      {temGraficos && <PainelGraficos />}
      <div className="grade-widgets">
        {config.widgets
          .filter((w) => WIDGETS[w])
          .map((w) => {
            const W = WIDGETS[w];
            return <W key={w} />;
          })}
      </div>
    </section>
  );
}
