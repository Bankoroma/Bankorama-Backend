import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    """
    Limiteur en mémoire (fenêtre glissante), suffisant pour une instance unique.
    Avec plusieurs instances, passer sur Redis.
    """

    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str):
        now = time.monotonic()

        with self._lock:
            hits = self._hits[key]

            while hits and hits[0] <= now - self.window:
                hits.popleft()

            if len(hits) >= self.max_hits:
                retry_after = int(hits[0] + self.window - now) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Trop de tentatives. Réessayez plus tard.",
                    headers={"Retry-After": str(retry_after)},
                )

            hits.append(now)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


login_limiter = RateLimiter(max_hits=10, window_seconds=15 * 60)
register_limiter = RateLimiter(max_hits=5, window_seconds=60 * 60)
