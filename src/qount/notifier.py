from __future__ import annotations

import json
from urllib.request import Request, urlopen

from .settings import Settings


class Notifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, payload: dict) -> None:
        if not self.settings.notify_webhook_url:
            return
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            self.settings.notify_webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10):
            return
