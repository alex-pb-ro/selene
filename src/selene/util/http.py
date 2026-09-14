from typing import Any
from urllib.request import HTTPRedirectHandler, OpenerDirector, ProxyHandler, build_opener

import requests


class DirectHttpSession(requests.Session):
    """HTTP session that keeps project requests off environment proxies and rejects redirects."""

    def __init__(self) -> None:
        super().__init__()
        self.trust_env = False

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        kwargs["allow_redirects"] = False
        response = super().send(request, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise requests.HTTPError("Refusing to redirect a project request to another endpoint", response=response)
        return response


class DirectUrlOpener:
    """Factory for local dashboard requests without proxies or redirects."""

    class _RejectRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    @classmethod
    def create(cls) -> OpenerDirector:
        return build_opener(ProxyHandler({}), cls._RejectRedirects())
