from rest_framework.pagination import LimitOffsetPagination


class Paginacao(LimitOffsetPagination):
    """Paginação padrão: 20 itens, máximo 50."""

    default_limit = 20
    max_limit = 50
