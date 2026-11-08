import django_filters
from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db.models import Q

from apps.monografias.models import Monografia
from tcc_common.texto import normalizar


class MonografiaFiltro(django_filters.FilterSet):
    """``?busca=``, ``?aluno=``, ``?orientador=``, ``?curso=``, ``?ano_defesa=``, ``?palavras_chave=``, ``?status=``."""

    busca = django_filters.CharFilter(method="filtrar_busca")
    aluno = django_filters.UUIDFilter(field_name="aluno_id")
    orientador = django_filters.UUIDFilter(field_name="orientador_id")
    curso = django_filters.UUIDFilter(field_name="curso_id")
    ano_defesa = django_filters.NumberFilter(field_name="defendida_em", lookup_expr="year")
    palavras_chave = django_filters.CharFilter(method="filtrar_palavras")
    status = django_filters.CharFilter(field_name="status")
    aprovacao_orientador = django_filters.CharFilter(field_name="aprovacao_orientador")

    class Meta:
        model = Monografia
        fields: list[str] = []

    def filtrar_busca(self, qs, name, value):
        """FTS (config portuguese) sobre o texto normalizado + fallback por substring."""
        termo = normalizar(value)
        if not termo:
            return qs
        consulta = SearchQuery(termo, search_type="websearch", config="portuguese")
        return qs.annotate(_busca=SearchVector("busca_normalizada", config="portuguese")).filter(
            Q(_busca=consulta) | Q(busca_normalizada__contains=termo)
        )

    def filtrar_palavras(self, qs, name, value):
        termos = [t.strip() for t in (value or "").split(",") if t.strip()]
        return qs.filter(palavras_chave__overlap=termos) if termos else qs
