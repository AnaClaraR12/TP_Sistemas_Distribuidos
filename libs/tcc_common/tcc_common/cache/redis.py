"""Cliente Redis, rate limit por janela fixa e travas com SET NX."""

import threading

import redis
from django.conf import settings

_cliente: redis.Redis | None = None
_lock = threading.Lock()


def get_redis() -> redis.Redis:
    """Cliente único por processo. ``REDIS_URL=fakeredis://`` usa um Redis em memória (testes)."""
    global _cliente
    if _cliente is None:
        with _lock:
            if _cliente is None:
                url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
                if url.startswith("fakeredis://"):
                    import fakeredis

                    _cliente = fakeredis.FakeRedis(decode_responses=True)
                else:
                    _cliente = redis.Redis.from_url(
                        url, decode_responses=True, socket_timeout=5, health_check_interval=30
                    )
    return _cliente


def reset_redis() -> None:
    """Descarta o singleton (usado nos testes)."""
    global _cliente
    _cliente = None


def verificar_rate_limit(chave: str, limite: int, janela_s: int) -> tuple[bool, int]:
    """Contador de janela fixa (``INCR`` + ``EXPIRE``).

    Retorna ``(permitido, retry_after_segundos)``.
    """
    r = get_redis()
    pipe = r.pipeline()
    pipe.incr(chave)
    pipe.expire(chave, janela_s, nx=True)
    pipe.ttl(chave)
    total, _, ttl = pipe.execute()
    if int(total) > limite:
        return False, max(int(ttl), 1)
    return True, 0


def adquirir_lock(chave: str, valor: str, ttl_s: int) -> bool:
    """``SET chave valor NX EX ttl`` — True se o lock foi obtido."""
    return bool(get_redis().set(chave, valor, nx=True, ex=ttl_s))


def liberar_lock(chave: str, valor: str | None = None) -> None:
    """Remove o lock. Se ``valor`` for informado, só remove se ainda for o dono."""
    r = get_redis()
    if valor is None:
        r.delete(chave)
        return
    script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
    try:
        r.eval(script, 1, chave, valor)
    except redis.ResponseError:  # pragma: no cover - fakeredis sem lua
        if r.get(chave) == valor:
            r.delete(chave)
