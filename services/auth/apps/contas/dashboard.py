"""Widgets e menus do dashboard permitidos por papel (consumido pelo frontend)."""

_MENUS = {
    "repositorio": {"rota": "/repositorio", "titulo": "Repositório público"},
    "minhas_monografias": {"rota": "/monografias", "titulo": "Minhas monografias"},
    "nova_monografia": {"rota": "/monografias/nova", "titulo": "Nova monografia"},
    "orientandos": {"rota": "/monografias", "titulo": "Orientandos"},
    "bancas": {"rota": "/bancas", "titulo": "Bancas"},
    "minhas_bancas": {"rota": "/bancas?minhas=1", "titulo": "Minhas bancas"},
    "nova_banca": {"rota": "/bancas/nova", "titulo": "Agendar banca"},
    "cadastros": {"rota": "/cadastros", "titulo": "Cadastros"},
    "auditoria": {"rota": "/auditoria", "titulo": "Auditoria"},
    "usuarios": {"rota": "/usuarios", "titulo": "Usuários"},
    "notificacoes": {"rota": "/notificacoes", "titulo": "Notificações"},
}

_CONFIG = {
    "aluno": {
        "widgets": ["linha_do_tempo_submissao", "notificacoes"],
        "menus": ["minhas_monografias", "nova_monografia", "repositorio", "notificacoes"],
    },
    "professor": {
        "widgets": ["pendencias_aprovacao", "minhas_bancas", "grafico_por_ano", "notificacoes"],
        "menus": ["orientandos", "minhas_bancas", "nova_banca", "repositorio", "notificacoes"],
    },
    "coordenador": {
        "widgets": [
            "kpis",
            "grafico_por_curso",
            "grafico_por_orientador",
            "grafico_por_ano",
            "grafico_taxa_aprovacao",
            "grafico_tempo_medio",
            "bancas_pendentes",
        ],
        "menus": [
            "orientandos",
            "bancas",
            "nova_banca",
            "minhas_bancas",
            "cadastros",
            "auditoria",
            "repositorio",
            "notificacoes",
        ],
    },
    "admin": {
        "widgets": [
            "kpis",
            "grafico_por_curso",
            "grafico_por_orientador",
            "grafico_por_ano",
            "grafico_taxa_aprovacao",
            "grafico_tempo_medio",
            "bancas_pendentes",
        ],
        "menus": [
            "orientandos",
            "bancas",
            "nova_banca",
            "cadastros",
            "auditoria",
            "usuarios",
            "repositorio",
            "notificacoes",
        ],
    },
}


def configuracao_dashboard(papel: str) -> dict:
    cfg = _CONFIG.get(papel, {"widgets": [], "menus": ["repositorio"]})
    return {"papel": papel, "widgets": cfg["widgets"], "menus": [{"id": m, **_MENUS[m]} for m in cfg["menus"]]}
