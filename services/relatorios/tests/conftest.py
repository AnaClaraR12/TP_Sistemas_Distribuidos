import uuid
from datetime import UTC, datetime

import pytest

C1, C2 = uuid.uuid4(), uuid.uuid4()
P1, P2 = uuid.uuid4(), uuid.uuid4()


def fato(**kw):
    from apps.relatorios.models import FatoMonografia

    base = {
        "monografia_id": uuid.uuid4(),
        "curso_id": C1,
        "curso_nome": "SI",
        "orientador_id": P1,
        "orientador_nome": "Prof A",
        "aluno_id": uuid.uuid4(),
        "status": "em_avaliacao",
    }
    return FatoMonografia.objects.create(**{**base, **kw})


def dt(ano, mes, dia):
    return datetime(ano, mes, dia, 12, tzinfo=UTC)


@pytest.fixture
def dados():
    # SI / Prof A: 2 aprovadas (2025, 2026), 1 reprovada (2026), 1 em avaliação
    fato(
        status="publicada",
        resultado="aprovada",
        submetida_em=dt(2025, 3, 1),
        defendida_em=dt(2025, 3, 31),
        ano_defesa=2025,
    )
    fato(
        status="aprovada",
        resultado="aprovada",
        submetida_em=dt(2026, 1, 1),
        defendida_em=dt(2026, 1, 11),
        ano_defesa=2026,
    )
    fato(
        status="reprovada",
        resultado="reprovada",
        submetida_em=dt(2026, 2, 1),
        defendida_em=dt(2026, 2, 21),
        ano_defesa=2026,
    )
    fato()
    # ENG / Prof B: 1 aprovada
    fato(
        curso_id=C2,
        curso_nome="ENG",
        orientador_id=P2,
        orientador_nome="Prof B",
        status="aprovada",
        resultado="aprovada",
        submetida_em=dt(2026, 4, 1),
        defendida_em=dt(2026, 4, 5),
        ano_defesa=2026,
    )
