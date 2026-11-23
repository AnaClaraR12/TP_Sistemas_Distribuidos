"""Roda TODOS os testes Python sem Docker: sobe um PostgreSQL 16 embutido (pgserver) e executa
o pytest de cada serviço + da biblioteca tcc_common, com cobertura.

Uso:  pip install pgserver tzdata && python3 scripts/run_tests_local.py [--sem-cobertura]
"""

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVICOS = ["auth", "monografias", "bancas", "repositorio", "notificacoes", "relatorios"]


def main() -> int:
    sys.path.insert(0, str(RAIZ / "scripts"))
    from dev_local_postgres import criar_databases, obter_uri, url_do_banco

    uri = obter_uri()
    criar_databases(uri)
    cobertura = "--sem-cobertura" not in sys.argv
    falhas = []
    alvos = [(RAIZ / "libs" / "tcc_common", url_do_banco(uri, "postgres"), "tcc_common")]
    alvos += [(RAIZ / "services" / s, url_do_banco(uri, f"{s}_db"), "apps") for s in SERVICOS]
    for pasta, db, pacote in alvos:
        print(f"\n===== {pasta.name} =====", flush=True)
        cmd = [sys.executable, "-m", "pytest", "-p", "no:warnings", "-o", "addopts=-p tcc_common.testing", "-q"]
        if cobertura:
            cmd += [f"--cov={pacote}", "--cov-report=term:skip-covered"]
        r = subprocess.run(cmd, cwd=pasta, env={**os.environ, "DATABASE_URL": db})
        if r.returncode:
            falhas.append(pasta.name)
    print("\nRESULTADO:", "todos os testes passaram" if not falhas else f"falhas em {falhas}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
