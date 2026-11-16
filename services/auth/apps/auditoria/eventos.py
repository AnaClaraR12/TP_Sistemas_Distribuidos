"""Consumer do auth-service: centraliza ``audit.registro`` e alertas de integridade."""

from apps.auditoria.servicos import gravar_registro


def on_audit_registro(envelope: dict) -> None:
    dados = dict(envelope["data"])
    dados.setdefault("servico_origem", envelope.get("producer"))
    gravar_registro(dados)


def on_integridade_violada(envelope: dict) -> None:
    d = envelope["data"]
    gravar_registro(
        {
            "usuario_id": envelope.get("actor_id"),
            "acao": "integridade_violada",
            "recurso": "monografia",
            "recurso_id": d["id"],
            "servico_origem": envelope.get("producer"),
            "nivel": "critico",
            "detalhes": {"sha_esperado": d["sha_esperado"], "sha_atual": d["sha_atual"]},
        }
    )


HANDLERS = {
    "audit.registro": on_audit_registro,
    "monografia.integridade_violada": on_integridade_violada,
}
