import time
from collections import OrderedDict
from typing import Any, Optional


class TTLCache:
    def __init__(self, ttl_seconds: int, max_entries: int):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        self._items[key] = (time.monotonic() + self.ttl_seconds, value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)
