"""Table jeton -> valeur : cache mémoire local + Redis (partagé, avec TTL)."""
from __future__ import annotations

import logging
from typing import Optional

from .pii import MemoryStore

log = logging.getLogger("governance.store")


class RedisStore:
    PREFIX = "gov:map:"

    def __init__(self, url: str, ttl_seconds: int):
        import redis  # import tardif : le moteur reste utilisable sans Redis

        self._r = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
        self._local = MemoryStore()
        self._ttl = ttl_seconds

    def put(self, token: str, value: str) -> None:
        if token in self._local:
            return  # déjà connu : on évite un aller-retour Redis par jeton et par requête
        self._local.put(token, value)
        try:
            self._r.set(self.PREFIX + token, value, ex=self._ttl)
        except Exception as e:  # Redis indisponible : le cache local suffit pour la session
            log.warning("redis set failed: %s", e)

    def get(self, token: str) -> Optional[str]:
        v = self._local.get(token)
        if v is not None:
            return v
        try:
            v = self._r.get(self.PREFIX + token)
        except Exception as e:
            log.warning("redis get failed: %s", e)
            return None
        if v is not None:
            self._local.put(token, v)
        return v

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


def build_store(redis_url: Optional[str], ttl_seconds: int):
    if redis_url:
        return RedisStore(redis_url, ttl_seconds)
    log.warning("REDIS_URL absent : table de correspondance en mémoire uniquement")
    return MemoryStore()
