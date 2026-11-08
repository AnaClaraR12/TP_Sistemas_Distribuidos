"""Máquina de estados da Monografia (Anexo B).

Transições só acontecem pelos métodos de domínio do model (``submeter()``,
``aprovar_orientador()``, ``rejeitar_orientador()``, ``registrar_resultado_banca()``,
``publicar()``). Uma transição fora deste grafo levanta ``TransicaoInvalida`` (HTTP 409).
"""

from __future__ import annotations

from django.db import models

from tcc_common.api.exceptions import ErroNegocio


class Status(models.TextChoices):
    RASCUNHO = "rascunho", "Rascunho"
    EM_AVALIACAO = "em_avaliacao", "Em avaliação"
    APROVADA = "aprovada", "Aprovada"
    REPROVADA = "reprovada", "Reprovada"
    PUBLICADA = "publicada", "Publicada"


class AprovacaoOrientador(models.TextChoices):
    PENDENTE = "pendente", "Pendente"
    APROVADA = "aprovada", "Aprovada"
    REJEITADA = "rejeitada", "Rejeitada"


TRANSICOES: dict[str, set[str]] = {
    Status.RASCUNHO: {Status.EM_AVALIACAO},
    Status.EM_AVALIACAO: {Status.RASCUNHO, Status.APROVADA, Status.REPROVADA},
    Status.APROVADA: {Status.PUBLICADA},
    Status.REPROVADA: set(),  # terminal
    Status.PUBLICADA: set(),  # terminal, imutável
}

TERMINAIS = {Status.REPROVADA, Status.PUBLICADA}


class TransicaoInvalida(ErroNegocio):
    default_code = "transicao_invalida"
    default_detail = "Transição de status inválida."


def validar_transicao(origem: str, destino: str) -> None:
    if destino not in TRANSICOES.get(origem, set()):
        raise TransicaoInvalida(
            f"Não é possível passar de '{origem}' para '{destino}'.",
            detalhes={"status_atual": origem, "status_desejado": destino},
        )
