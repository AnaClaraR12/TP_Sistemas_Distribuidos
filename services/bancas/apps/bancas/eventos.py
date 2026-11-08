"""Consumers do bancas-service (read models + cálculo assíncrono do resultado)."""

from __future__ import annotations

from apps.bancas.models import MonografiaRef, ProfessorRef
from apps.bancas.servicos import calcular_resultado

_CAMPOS_MONO = ("titulo", "status", "aprovacao_orientador", "aluno_id", "orientador_id", "curso_id")


def on_monografia(envelope: dict) -> None:
    d = envelope["data"]
    if envelope["type"] == "monografia.excluida":
        MonografiaRef.objects.filter(pk=d["id"]).delete()
        return
    if "status" not in d:  # ex.: texto_extraido não carrega o estado
        return
    MonografiaRef.objects.update_or_create(pk=d["id"], defaults={c: d.get(c) for c in _CAMPOS_MONO})


def on_professor(envelope: dict) -> None:
    d = envelope["data"]
    if envelope["type"].endswith(".deleted"):
        ProfessorRef.objects.filter(pk=d["id"]).delete()
        return
    ProfessorRef.objects.update_or_create(
        pk=d["id"],
        defaults={"nome": d["nome"], "email": d["email"].lower(), "departamento": d.get("departamento") or ""},
    )


def on_avaliacao_registrada(envelope: dict) -> None:
    calcular_resultado(envelope["data"]["banca_id"])


HANDLERS = {
    "monografia.*": on_monografia,
    "cadastro.professor.*": on_professor,
    "avaliacao.registrada": on_avaliacao_registrada,
}
