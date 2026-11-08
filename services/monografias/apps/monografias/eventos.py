"""Consumers do monografias-service."""

from __future__ import annotations

import logging

from django.utils.dateparse import parse_datetime

from apps.monografias.models import AlunoRef, CursoRef, Monografia, ProfessorRef
from apps.monografias.servicos import chave_lock_upload
from tcc_common.cache.redis import liberar_lock

logger = logging.getLogger(__name__)

_REFS = {"aluno": AlunoRef, "professor": ProfessorRef, "curso": CursoRef}
_CAMPOS = {
    "aluno": ("nome", "email", "matricula", "curso_id", "orientador_id"),
    "professor": ("nome", "email", "departamento"),
    "curso": ("nome", "codigo", "coordenador_id"),
}


def on_cadastro(envelope: dict) -> None:
    """cadastro.<entidade>.<upserted|deleted> -> mantém o read model local."""
    _, entidade, acao = envelope["type"].split(".")
    modelo = _REFS.get(entidade)
    if modelo is None:
        return
    d = envelope["data"]
    if acao == "deleted":
        modelo.objects.filter(pk=d["id"]).delete()
        return
    defaults = {}
    for campo in _CAMPOS[entidade]:
        valor = d.get(campo)
        texto = not campo.endswith("_id")
        defaults[campo] = (valor or "") if texto else valor
    modelo.objects.update_or_create(pk=d["id"], defaults=defaults)


def on_resultado_banca(envelope: dict) -> None:
    d = envelope["data"]
    m = Monografia.objects.select_for_update().filter(pk=d["monografia_id"]).first()
    if m is None:
        logger.warning("resultado_para_monografia_inexistente", extra={"monografia_id": d["monografia_id"]})
        return
    if m.resultado_banca:  # já registrado (idempotência de domínio)
        return
    m.registrar_resultado_banca(
        d["resultado"], d["exige_correcao"], parse_datetime(d["data_defesa"]) if d.get("data_defesa") else None
    )


def on_extracao_concluida(envelope: dict) -> None:
    """monografia.texto_extraido / extracao_falhou -> libera o lock e marca o flag."""
    d = envelope["data"]
    liberar_lock(chave_lock_upload(d["id"]))
    Monografia.objects.filter(pk=d["id"]).update(texto_extraido=envelope["type"] == "monografia.texto_extraido")


HANDLERS = {
    "cadastro.#": on_cadastro,
    "banca.resultado_calculado": on_resultado_banca,
    "monografia.texto_extraido": on_extracao_concluida,
    "monografia.extracao_falhou": on_extracao_concluida,
}
