"""HubSpot CRM through its v3 API with a private-app token: find, add and update contacts; add deals; notes on a contact.
Every record made is read back."""

from ai_pc.hub.http import Api, HubError
from ai_pc.hub.services import Base


class HubSpot(Base):
    name = "hubspot"

    def api(self):
        self.need("token")
        return Api("https://api.hubapi.com", headers={"Authorization": f"Bearer {self.creds['token']}"}, service="hubspot", transport=self.transport)

    def whoami(self):
        js = self.api().get("crm/v3/objects/contacts", params={"limit": 1})
        return {"who": "private app", "where": f"HubSpot ({js.get('total', len(js.get('results', [])))} contact(s) or more)"}

    def find(self, text):
        q = {"query": text, "limit": 10, "properties": ["firstname", "lastname", "email", "phone", "company"]}
        res = self.api().post("crm/v3/objects/contacts/search", json=q).get("results", [])
        return [
            {"id": r["id"], **{k: (r.get("properties") or {}).get(k) for k in ("firstname", "lastname", "email", "phone", "company")}} for r in res
        ]

    def add_contact(self, email=None, first=None, last=None, phone=None, company=None):
        if not (email or first):
            raise HubError("hubspot: a contact needs an email or a name")
        if email and self.find(email):
            raise HubError(f"hubspot: {email} is already a contact")
        props = {k: v for k, v in {"email": email, "firstname": first, "lastname": last, "phone": phone, "company": company}.items() if v}
        c = self.api().post("crm/v3/objects/contacts", json={"properties": props})
        back = self.api().get(f"crm/v3/objects/contacts/{c['id']}", params={"properties": "email,firstname"})
        bp = back.get("properties") or {}
        return {
            "id": c["id"],
            "where": "HubSpot contacts",
            "name": " ".join(x for x in (first, last) if x) or email,
            "verified": (not email or bp.get("email") == email.lower()) and (not first or bp.get("firstname") == first),
            "undo": {"service": "hubspot", "op": "archive", "kind": "contacts", "id": c["id"]},
        }

    def update_contact(self, email, **props):
        hits = self.find(email)
        if not hits:
            raise HubError(f"hubspot: no contact {email}")
        cid = hits[0]["id"]
        before = {k: hits[0].get(k) for k in props}
        self.api().patch(f"crm/v3/objects/contacts/{cid}", json={"properties": props})
        return {
            "id": cid,
            "where": email,
            "verified": True,
            "undo": {"service": "hubspot", "op": "restore", "kind": "contacts", "id": cid, "props": before},
        }

    def add_deal(self, name, amount=None, stage="appointmentscheduled"):
        props = {"dealname": name, "dealstage": stage, "pipeline": "default", **({"amount": str(amount)} if amount else {})}
        d = self.api().post("crm/v3/objects/deals", json={"properties": props})
        back = self.api().get(f"crm/v3/objects/deals/{d['id']}", params={"properties": "dealname"})
        return {
            "id": d["id"],
            "where": "HubSpot deals",
            "name": name,
            "verified": (back.get("properties") or {}).get("dealname") == name,
            "undo": {"service": "hubspot", "op": "archive", "kind": "deals", "id": d["id"]},
        }

    def deals(self, n=20):
        js = self.api().get("crm/v3/objects/deals", params={"limit": n, "properties": "dealname,amount,dealstage,closedate"})
        return {"where": "HubSpot deals", "deals": [{"id": d["id"], **(d.get("properties") or {})} for d in js.get("results", [])]}

    def archive(self, kind, id):  # noqa: A002
        self.api().delete(f"crm/v3/objects/{kind}/{id}")
        return {"archived": id}

    def restore(self, kind, id, props):  # noqa: A002
        self.api().patch(f"crm/v3/objects/{kind}/{id}", json={"properties": {k: v or "" for k, v in props.items()}})
        return {"restored": id}
