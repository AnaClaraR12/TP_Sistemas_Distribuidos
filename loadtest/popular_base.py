"""Popula o banco do repositorio-service com N monografias publicadas sintéticas (para o teste de carga).

Uso (dentro de services/repositorio, com DJANGO_SETTINGS_MODULE e DATABASE_URL definidos):
    python ../../loadtest/popular_base.py 3000
No Docker:  docker compose exec repositorio-service python /app/popular_base.py 3000  (copie o arquivo)
"""

from __future__ import annotations

import hashlib
import os
import random
import sys
import uuid
from pathlib import Path

import django

sys.path.insert(0, os.getcwd())
django.setup()

from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402

from apps.indexacao.models import CursoRef, DocumentoIndexado, ProfessorRef  # noqa: E402

VOCAB = (
    "sistemas distribuidos redis cache microsservicos rabbitmq filas postgresql busca textual seguranca jwt docker "
    "kubernetes nuvem elasticidade iot agricultura blockchain aprendizado maquina classificacao redes neurais "
    "acessibilidade escalabilidade desempenho banco dados indices api rest devops integridade replicacao "
    "consistencia tolerancia falhas algoritmos grafos compiladores engenharia software testes qualidade usabilidade "
    "visao computacional processamento linguagem natural criptografia sensores mobile web arquitetura modelo "
    "avaliacao experimento resultado proposta metodologia estudo caso analise dados"
).split()


def texto(n: int) -> str:
    return " ".join(random.choices(VOCAB, k=n))


def main(total: int) -> None:
    random.seed(7)
    if DocumentoIndexado.objects.filter(publico=True).count() >= total:
        print("base já populada")
        return
    cursos = [
        CursoRef.objects.get_or_create(id=uuid.uuid4(), defaults={"nome": f"Curso {c}", "codigo": c})[0]
        for c in ("SI", "CC", "ENG", "MAT")
    ]
    profs = [
        ProfessorRef.objects.get_or_create(
            id=uuid.uuid4(), defaults={"nome": f"Professor {i}", "departamento": "DECOM"}
        )[0]
        for i in range(20)
    ]
    pasta = Path(settings.MEDIA_ROOT) / "publicados"
    pasta.mkdir(parents=True, exist_ok=True)
    pdf = b"%PDF-1.4\n" + texto(2000).encode() + b"\n%%EOF\n"
    arquivo = pasta / "carga.pdf"
    arquivo.write_bytes(pdf)
    sha = hashlib.sha256(pdf).hexdigest()
    lote = []
    for i in range(total):
        c, p = random.choice(cursos), random.choice(profs)
        titulo = f"{texto(6).capitalize()} {i}"
        palavras = random.sample(VOCAB, 3)
        lote.append(
            DocumentoIndexado(
                monografia_id=uuid.uuid4(),
                titulo=titulo,
                titulo_norm=titulo.lower(),
                resumo=texto(120),
                palavras_chave=palavras,
                palavras_chave_norm=palavras,
                autor_nome=f"Autor {i}",
                autor_norm=f"autor {i}",
                orientador_id=p.id,
                orientador_nome=p.nome,
                orientador_norm=p.nome.lower(),
                curso_id=c.id,
                curso_nome=c.nome,
                ano_defesa=random.randint(2018, 2026),
                texto_completo=texto(3000),
                paginas=random.randint(30, 120),
                publico=True,
                arquivo_sha256=sha,
                arquivo_local=str(arquivo),
            )
        )
    DocumentoIndexado.objects.bulk_create(lote, batch_size=500)
    with connection.cursor() as cur:  # textos sintéticos são ASCII: normalização == identidade
        cur.execute("""
            UPDATE indexacao_documentoindexado SET publicado_em = now() - (random() * interval '700 days'),
              search_vector = setweight(to_tsvector('portuguese', titulo_norm), 'A')
                || setweight(to_tsvector('portuguese', array_to_string(palavras_chave_norm, ' ')), 'B')
                || setweight(to_tsvector('portuguese', resumo), 'B')
                || setweight(to_tsvector('portuguese', left(texto_completo, 300000)), 'C')
        """)
        cur.execute("ANALYZE indexacao_documentoindexado")
    print(f"{total} documentos publicados criados")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3000)
