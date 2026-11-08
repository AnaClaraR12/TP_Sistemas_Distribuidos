import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";
import Carregando from "../components/Carregando";

/** Redireciona para /login quando não autenticado; 403 visual quando o papel não permite. */
export default function RotaProtegida({ papeis, children }) {
  const { usuario, carregando, papel } = useAuth();
  const local = useLocation();
  if (carregando) return <Carregando />;
  if (!usuario) return <Navigate to="/login" replace state={{ de: local.pathname + local.search }} />;
  if (papeis && !papeis.includes(papel)) {
    return (
      <div className="cartao erro" role="alert">
        <h2>Acesso negado</h2>
        <p>Seu perfil ({papel}) não tem permissão para esta página.</p>
      </div>
    );
  }
  return children;
}
