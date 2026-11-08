"""Métricas do dashboard — agregações no banco (Count/Avg/ExtractYear), sem loops em Python."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import Coalesce, ExtractYear

from apps.relatorios.models import FatoMonografia
from tcc_common.cache.redis import get_redis

logger = logging.getLogger(__name__)

APROVADAS = Count("monografia_id", filter=Q(resultado="aprovada"))
REPROVADAS = Count("monografia_id", filter=Q(resultado="reprovada"))
PUBLICADAS = Count("monografia_id", filter=Q(status="publicada"))


# --- escopo por papel -------------------------------------------------------------------


def escopo_do_usuario(u) -> tuple[str, Q]:
    if u.papel == "admin":
        return "admin", Q()
    if u.papel == "coordenador":
        ids = sorted(u.curso_ids)
        return f"curso:{','.join(ids)}", Q(curso_id__in=ids) | Q(orientador_id=u.professor_id)
    if u.papel == "professor":
        return f"prof:{u.professor_id}", Q(orientador_id=u.professor_id)
    return f"aluno:{u.aluno_id}", Q(aluno_id=u.aluno_id)


# --- cache ------------------------------------------------------------------------------


def com_cache(nome: str, escopo: str, calcular: Callable[[], dict]) -> tuple[dict, str]:
    chave = f"relatorio:{nome}:{hashlib.sha256(escopo.encode()).hexdigest()[:16]}"
    try:
        r = get_redis()
        bruto = r.get(chave)
        if bruto:
            return json.loads(bruto), "HIT"
        dados = calcular()
        r.set(chave, json.dumps(dados, default=str), ex=settings.RELATORIO_CACHE_TTL_S)
        return dados, "MISS"
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache_relatorio_indisponivel", extra={"erro": repr(exc)})
        return calcular(), "MISS"


def invalidar_cache() -> None:
    try:
        r = get_redis()
        chaves = list(r.scan_iter("relatorio:*", count=500))
        if chaves:
            r.delete(*chaves)
    except Exception as exc:  # noqa: BLE001
        logger.warning("falha_invalidar_cache_relatorio", extra={"erro": repr(exc)})


# --- métricas ------------------------------------------------------------------------------


def _taxa(aprovadas: int, reprovadas: int) -> float | None:
    total = aprovadas + reprovadas
    return round(aprovadas / total, 4) if total else None


def _dias(td: timedelta | None) -> float | None:
    return round(td.total_seconds() / 86400, 1) if td is not None else None


def por_curso(qs) -> list[dict]:
    linhas = (
        qs.values("curso_id", "curso_nome")
        .annotate(total=Count("monografia_id"), publicadas=PUBLICADAS, aprovadas=APROVADAS, reprovadas=REPROVADAS)
        .order_by("-total", "curso_nome")
    )
    return [{**row, "curso_id": str(row["curso_id"]) if row["curso_id"] else None} for row in linhas]


def por_orientador(qs) -> list[dict]:
    linhas = (
        qs.values("orientador_id", "orientador_nome")
        .annotate(total=Count("monografia_id"), publicadas=PUBLICADAS, aprovadas=APROVADAS, reprovadas=REPROVADAS)
        .order_by("-total", "orientador_nome")
    )
    return [{**row, "orientador_id": str(row["orientador_id"]) if row["orientador_id"] else None} for row in linhas]


def por_ano(qs) -> list[dict]:
    return list(
        qs.annotate(ano=Coalesce("ano_defesa", ExtractYear("defendida_em")))
        .exclude(ano__isnull=True)
        .values("ano")
        .annotate(total=Count("monografia_id"), aprovadas=APROVADAS, reprovadas=REPROVADAS, publicadas=PUBLICADAS)
        .order_by("ano")
    )


def taxa_aprovacao(qs) -> dict:
    geral = qs.aggregate(aprovadas=APROVADAS, reprovadas=REPROVADAS)
    cursos = (
        qs.values("curso_id", "curso_nome").annotate(aprovadas=APROVADAS, reprovadas=REPROVADAS).order_by("curso_nome")
    )
    anos = (
        qs.annotate(ano=Coalesce("ano_defesa", ExtractYear("defendida_em")))
        .exclude(ano__isnull=True)
        .values("ano")
        .annotate(aprovadas=APROVADAS, reprovadas=REPROVADAS)
        .order_by("ano")
    )
    return {
        "geral": {**geral, "taxa": _taxa(geral["aprovadas"], geral["reprovadas"])},
        "por_curso": [
            {
                "curso_id": str(c["curso_id"]) if c["curso_id"] else None,
                "curso_nome": c["curso_nome"],
                "aprovadas": c["aprovadas"],
                "reprovadas": c["reprovadas"],
                "taxa": _taxa(c["aprovadas"], c["reprovadas"]),
            }
            for c in cursos
        ],
        "por_ano": [{**a, "taxa": _taxa(a["aprovadas"], a["reprovadas"])} for a in anos],
    }


DURACAO = ExpressionWrapper(F("defendida_em") - F("submetida_em"), output_field=DurationField())


def tempo_medio(qs) -> dict:
    base = qs.filter(defendida_em__isnull=False, submetida_em__isnull=False)
    geral = base.aggregate(media=Avg(DURACAO), n=Count("monografia_id"))
    cursos = (
        base.values("curso_id", "curso_nome")
        .annotate(media=Avg(DURACAO), n=Count("monografia_id"))
        .order_by("curso_nome")
    )
    return {
        "geral_dias": _dias(geral["media"]),
        "amostra": geral["n"],
        "por_curso": [
            {
                "curso_id": str(c["curso_id"]) if c["curso_id"] else None,
                "curso_nome": c["curso_nome"],
                "media_dias": _dias(c["media"]),
                "amostra": c["n"],
            }
            for c in cursos
        ],
    }


def resumo(qs) -> dict:
    por_status = dict(qs.values_list("status").annotate(n=Count("monografia_id")).values_list("status", "n"))
    return {
        "total": sum(por_status.values()),
        "por_status": por_status,
        "por_curso": por_curso(qs),
        "por_orientador": por_orientador(qs),
        "por_ano": por_ano(qs),
        "taxa_aprovacao": taxa_aprovacao(qs),
        "tempo_medio_submissao_defesa": tempo_medio(qs),
    }


RELATORIOS = {
    "monografias-por-curso": por_curso,
    "monografias-por-orientador": por_orientador,
    "monografias-por-ano-defesa": por_ano,
    "taxa-aprovacao": taxa_aprovacao,
    "tempo-medio-submissao-defesa": tempo_medio,
    "resumo": resumo,
}


def calcular(nome: str, filtro: Q):
    return RELATORIOS[nome](FatoMonografia.objects.filter(filtro))
