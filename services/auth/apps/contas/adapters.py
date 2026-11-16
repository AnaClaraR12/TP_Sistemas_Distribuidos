"""Contas são criadas pela coordenação: o cadastro público do allauth fica desligado."""

from allauth.account.adapter import DefaultAccountAdapter


class ContaAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        return False
