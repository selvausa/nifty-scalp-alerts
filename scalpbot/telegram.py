"""Minimal Telegram Bot API client: send messages and long-poll for commands."""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests

log = logging.getLogger("scalpbot.telegram")


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self.chat_id = str(chat_id)
        self.offset: Optional[int] = None
        self.enabled = bool(token and chat_id)

    def send(self, html_text: str) -> bool:
        if not self.enabled:
            print(html_text + "\n")
            return True
        for attempt in range(3):
            try:
                r = requests.post(f"{self.base}/sendMessage", timeout=10, json={
                    "chat_id": self.chat_id, "text": html_text[:4000], "parse_mode": "HTML",
                    "disable_web_page_preview": True})
                if r.ok:
                    return True
                log.warning("Telegram send failed: %s %s", r.status_code, r.text[:200])
                if r.status_code == 400:   # bad markup: resend as plain text
                    requests.post(f"{self.base}/sendMessage", timeout=10,
                                  json={"chat_id": self.chat_id, "text": html_text[:4000]})
                    return True
            except requests.RequestException as e:
                log.warning("Telegram send error: %s", e)
            time.sleep(1 + attempt)
        return False

    def poll(self, timeout: float) -> list[str]:
        """Wait up to `timeout` seconds for messages from the configured chat."""
        if not self.enabled:
            time.sleep(max(timeout, 0))
            return []
        if timeout < 1:
            time.sleep(max(timeout, 0))
            return []
        try:
            params = {"timeout": int(timeout), "allowed_updates": '["message"]'}
            if self.offset is not None:
                params["offset"] = self.offset
            r = requests.get(f"{self.base}/getUpdates", params=params, timeout=timeout + 10)
            data = r.json()
            if not data.get("ok"):
                log.warning("Telegram getUpdates failed: %s", str(data)[:200])
                time.sleep(min(timeout, 5))
                return []
        except (requests.RequestException, ValueError) as e:
            log.warning("Telegram poll error: %s", e)
            time.sleep(min(timeout, 5))
            return []
        out = []
        for u in data.get("result", []):
            self.offset = u["update_id"] + 1
            msg = u.get("message") or {}
            # only the owner's chat may drive the bot
            if str((msg.get("chat") or {}).get("id")) == self.chat_id and msg.get("text"):
                out.append(msg["text"].strip())
        return out
