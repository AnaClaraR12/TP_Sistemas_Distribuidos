import { Route, Routes } from "react-router-dom";
import RotaProtegida from "./auth/RotaProtegida";
import Layout from "./components/Layout";
import { Auditoria, Cadastros, Notificacoes, Usuarios } from "./pages/Administracao";
import { BancaExterna, DetalheBanca, ListaBancas, NovaBanca } from "./pages/Bancas";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import { DetalheMonografia, ListaMonografias, NovaMonografia } from "./pages/Monografias";
import { Busca, DetalhePublico, Home } from "./pages/Publicas";

const GESTORES = ["coordenador", "admin"];

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* públicas (sem login) */}
        <Route path="/" element={<Home />} />
        <Route path="/repositorio" element={<Busca />} />
        <Route path="/repositorio/:id" element={<DetalhePublico />} />
        <Route path="/login" element={<Login />} />
        <Route path="/banca/externo/:token" element={<BancaExterna />} />

        {/* restritas */}
        <Route path="/dashboard" element={<RotaProtegida><Dashboard /></RotaProtegida>} />
        <Route path="/monografias" element={<RotaProtegida><ListaMonografias /></RotaProtegida>} />
        <Route path="/monografias/nova" element={<RotaProtegida papeis={["aluno", "admin"]}><NovaMonografia /></RotaProtegida>} />
        <Route path="/monografias/:id" element={<RotaProtegida><DetalheMonografia /></RotaProtegida>} />
        <Route path="/bancas" element={<RotaProtegida><ListaBancas /></RotaProtegida>} />
        <Route path="/bancas/nova" element={<RotaProtegida papeis={["professor", ...GESTORES]}><NovaBanca /></RotaProtegida>} />
        <Route path="/bancas/:id" element={<RotaProtegida><DetalheBanca /></RotaProtegida>} />
        <Route path="/cadastros" element={<RotaProtegida papeis={GESTORES}><Cadastros /></RotaProtegida>} />
        <Route path="/auditoria" element={<RotaProtegida papeis={GESTORES}><Auditoria /></RotaProtegida>} />
        <Route path="/usuarios" element={<RotaProtegida papeis={["admin"]}><Usuarios /></RotaProtegida>} />
        <Route path="/notificacoes" element={<RotaProtegida><Notificacoes /></RotaProtegida>} />
        <Route path="*" element={<div className="cartao"><h1>Página não encontrada</h1></div>} />
      </Route>
    </Routes>
  );
}
