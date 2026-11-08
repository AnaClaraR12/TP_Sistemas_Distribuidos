export default function Carregando({ texto = "Carregando…" }) {
  return (
    <div className="carregando" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {texto}
    </div>
  );
}
