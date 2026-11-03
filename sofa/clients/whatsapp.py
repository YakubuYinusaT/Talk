"""WhatsApp, through Meta's WhatsApp Cloud API: sending a message to a person who wrote to Talk, and fetching a photo they sent."""

import logging

import httpx

log = logging.getLogger("sofa.whatsapp")

GRAPH = "https://graph.facebook.com/v21.0"


class WhatsAppClient:
    def __init__(self, phone_number_id: str, access_token: str):
        self.phone_number_id = phone_number_id
        self.http = httpx.AsyncClient(timeout=20, headers={"Authorization": f"Bearer {access_token}"})
        self._display = None

    @property
    def ready(self) -> bool:
        return bool(self.phone_number_id)

    async def send_text(self, to: str, body: str) -> tuple[str, str | None]:
        """Returns (status, message id): "sent" when Meta accepted the message, "failed" otherwise. `to` is the number in international form, with or
        without the plus sign."""
        payload = {"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "text", "text": {"preview_url": False, "body": body[:4000]}}
        try:
            resp = await self.http.post(f"{GRAPH}/{self.phone_number_id}/messages", json=payload)
        except httpx.HTTPError as exc:
            log.error("WhatsApp could not be reached: %s", type(exc).__name__)
            return "failed", None
        if resp.status_code >= 300:
            log.error("WhatsApp refused a message: HTTP %s %s", resp.status_code, (resp.json().get("error") or {}).get("message", "") if resp.content else "")
            return "failed", None
        return "sent", ((resp.json().get("messages") or [{}])[0]).get("id")

    async def media(self, media_id: str) -> tuple[bytes, str] | None:
        """A photo the person sent: its bytes and its type, or None when it could not be fetched."""
        try:
            info = await self.http.get(f"{GRAPH}/{media_id}")
            info.raise_for_status()
            meta = info.json()
            got = await self.http.get(meta["url"])
            got.raise_for_status()
            return got.content, str(meta.get("mime_type") or "image/jpeg")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.error("a WhatsApp photo could not be fetched: %s", type(exc).__name__)
            return None

    async def display_number(self) -> str:
        """The business number as digits, for the wa.me link on the website. Asked once."""
        if self._display is None:
            try:
                resp = await self.http.get(f"{GRAPH}/{self.phone_number_id}", params={"fields": "display_phone_number"})
                self._display = "".join(c for c in resp.json().get("display_phone_number", "") if c.isdigit()) if resp.status_code == 200 else ""
            except httpx.HTTPError:
                self._display = ""
        return self._display
