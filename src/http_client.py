from __future__ import annotations

from typing import Any
import ssl

import requests
from requests.adapters import HTTPAdapter


class SystemSSLContextAdapter(HTTPAdapter):
    def __init__(self, ssl_context: ssl.SSLContext, **kwargs: Any) -> None:
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        kwargs["ssl_context"] = self._ssl_context
        super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args: Any, **kwargs: Any) -> Any:
        kwargs["ssl_context"] = self._ssl_context
        return super().proxy_manager_for(*args, **kwargs)


def build_http_session() -> requests.Session:
    session = requests.Session()
    ssl_context = ssl.create_default_context()
    adapter = SystemSSLContextAdapter(ssl_context=ssl_context)
    session.mount("https://", adapter)
    return session
