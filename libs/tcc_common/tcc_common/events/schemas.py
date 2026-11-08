"""Catálogo de eventos (Anexo C) — campos obrigatórios de ``data`` por tipo.

Validado na publicação (``registrar_evento``) e usado nos testes de contrato dos
consumers, garantindo que produtor e consumidor concordam com o formato.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

_MONO_BASE = {"id", "titulo", "status", "aprovacao_orientador", "aluno_id", "orientador_id", "curso_id"}

CAMPOS_OBRIGATORIOS: dict[str, set[str]] = {
    "cadastro.curso.upserted": {"id", "nome", "codigo", "coordenador_id"},
    "cadastro.curso.deleted": {"id"},
    "cadastro.professor.upserted": {"id", "nome", "email", "departamento"},
    "cadastro.professor.deleted": {"id"},
    "cadastro.aluno.upserted": {"id", "nome", "email", "matricula", "curso_id", "orientador_id"},
    "cadastro.aluno.deleted": {"id"},
    "monografia.submetida": _MONO_BASE | {"sha256", "submetida_em"},
    "monografia.texto_extraido": {"id", "paginas", "sem_texto"},
    "monografia.extracao_falhou": {"id", "motivo"},
    "monografia.aprovada_orientador": _MONO_BASE | {"sha256_aprovado"},
    "monografia.rejeitada_orientador": _MONO_BASE | {"motivo"},
    "monografia.resultado_registrado": _MONO_BASE | {"resultado", "exige_correcao"},
    "monografia.excluida": {"id"},
    "monografia.integridade_violada": _MONO_BASE | {"sha_esperado", "sha_atual"},
    "monografia.publicada": _MONO_BASE
    | {
        "resumo",
        "palavras_chave",
        "autor_nome",
        "orientador_nome",
        "curso_nome",
        "ano_defesa",
        "sha256",
        "publicada_em",
    },
    "documento.enviado": {"monografia_id", "tipo"},
    "banca.convite_enviado": {"banca_id", "monografia_id", "membro", "expira_em"},
    "banca.agendada": {"banca_id", "monografia_id", "aluno_id", "data_hora", "local", "link", "membros"},
    "banca.cancelada": {"banca_id", "monografia_id", "aluno_id", "motivo", "membros"},
    "avaliacao.registrada": {"banca_id", "avaliacao_id", "membro_id"},
    "banca.resultado_calculado": {
        "banca_id",
        "monografia_id",
        "aluno_id",
        "orientador_id",
        "resultado",
        "media",
        "exige_correcao",
        "data_defesa",
    },
    "repositorio.indexado": {"monografia_id"},
    "audit.registro": {"usuario_id", "acao", "recurso", "recurso_id", "detalhes"},
}

#: campos de ``data`` que contêm segredo: são mascarados no outbox após a publicação
CAMPOS_SENSIVEIS: dict[str, set[str]] = {"banca.convite_enviado": {"token"}}


class EventoInvalido(ValueError):
    pass


def validar_dados(tipo: str, data: dict) -> None:
    obrigatorios = CAMPOS_OBRIGATORIOS.get(tipo)
    if obrigatorios is None:
        raise EventoInvalido(f"Tipo de evento desconhecido: {tipo}")
    faltando = obrigatorios - set(data)
    if faltando:
        raise EventoInvalido(f"Evento {tipo} sem campos obrigatórios: {sorted(faltando)}")
