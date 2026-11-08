"""Regras do bancas-service: agendamento em 2 etapas (P4), tokens externos (P10),
conflito de horário com lock, avaliações e cálculo do resultado (P5)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import DateTimeField, ExpressionWrapper, F, Q, Value
from django.utils import timezone

from apps.bancas.models import Avaliacao, Banca, MembroBanca, MonografiaRef, ProfessorRef
from tcc_common.api.exceptions import ErroNegocio
from tcc_common.audit.auditoria import registrar_auditoria
from tcc_common.events.outbox import registrar_evento

logger = logging.getLogger(__name__)


# --- monografia (read model + fallback HTTP interno) -----------------------------------


def obter_monografia(monografia_id) -> MonografiaRef:
    """Read model local; se ausente/defasado, consulta o monografias-service (HTTP interno)."""
    ref = MonografiaRef.objects.filter(pk=monografia_id).first()
    if ref and ref.apta_para_banca:
        return ref
    try:
        resp = requests.get(
            f"{settings.SERVICOS_URLS['monografias']}/internal/monografias/{monografia_id}/",
            headers={"X-Service-Token": settings.SERVICE_TOKEN},
            timeout=3,
        )
    except requests.RequestException as exc:
        logger.warning("fallback_monografias_indisponivel", extra={"erro": repr(exc)})
        if ref:
            return ref
        raise ErroNegocio("Monografia não encontrada.", codigo="monografia_nao_encontrada", status_code=404) from exc
    if resp.status_code == 404:
        raise ErroNegocio("Monografia não encontrada.", codigo="monografia_nao_encontrada", status_code=404)
    resp.raise_for_status()
    d = resp.json()
    ref, _ = MonografiaRef.objects.update_or_create(
        pk=d["id"],
        defaults={
            k: d.get(k) for k in ("titulo", "status", "aprovacao_orientador", "aluno_id", "orientador_id", "curso_id")
        },
    )
    return ref


def exigir_aprovacao_orientador(ref: MonografiaRef) -> None:
    if not ref.apta_para_banca:
        raise ErroNegocio(
            "A banca só pode ser agendada após a aprovação do orientador.",
            codigo="orientador_nao_aprovou",
            detalhes={"status": ref.status, "aprovacao_orientador": ref.aprovacao_orientador},
        )


# --- tokens de membro externo -----------------------------------------------------------


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def gerar_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def membro_por_token(token: str) -> MembroBanca:
    """Valida hash, revogação e expiração. Nunca loga o token."""
    if not token or len(token) > 200:
        raise ErroNegocio("Token ausente ou inválido.", codigo="token_invalido", status_code=401)
    membro = MembroBanca.objects.select_related("banca").filter(token_hash=hash_token(token), tipo="externo").first()
    if membro is None:
        raise ErroNegocio("Token inválido.", codigo="token_invalido", status_code=401)
    if membro.token_revogado:
        raise ErroNegocio("Token revogado.", codigo="token_revogado", status_code=401)
    if membro.token_expira_em and membro.token_expira_em < timezone.now():
        raise ErroNegocio("Token expirado.", codigo="token_expirado", status_code=401)
    return membro


def _expiracao_token(banca: Banca):
    return banca.data_hora_inicio + timedelta(days=settings.TOKEN_EXTERNO_DIAS_APOS_BANCA)


def _evento_convite(banca: Banca, membro: MembroBanca, token: str | None, ref: MonografiaRef | None) -> None:
    registrar_evento(
        "banca.convite_enviado",
        {
            "banca_id": banca.id,
            "monografia_id": banca.monografia_id,
            "titulo": ref.titulo if ref else "",
            "data_hora": banca.data_hora_inicio,
            "local": banca.local,
            "link": banca.link,
            "membro": {
                "id": membro.id,
                "nome": membro.nome,
                "email": membro.email,
                "tipo": membro.tipo,
                "funcao": membro.funcao,
            },
            "token": token,
            "expira_em": membro.token_expira_em,
        },
    )


def adicionar_membro(banca: Banca, dados: dict, ref: MonografiaRef | None, usuario=None, request=None) -> MembroBanca:
    tipo = dados["tipo"]
    if tipo == MembroBanca.Tipo.INTERNO:
        prof = ProfessorRef.objects.filter(pk=dados["professor_id"]).first()
        if prof is None:
            raise ErroNegocio(
                "Professor não encontrado.",
                codigo="professor_nao_encontrado",
                status_code=400,
                detalhes={"professor_id": str(dados["professor_id"])},
            )
        membro = MembroBanca(
            banca=banca,
            tipo=tipo,
            professor_id=prof.id,
            nome=prof.nome,
            email=prof.email.lower(),
            funcao=dados.get("funcao") or MembroBanca.Funcao.MEMBRO,
        )
        token = None
    else:
        token, h = gerar_token()
        membro = MembroBanca(
            banca=banca,
            tipo=tipo,
            nome=dados["nome"],
            email=dados["email"].lower(),
            instituicao=dados.get("instituicao"),
            funcao=dados.get("funcao") or MembroBanca.Funcao.MEMBRO,
            token_hash=h,
            token_expira_em=_expiracao_token(banca),
        )
    try:
        with transaction.atomic():
            membro.save()
    except IntegrityError as exc:
        raise ErroNegocio(
            "Membro já faz parte da banca.", codigo="membro_duplicado", detalhes={"email": membro.email}
        ) from exc
    _evento_convite(banca, membro, token, ref)
    if token:
        registrar_auditoria(
            "token_externo_gerado",
            "membro_banca",
            membro.id,
            request=request,
            usuario=usuario,
            detalhes={"banca_id": str(banca.id), "expira_em": membro.token_expira_em.isoformat()},
        )
    return membro


# --- etapa 1: criação ---------------------------------------------------------------------


def _normalizar_local_link(dados: dict) -> tuple[str | None, str | None]:
    local = (dados.get("local") or "").strip() or None
    link = (dados.get("link") or "").strip() or None
    if bool(local) == bool(link):
        raise ErroNegocio(
            "Informe exatamente um entre 'local' (presencial) e 'link' (remota).",
            codigo="local_ou_link",
            status_code=400,
        )
    return local, link


def pode_gerir_banca(usuario, ref: MonografiaRef) -> bool:
    if usuario.papel in ("admin", "coordenador"):
        return True
    return bool(usuario.professor_id) and str(ref.orientador_id) == str(usuario.professor_id)


@transaction.atomic
def criar_banca(dados: dict, usuario, request=None) -> Banca:
    ref = obter_monografia(dados["monografia_id"])
    if not pode_gerir_banca(usuario, ref):
        raise ErroNegocio(
            "Somente coordenador ou orientador da monografia agendam a banca.", codigo="acesso_negado", status_code=403
        )
    exigir_aprovacao_orientador(ref)
    if Banca.objects.filter(monografia_id=ref.id).exclude(status=Banca.Status.CANCELADA).exists():
        raise ErroNegocio("Já existe uma banca ativa para esta monografia.", codigo="banca_ja_existe")
    local, link = _normalizar_local_link(dados)
    membros = list(dados.get("membros") or [])
    if ref.orientador_id and not any(str(m.get("professor_id")) == str(ref.orientador_id) for m in membros):
        membros.insert(0, {"tipo": "interno", "professor_id": ref.orientador_id, "funcao": "orientador"})
    if len(membros) < settings.BANCA_MIN_MEMBROS:
        raise ErroNegocio(
            f"A banca precisa de no mínimo {settings.BANCA_MIN_MEMBROS} membros (orientador + 2).",
            codigo="membros_insuficientes",
            status_code=400,
        )
    banca = Banca.objects.create(
        monografia_id=ref.id,
        data_hora_inicio=dados["data_hora_inicio"],
        duracao_minutos=dados.get("duracao_minutos") or settings.BANCA_DURACAO_PADRAO_MIN,
        local=local,
        link=link,
        criada_por_id=usuario.id,
    )
    for m in membros:
        if str(m.get("professor_id")) == str(ref.orientador_id):
            m = {**m, "funcao": "orientador"}
        adicionar_membro(banca, m, ref, usuario, request)
    registrar_auditoria("banca_criada", "banca", banca.id, request=request, usuario=usuario)
    return banca


# --- confirmação ------------------------------------------------------------------------


@transaction.atomic
def responder_convite(membro: MembroBanca, resposta: str, usuario=None, request=None) -> MembroBanca:
    if membro.banca.status not in (Banca.Status.EM_ORGANIZACAO, Banca.Status.AGENDADA):
        raise ErroNegocio("Banca não aceita mais confirmações.", codigo="banca_fechada")
    if resposta not in (MembroBanca.Confirmacao.CONFIRMADO, MembroBanca.Confirmacao.RECUSADO):
        raise ErroNegocio("Resposta inválida.", codigo="resposta_invalida", status_code=400)
    membro.confirmacao = resposta
    membro.confirmado_em = timezone.now()
    membro.save()
    registrar_auditoria(
        f"convite_{resposta}",
        "membro_banca",
        membro.id,
        request=request,
        usuario=usuario,
        detalhes={"banca_id": str(membro.banca_id), "tipo": membro.tipo},
    )
    return membro


# --- etapa 2: agendamento ------------------------------------------------------------------


def _chaves_lock(membros) -> list[str]:
    chaves = {f"email:{m.email.lower()}" for m in membros}
    chaves |= {f"prof:{m.professor_id}" for m in membros if m.professor_id}
    return sorted(chaves)


def conflitos_de_horario(banca: Banca, membros) -> list[dict]:
    """Outras bancas AGENDADAS com intervalo sobreposto que compartilham algum membro."""
    fim = banca.data_hora_fim
    profs = [m.professor_id for m in membros if m.professor_id]
    emails = [m.email.lower() for m in membros]
    outras = (
        Banca.objects.filter(status=Banca.Status.AGENDADA)
        .exclude(pk=banca.pk)
        .annotate(
            fim=ExpressionWrapper(
                F("data_hora_inicio") + F("duracao_minutos") * Value(timedelta(minutes=1)), output_field=DateTimeField()
            )
        )
        .filter(data_hora_inicio__lt=fim, fim__gt=banca.data_hora_inicio)
    )
    conflitos = []
    for m in (
        MembroBanca.objects.filter(banca__in=outras)
        .filter(Q(professor_id__in=profs) | Q(email__in=emails))
        .select_related("banca")
    ):
        conflitos.append(
            {
                "membro": m.nome,
                "email": m.email,
                "banca_id": str(m.banca_id),
                "inicio": m.banca.data_hora_inicio.isoformat(),
                "fim": m.banca.data_hora_fim.isoformat(),
            }
        )
    return conflitos


def agendar(banca_id, usuario, request=None) -> Banca:
    with transaction.atomic():
        banca = Banca.objects.select_for_update().get(pk=banca_id)
        ref = obter_monografia(banca.monografia_id)
        if not pode_gerir_banca(usuario, ref):
            raise ErroNegocio("Sem permissão para agendar esta banca.", codigo="acesso_negado", status_code=403)
        if banca.status != Banca.Status.EM_ORGANIZACAO:
            raise ErroNegocio(
                "Somente bancas em organização podem ser agendadas.",
                codigo="status_invalido",
                detalhes={"status": banca.status},
            )
        membros = list(banca.membros.all())
        pendentes = [
            {"membro": m.nome, "email": m.email, "confirmacao": m.confirmacao}
            for m in membros
            if m.confirmacao != MembroBanca.Confirmacao.CONFIRMADO
        ]
        if pendentes:
            raise ErroNegocio(
                "Nem todos os membros confirmaram disponibilidade.",
                codigo="confirmacoes_pendentes",
                detalhes={"membros": pendentes},
            )
        exigir_aprovacao_orientador(ref)
        # lock por membro (advisory lock transacional) => sem race condition entre agendamentos concorrentes
        with connection.cursor() as cur:
            for chave in _chaves_lock(membros):
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [chave])
        conflitos = conflitos_de_horario(banca, membros)
        if conflitos:
            raise ErroNegocio(
                "Conflito de horário com outras bancas dos mesmos membros.",
                codigo="conflito_horario",
                detalhes={"conflitos": conflitos},
            )
        banca.status = Banca.Status.AGENDADA
        banca.save()
        registrar_evento(
            "banca.agendada",
            {
                "banca_id": banca.id,
                "monografia_id": banca.monografia_id,
                "titulo": ref.titulo,
                "aluno_id": ref.aluno_id,
                "orientador_id": ref.orientador_id,
                "curso_id": ref.curso_id,
                "data_hora": banca.data_hora_inicio,
                "duracao_minutos": banca.duracao_minutos,
                "local": banca.local,
                "link": banca.link,
                "membros": [
                    {
                        "id": m.id,
                        "nome": m.nome,
                        "email": m.email,
                        "tipo": m.tipo,
                        "funcao": m.funcao,
                        "professor_id": m.professor_id,
                    }
                    for m in membros
                ],
            },
        )
        registrar_auditoria("banca_agendada", "banca", banca.id, request=request, usuario=usuario)
        return banca


# --- edição / cancelamento / realização ------------------------------------------------------


@transaction.atomic
def editar_banca(banca: Banca, dados: dict, usuario, request=None) -> Banca:
    if banca.status in (Banca.Status.REALIZADA, Banca.Status.CANCELADA):
        raise ErroNegocio("Banca realizada ou cancelada não pode ser editada.", codigo="banca_nao_editavel")
    mudou_horario = False
    for campo in ("data_hora_inicio", "duracao_minutos"):
        if campo in dados and dados[campo] != getattr(banca, campo):
            setattr(banca, campo, dados[campo])
            mudou_horario = True
    if "local" in dados or "link" in dados:
        banca.local, banca.link = _normalizar_local_link(
            {"local": dados.get("local", banca.local), "link": dados.get("link", banca.link)}
        )
    if mudou_horario:
        # novo horário exige nova confirmação de todos (e volta para organização)
        banca.status = Banca.Status.EM_ORGANIZACAO
        for m in banca.membros.all():
            m.confirmacao = MembroBanca.Confirmacao.PENDENTE
            m.confirmado_em = None
            if m.tipo == MembroBanca.Tipo.EXTERNO:
                m.token_expira_em = _expiracao_token(banca)
            m.save()
    banca.save()
    registrar_auditoria(
        "banca_editada",
        "banca",
        banca.id,
        request=request,
        usuario=usuario,
        detalhes={"campos": sorted(dados), "reconfirmacao": mudou_horario},
    )
    return banca


def _revogar_tokens(banca: Banca, usuario=None, request=None, motivo: str = "") -> int:
    n = banca.membros.filter(tipo="externo", token_revogado=False).update(token_revogado=True)
    if n:
        registrar_auditoria(
            "token_externo_revogado",
            "banca",
            banca.id,
            request=request,
            usuario=usuario,
            detalhes={"quantidade": n, "motivo": motivo},
        )
    return n


@transaction.atomic
def cancelar(banca: Banca, motivo: str, usuario, request=None) -> Banca:
    if banca.status in (Banca.Status.REALIZADA, Banca.Status.CANCELADA):
        raise ErroNegocio("Banca já realizada ou cancelada.", codigo="banca_nao_editavel")
    ref = MonografiaRef.objects.filter(pk=banca.monografia_id).first()
    banca.status = Banca.Status.CANCELADA
    banca.motivo_cancelamento = motivo
    banca.save()
    _revogar_tokens(banca, usuario, request, "cancelamento")
    registrar_evento(
        "banca.cancelada",
        {
            "banca_id": banca.id,
            "monografia_id": banca.monografia_id,
            "aluno_id": ref.aluno_id if ref else None,
            "titulo": ref.titulo if ref else "",
            "motivo": motivo,
            "data_hora": banca.data_hora_inicio,
            "membros": [{"nome": m.nome, "email": m.email, "tipo": m.tipo} for m in banca.membros.all()],
        },
    )
    registrar_auditoria(
        "banca_cancelada", "banca", banca.id, request=request, usuario=usuario, detalhes={"motivo": motivo}
    )
    return banca


@transaction.atomic
def marcar_realizada(banca: Banca, usuario, request=None) -> Banca:
    if banca.status != Banca.Status.AGENDADA:
        raise ErroNegocio("Somente bancas agendadas podem ser marcadas como realizadas.", codigo="status_invalido")
    banca.status = Banca.Status.REALIZADA
    banca.save()
    registrar_auditoria("banca_realizada", "banca", banca.id, request=request, usuario=usuario)
    return banca


# --- avaliações e resultado ------------------------------------------------------------------


def _exigir_aberta_para_avaliacao(banca: Banca) -> None:
    if banca.status != Banca.Status.REALIZADA:
        raise ErroNegocio("Avaliações só são aceitas após a realização da banca.", codigo="banca_nao_realizada")
    if banca.resultado_calculado_em is not None:
        raise ErroNegocio("O resultado já foi fechado.", codigo="resultado_fechado")


def registrar_avaliacao(banca: Banca, membro: MembroBanca, dados: dict, usuario=None, request=None) -> Avaliacao:
    with transaction.atomic():
        banca = Banca.objects.select_for_update().get(pk=banca.pk)
        _exigir_aberta_para_avaliacao(banca)
        if membro.banca_id != banca.id or membro.confirmacao != MembroBanca.Confirmacao.CONFIRMADO:
            raise ErroNegocio("Apenas membros confirmados avaliam.", codigo="nao_e_membro", status_code=403)
        if Avaliacao.objects.filter(banca=banca, membro=membro).exists():
            raise ErroNegocio("Você já registrou sua avaliação.", codigo="avaliacao_duplicada")
        av = Avaliacao(banca=banca, membro=membro, **dados)
        av.full_clean()
        av.save()
        registrar_evento(
            "avaliacao.registrada",
            {"banca_id": banca.id, "avaliacao_id": av.id, "membro_id": membro.id, "monografia_id": banca.monografia_id},
        )
        registrar_auditoria(
            "avaliacao_registrada",
            "banca",
            banca.id,
            request=request,
            usuario=usuario,
            detalhes={"membro_id": str(membro.id), "tipo": membro.tipo},
        )
    return av


def editar_avaliacao(av: Avaliacao, dados: dict, usuario=None, request=None) -> Avaliacao:
    with transaction.atomic():
        banca = Banca.objects.select_for_update().get(pk=av.banca_id)
        if banca.resultado_calculado_em is not None:
            raise ErroNegocio(
                "O resultado já foi fechado; a avaliação não pode mais ser editada.", codigo="resultado_fechado"
            )
        for campo in ("nota", "parecer", "recomendacao"):
            if campo in dados:
                setattr(av, campo, dados[campo])
        av.full_clean()
        av.save()
        registrar_auditoria(
            "avaliacao_editada",
            "banca",
            banca.id,
            request=request,
            usuario=usuario,
            detalhes={"avaliacao_id": str(av.id), "campos": sorted(dados)},
        )
    return av


def calcular_resultado(banca_id) -> Banca | None:
    """Fecha o resultado somente quando TODOS os membros ativos avaliaram (idempotente)."""
    banca = Banca.objects.select_for_update().filter(pk=banca_id).first()
    if banca is None or banca.resultado_calculado_em is not None:
        return banca
    membros = banca.membros.filter(confirmacao=MembroBanca.Confirmacao.CONFIRMADO)
    avaliacoes = list(Avaliacao.objects.filter(banca=banca, membro__in=membros))
    if not avaliacoes or len(avaliacoes) < membros.count():
        return None
    notas = [a.nota for a in avaliacoes]
    media = (sum(notas) / Decimal(len(notas))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    reprovados = sum(1 for a in avaliacoes if a.recomendacao == Avaliacao.Recomendacao.REPROVADO)
    if media < Decimal(str(settings.NOTA_MINIMA)) or reprovados > len(avaliacoes) / 2:
        resultado, exige = "reprovada", False
    else:
        resultado = "aprovada"
        exige = any(a.recomendacao == Avaliacao.Recomendacao.COM_RESSALVAS for a in avaliacoes)
    banca.resultado_final = resultado
    banca.media_final = media
    banca.exige_correcao = exige
    banca.resultado_calculado_em = timezone.now()
    banca.status = Banca.Status.REALIZADA
    banca.save()
    _revogar_tokens(banca, motivo="resultado_fechado")
    ref = MonografiaRef.objects.filter(pk=banca.monografia_id).first()
    registrar_evento(
        "banca.resultado_calculado",
        {
            "banca_id": banca.id,
            "monografia_id": banca.monografia_id,
            "aluno_id": ref.aluno_id if ref else None,
            "orientador_id": ref.orientador_id if ref else None,
            "curso_id": ref.curso_id if ref else None,
            "titulo": ref.titulo if ref else "",
            "resultado": resultado,
            "media": str(media),
            "exige_correcao": exige,
            "data_defesa": banca.data_hora_inicio,
        },
    )
    return banca
