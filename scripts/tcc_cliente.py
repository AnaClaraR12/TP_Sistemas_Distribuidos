"""Cliente HTTP do sistema (via gateway) usado pelo seed de demonstração e pelo teste E2E.

Sem dependências além de ``requests``. Inclui um gerador de PDF mínimo (com texto
extraível) e um leitor da API do MailHog (para obter os links de convite externo).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

import requests


def pdf_simples(linhas: list[str]) -> bytes:
    """Gera um PDF 1.4 válido de 1 página com as linhas de texto (Helvetica)."""

    def esc(t: str) -> str:
        t = t.encode("latin-1", "replace").decode("latin-1")
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    conteudo = "BT /F1 12 Tf 50 800 Td 16 TL " + " ".join(f"({esc(linha)}) '" for linha in linhas) + " ET"
    stream = conteudo.encode("latin-1")
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    saida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    saida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(saida)


class ErroApi(RuntimeError):
    def __init__(self, resp: requests.Response):
        self.status = resp.status_code
        try:
            self.corpo = resp.json()
        except ValueError:
            self.corpo = {"texto": resp.text[:300]}
        super().__init__(f"{resp.request.method} {resp.url} -> {resp.status_code}: {self.corpo}")


@dataclass
class Sessao:
    gateway: str
    token: str | None = None
    perfil: dict = field(default_factory=dict)

    def _h(self, extra=None):
        h = {"X-Request-ID": uuid.uuid4().hex}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return {**h, **(extra or {})}

    def req(self, metodo: str, caminho: str, esperado: tuple[int, ...] | None = (200, 201, 202, 204), **kw):
        resp = requests.request(
            metodo, self.gateway.rstrip("/") + caminho, headers=self._h(kw.pop("headers", None)), timeout=60, **kw
        )
        if esperado and resp.status_code not in esperado:
            raise ErroApi(resp)
        return resp

    def get(self, c, **kw):
        return self.req("GET", c, **kw)

    def post(self, c, **kw):
        return self.req("POST", c, **kw)

    def patch(self, c, **kw):
        return self.req("PATCH", c, **kw)

    def delete(self, c, **kw):
        return self.req("DELETE", c, **kw)

    @classmethod
    def login(cls, gateway: str, email: str, senha: str) -> Sessao:
        s = cls(gateway)
        r = s.post("/api/auth/token/", json={"email": email, "password": senha}, esperado=(200,))
        s.token = r.json()["access"]
        s.perfil = s.get("/api/auth/me/").json()
        return s

    # atalhos de domínio
    def upload(self, mid: str, conteudo: bytes, nome="tcc.pdf", esperado=(200, 201)):
        return self.post(
            f"/api/monografias/{mid}/arquivo/",
            files={"arquivo": (nome, conteudo, "application/pdf")},
            esperado=esperado,
        )

    def documento(self, mid: str, tipo: str, conteudo: bytes):
        return self.post(
            f"/api/monografias/{mid}/documentos/",
            data={"tipo": tipo},
            files={"arquivo": (f"{tipo}.pdf", conteudo, "application/pdf")},
        ).json()


def aguardar(condicao, timeout: float = 60, intervalo: float = 1.0, descricao: str = "condição"):
    """Espera uma condição eventual (o sistema é assíncrono: eventos levam alguns segundos)."""
    fim = time.time() + timeout
    ultimo = None
    while time.time() < fim:
        try:
            ultimo = condicao()
            if ultimo:
                return ultimo
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
        time.sleep(intervalo)
    raise TimeoutError(f"Tempo esgotado aguardando {descricao} (último: {ultimo!r})")


class MailHog:
    def __init__(self, url: str = "http://localhost:8025"):
        self.url = url.rstrip("/")

    def mensagens(self, para: str | None = None) -> list[dict]:
        """Mensagens mais recentes primeiro; com ``para``, usa a busca do MailHog (filtra no servidor)."""
        if para:
            r = requests.get(
                f"{self.url}/api/v2/search", params={"kind": "to", "query": para, "limit": 250}, timeout=10
            )
        else:
            r = requests.get(f"{self.url}/api/v2/messages", params={"limit": 250}, timeout=10)
        r.raise_for_status()
        itens = r.json().get("items", [])
        if para:  # a busca é por substring: confirma o destinatário exato
            itens = [
                m
                for m in itens
                if any(
                    para.lower() == (t.get("Mailbox", "") + "@" + t.get("Domain", "")).lower() for t in m.get("To", [])
                )
            ]
        return itens

    @staticmethod
    def corpo(msg: dict) -> str:
        import quopri

        bruto = msg.get("Content", {}).get("Body", "")
        try:
            return quopri.decodestring(bruto.encode()).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return bruto

    def token_convite(self, email: str) -> str | None:
        for m in self.mensagens(email):
            achado = re.search(r"/banca/externo/([A-Za-z0-9_\-]{20,})", self.corpo(m))
            if achado:
                return achado.group(1)
        return None
