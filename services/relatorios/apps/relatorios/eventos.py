"""Consumers idempotentes (upsert) que mantêm FatoMonografia."""

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.relatorios.metricas import invalidar_cache
from apps.relatorios.models import CursoRef, FatoMonografia, ProfessorRef


def _dt(valor):
    return parse_datetime(valor) if isinstance(valor, str) else valor


def _ano(dt) -> int | None:
    return timezone.localtime(dt).year if dt else None


def _nomes(curso_id, orientador_id) -> dict:
    out = {}
    if curso_id and (c := CursoRef.objects.filter(pk=curso_id).first()):
        out["curso_nome"] = c.nome
    if orientador_id and (p := ProfessorRef.objects.filter(pk=orientador_id).first()):
        out["orientador_nome"] = p.nome
    return out


def on_monografia(env: dict) -> None:
    d = env["data"]
    if env["type"] == "monografia.excluida":
        FatoMonografia.objects.filter(pk=d["id"]).delete()
        invalidar_cache()
        return
    if "status" not in d:
        return
    campos = {k: d.get(k) for k in ("titulo", "status", "aluno_id", "orientador_id", "curso_id")}
    campos.update(_nomes(d.get("curso_id"), d.get("orientador_id")))
    if d.get("curso_nome"):
        campos["curso_nome"] = d["curso_nome"]
    if d.get("orientador_nome"):
        campos["orientador_nome"] = d["orientador_nome"]
    if env["type"] == "monografia.submetida":
        campos["submetida_em"] = _dt(d["submetida_em"])
    if env["type"] == "monografia.resultado_registrado":
        campos["resultado"] = d["resultado"]
        if d.get("defendida_em"):
            campos["defendida_em"] = _dt(d["defendida_em"])
            campos["ano_defesa"] = _ano(campos["defendida_em"])
    if env["type"] == "monografia.publicada":
        campos["publicada_em"] = _dt(d["publicada_em"])
        if d.get("defendida_em"):
            campos["defendida_em"] = _dt(d["defendida_em"])
        campos["ano_defesa"] = d.get("ano_defesa") or _ano(campos.get("defendida_em"))
    FatoMonografia.objects.update_or_create(pk=d["id"], defaults=campos)
    invalidar_cache()


def on_resultado_banca(env: dict) -> None:
    d = env["data"]
    defendida = _dt(d["data_defesa"])
    FatoMonografia.objects.update_or_create(
        pk=d["monografia_id"],
        defaults={
            "resultado": d["resultado"],
            "defendida_em": defendida,
            "ano_defesa": _ano(defendida),
            **{k: d[k] for k in ("aluno_id", "orientador_id", "curso_id") if d.get(k)},
        },
    )
    invalidar_cache()


def on_cadastro(env: dict) -> None:
    _, entidade, acao = env["type"].split(".")
    d = env["data"]
    if entidade == "curso":
        if acao == "deleted":
            CursoRef.objects.filter(pk=d["id"]).delete()
        else:
            CursoRef.objects.update_or_create(pk=d["id"], defaults={"nome": d["nome"]})
            FatoMonografia.objects.filter(curso_id=d["id"]).update(curso_nome=d["nome"])
    elif entidade == "professor":
        if acao == "deleted":
            ProfessorRef.objects.filter(pk=d["id"]).delete()
        else:
            ProfessorRef.objects.update_or_create(pk=d["id"], defaults={"nome": d["nome"]})
            FatoMonografia.objects.filter(orientador_id=d["id"]).update(orientador_nome=d["nome"])
    invalidar_cache()


HANDLERS = {
    "monografia.*": on_monografia,
    "banca.resultado_calculado": on_resultado_banca,
    "cadastro.#": on_cadastro,
}
