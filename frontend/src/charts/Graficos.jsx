import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";
import { Bar, Doughnut, Line } from "react-chartjs-2";
import Carregando from "../components/Carregando";
import { Alerta } from "../components/comuns";
import { useApi } from "../utils/hooks";

ChartJS.register(CategoryScale, LinearScale, BarElement, LineElement, PointElement, ArcElement, Tooltip, Legend);

// Paleta com bom contraste e distinguível para daltonismo (Okabe–Ito)
export const CORES = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"];

const base = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } };

function Caixa({ titulo, children, vazio }) {
  return (
    <figure className="grafico cartao">
      <figcaption>{titulo}</figcaption>
      <div className="grafico-area">{vazio ? <p className="mudo">Sem dados para exibir.</p> : children}</div>
    </figure>
  );
}

export function PorCurso({ dados }) {
  return (
    <Caixa titulo="Monografias por curso" vazio={!dados?.length}>
      <Bar
        options={{ ...base, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }}
        data={{
          labels: dados?.map((d) => d.curso_nome || "—"),
          datasets: [
            { label: "Total", data: dados?.map((d) => d.total), backgroundColor: CORES[0] },
            { label: "Publicadas", data: dados?.map((d) => d.publicadas), backgroundColor: CORES[2] },
          ],
        }}
      />
    </Caixa>
  );
}

export function PorOrientador({ dados }) {
  return (
    <Caixa titulo="Monografias por orientador" vazio={!dados?.length}>
      <Bar
        options={{ ...base, indexAxis: "y", scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } }}
        data={{
          labels: dados?.map((d) => d.orientador_nome || "—"),
          datasets: [{ label: "Orientações", data: dados?.map((d) => d.total), backgroundColor: CORES[1] }],
        }}
      />
    </Caixa>
  );
}

export function PorAno({ dados }) {
  return (
    <Caixa titulo="Monografias por ano de defesa" vazio={!dados?.length}>
      <Line
        options={{ ...base, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } }}
        data={{
          labels: dados?.map((d) => d.ano),
          datasets: [
            { label: "Defesas", data: dados?.map((d) => d.total), borderColor: CORES[0], backgroundColor: CORES[0], tension: 0.25 },
            { label: "Aprovadas", data: dados?.map((d) => d.aprovadas), borderColor: CORES[2], backgroundColor: CORES[2], tension: 0.25 },
          ],
        }}
      />
    </Caixa>
  );
}

export function TaxaAprovacao({ dados }) {
  const g = dados?.geral;
  const taxa = g?.taxa;
  return (
    <>
      <Caixa titulo={`Taxa de aprovação${taxa != null ? `: ${(taxa * 100).toFixed(1)}%` : ""}`} vazio={!g || g.aprovadas + g.reprovadas === 0}>
        <Doughnut
          options={{ ...base, cutout: "65%" }}
          data={{
            labels: ["Aprovadas", "Reprovadas"],
            datasets: [{ data: [g?.aprovadas, g?.reprovadas], backgroundColor: [CORES[2], CORES[3]] }],
          }}
        />
      </Caixa>
      <Caixa titulo="Taxa de aprovação por ano (%)" vazio={!dados?.por_ano?.length}>
        <Bar
          options={{ ...base, scales: { y: { beginAtZero: true, max: 100 } } }}
          data={{
            labels: dados?.por_ano?.map((d) => d.ano),
            datasets: [{ label: "% aprovadas", data: dados?.por_ano?.map((d) => (d.taxa ?? 0) * 100), backgroundColor: CORES[5] }],
          }}
        />
      </Caixa>
    </>
  );
}

export function TempoMedio({ dados }) {
  return (
    <>
      <div className="kpi cartao">
        <span className="kpi-valor">{dados?.geral_dias ?? "—"}</span>
        <span className="kpi-rotulo">dias em média da submissão à defesa ({dados?.amostra || 0} defesas)</span>
      </div>
      <Caixa titulo="Tempo médio submissão → defesa por curso (dias)" vazio={!dados?.por_curso?.length}>
        <Bar
          options={{ ...base, scales: { y: { beginAtZero: true } } }}
          data={{
            labels: dados?.por_curso?.map((d) => d.curso_nome || "—"),
            datasets: [{ label: "Dias", data: dados?.por_curso?.map((d) => d.media_dias), backgroundColor: CORES[4] }],
          }}
        />
      </Caixa>
    </>
  );
}

/** Dashboard completo a partir de /api/relatorios/resumo/ (uma chamada). */
export default function PainelGraficos() {
  const { dados, erro, carregando } = useApi("/api/relatorios/resumo/");
  if (carregando && !dados) return <Carregando texto="Carregando indicadores…" />;
  if (erro) return <Alerta>{erro}</Alerta>;
  const d = dados?.dados;
  if (!d) return null;
  return (
    <section aria-label="Indicadores">
      <div className="kpis">
        <div className="kpi cartao">
          <span className="kpi-valor">{d.total}</span>
          <span className="kpi-rotulo">monografias acompanhadas</span>
        </div>
        <div className="kpi cartao">
          <span className="kpi-valor">{d.por_status?.publicada || 0}</span>
          <span className="kpi-rotulo">publicadas</span>
        </div>
        <div className="kpi cartao">
          <span className="kpi-valor">{d.por_status?.em_avaliacao || 0}</span>
          <span className="kpi-rotulo">em avaliação</span>
        </div>
        <TempoMedio dados={d.tempo_medio_submissao_defesa} />
      </div>
      <div className="graficos">
        <PorCurso dados={d.por_curso} />
        <PorOrientador dados={d.por_orientador} />
        <PorAno dados={d.por_ano} />
        <TaxaAprovacao dados={d.taxa_aprovacao} />
      </div>
    </section>
  );
}
