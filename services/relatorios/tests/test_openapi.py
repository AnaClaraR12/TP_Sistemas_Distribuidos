"""O schema OpenAPI (Swagger) do serviço é gerado sem erros nem avisos."""

from django.core.management import call_command


def test_schema_openapi_sem_avisos(tmp_path, db):
    destino = tmp_path / "schema.json"
    call_command("spectacular", "--fail-on-warn", "--format", "openapi-json", "--file", str(destino))
    assert destino.stat().st_size > 1000
