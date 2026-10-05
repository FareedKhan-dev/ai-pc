"""WhatsApp Business through Meta's Cloud API (a business number, e.g. the free test number): a text to someone who wrote
to the business in the last 24 hours, or an approved template to anyone; a personal WhatsApp account has no API."""

import re

from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base

GRAPH = "https://graph.facebook.com/v23.0"


def number(n):
    """'0300-1234567' or '+92 300 1234567' -> '923001234567' (international, digits only; Pakistani 03xx assumed)."""
    d = re.sub(r"\D", "", n or "")
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("0") and len(d) == 11:
        d = "92" + d[1:]
    if len(d) < 10:
        raise HubError(f"whatsapp: {n} is not a full phone number")
    return d


class WhatsApp(Base):
    name = "whatsapp"

    def api(self):
        self.need("token", "phone_number_id")
        return Api(GRAPH, headers={"Authorization": f"Bearer {self.creds['token']}"}, service="whatsapp", transport=self.transport)

    def whoami(self):
        p = self.api().get(self.creds["phone_number_id"], params={"fields": "display_phone_number,verified_name"})
        return {"who": p.get("verified_name"), "where": p.get("display_phone_number")}

    def send(self, to, text):
        js = self.api().post(
            f"{self.creds['phone_number_id']}/messages",
            json={"messaging_product": "whatsapp", "to": number(to), "type": "text", "text": {"body": text, "preview_url": False}},
        )
        mid = (js.get("messages") or [{}])[0].get("id")
        return {"id": mid, "where": f"WhatsApp +{number(to)}", "verified": bool(mid), "undo": None}

    def send_template(self, to, template="hello_world", lang="en_US", params=()):
        tpl = {"name": template, "language": {"code": lang}}
        if params:
            tpl["components"] = [{"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]}]
        js = self.api().post(
            f"{self.creds['phone_number_id']}/messages", json={"messaging_product": "whatsapp", "to": number(to), "type": "template", "template": tpl}
        )
        mid = (js.get("messages") or [{}])[0].get("id")
        return {"id": mid, "where": f"WhatsApp +{number(to)}", "verified": bool(mid), "undo": None}
