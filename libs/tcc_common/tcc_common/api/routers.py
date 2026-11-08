from rest_framework.routers import SimpleRouter


class RouterBarraOpcional(SimpleRouter):
    """Aceita a URL com e sem barra final (``POST /api/monografias`` e ``/api/monografias/``)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trailing_slash = "/?"
