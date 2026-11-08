"""Adapter do allauth: cadastro público desabilitado (P2)."""

from allauth.account.adapter import DefaultAccountAdapter


class ContaAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request) -> bool:
        return False
