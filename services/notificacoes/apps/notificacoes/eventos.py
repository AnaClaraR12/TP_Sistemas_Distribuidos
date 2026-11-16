"""Consumers: evento -> destinatários certos -> e-mail (MailHog em dev) + alerta in-app."""

from django.conf import settings

from apps.notificacoes.envio import Destinatario, notificar
from apps.notificacoes.models import AlunoRef, CursoRef, ProfessorRef


def _aluno(aid) -> list[Destinatario]:
    a = AlunoRef.objects.filter(pk=aid).first() if aid else None
    return [Destinatario(a.email, a.nome, str(a.id))] if a else []


def _prof(pid) -> list[Destinatario]:
    p = ProfessorRef.objects.filter(pk=pid).first() if pid else None
    return [Destinatario(p.email, p.nome, str(p.id))] if p else []


def _coordenador(curso_id) -> list[Destinatario]:
    c = CursoRef.objects.filter(pk=curso_id).first() if curso_id else None
    return _prof(c.coordenador_id) if c else []


def _ctx_mono(d: dict) -> dict:
    return {"titulo": d.get("titulo", ""), "monografia_id": d.get("id") or d.get("monografia_id")}


def on_submetida(env):
    d = env["data"]
    notificar(env, "submissao_orientador", _prof(d["orientador_id"]), _ctx_mono(d))


def on_texto_extraido(env):
    d = env["data"]
    notificar(
        env,
        "texto_extraido",
        _prof(d.get("orientador_id")) + _aluno(d.get("aluno_id")),
        {**_ctx_mono(d), "paginas": d["paginas"], "sem_texto": d["sem_texto"]},
    )


def on_extracao_falhou(env):
    d = env["data"]
    notificar(
        env,
        "extracao_falhou",
        _aluno(d.get("aluno_id")) + _prof(d.get("orientador_id")),
        {**_ctx_mono(d), "motivo": d["motivo"]},
    )


def on_aprovada_orientador(env):
    d = env["data"]
    notificar(env, "aprovada_orientador", _aluno(d["aluno_id"]) + _coordenador(d["curso_id"]), _ctx_mono(d))


def on_rejeitada_orientador(env):
    d = env["data"]
    notificar(env, "rejeitada_orientador", _aluno(d["aluno_id"]), {**_ctx_mono(d), "motivo": d["motivo"]})


def on_convite(env):
    d = env["data"]
    m = d["membro"]
    token = d.get("token")
    frontend = settings.FRONTEND_URL.rstrip("/")
    url = (
        f"{frontend}/banca/externo/{token}"
        if m["tipo"] == "externo" and token
        else f"{frontend}/bancas/{d['banca_id']}"
    )
    notificar(
        env,
        "convite_banca",
        [Destinatario(m["email"], m["nome"], m.get("id"))],
        {
            "titulo": d.get("titulo", ""),
            "data_hora": d.get("data_hora"),
            "local": d.get("local"),
            "link": d.get("link"),
            "url_convite": url,
            "expira_em": d.get("expira_em"),
        },
        segredos=(token,) if token else (),
    )


def on_agendada(env):
    d = env["data"]
    membros = [Destinatario(m["email"], m["nome"]) for m in d["membros"]]
    notificar(
        env,
        "banca_agendada",
        membros + _aluno(d["aluno_id"]),
        {
            "titulo": d.get("titulo", ""),
            "data_hora": d["data_hora"],
            "duracao": d.get("duracao_minutos", 120),
            "local": d["local"],
            "link": d["link"],
            "membros": d["membros"],
        },
    )


def on_cancelada(env):
    d = env["data"]
    membros = [Destinatario(m["email"], m["nome"]) for m in d["membros"]]
    notificar(
        env, "banca_cancelada", membros + _aluno(d["aluno_id"]), {"titulo": d.get("titulo", ""), "motivo": d["motivo"]}
    )


def on_resultado(env):
    d = env["data"]
    dest = _aluno(d["aluno_id"]) + _prof(d["orientador_id"]) + _coordenador(d.get("curso_id"))
    notificar(
        env,
        "resultado_banca",
        dest,
        {
            "titulo": d.get("titulo", ""),
            "resultado": d["resultado"],
            "media": d["media"],
            "exige_correcao": d["exige_correcao"],
        },
    )


def on_publicada(env):
    d = env["data"]
    dest = _aluno(d["aluno_id"]) or (
        [Destinatario(d["autor_email"], d.get("autor_nome", ""))] if d.get("autor_email") else []
    )
    notificar(env, "publicada", dest, _ctx_mono(d))


def on_integridade(env):
    d = env["data"]
    admins = [Destinatario(e, "Administrador") for e in settings.NOTIFICACOES_ADMIN_EMAILS]
    notificar(
        env,
        "integridade_violada",
        admins + _coordenador(d.get("curso_id")),
        {**_ctx_mono(d), "sha_esperado": d["sha_esperado"], "sha_atual": d["sha_atual"]},
    )


def on_cadastro(env):
    _, entidade, acao = env["type"].split(".")
    d = env["data"]
    modelo = {"aluno": AlunoRef, "professor": ProfessorRef, "curso": CursoRef}.get(entidade)
    if modelo is None:
        return
    if acao == "deleted":
        modelo.objects.filter(pk=d["id"]).delete()
    elif entidade == "aluno":
        AlunoRef.objects.update_or_create(
            pk=d["id"], defaults={"nome": d["nome"], "email": d["email"], "curso_id": d.get("curso_id")}
        )
    elif entidade == "professor":
        ProfessorRef.objects.update_or_create(pk=d["id"], defaults={"nome": d["nome"], "email": d["email"]})
    else:
        CursoRef.objects.update_or_create(
            pk=d["id"], defaults={"nome": d["nome"], "coordenador_id": d.get("coordenador_id")}
        )


HANDLERS = {
    "monografia.submetida": on_submetida,
    "monografia.texto_extraido": on_texto_extraido,
    "monografia.extracao_falhou": on_extracao_falhou,
    "monografia.aprovada_orientador": on_aprovada_orientador,
    "monografia.rejeitada_orientador": on_rejeitada_orientador,
    "monografia.publicada": on_publicada,
    "monografia.integridade_violada": on_integridade,
    "banca.convite_enviado": on_convite,
    "banca.agendada": on_agendada,
    "banca.cancelada": on_cancelada,
    "banca.resultado_calculado": on_resultado,
    "cadastro.#": on_cadastro,
}
