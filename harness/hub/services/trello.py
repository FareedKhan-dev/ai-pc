"""Trello through its REST API (key and token in an OAuth header, never in the address): boards, lists, cards; create,
move, comment, set a due date, archive. Every card made or changed is read back."""
from ..http import Api, HubError
from . import Base, pick


class Trello(Base):
    name = "trello"

    def api(self):
        self.need("key", "token")
        auth = f'OAuth oauth_consumer_key="{self.creds["key"]}", oauth_token="{self.creds["token"]}"'
        return Api("https://api.trello.com/1", headers={"Authorization": auth}, service="trello", transport=self.transport)

    def whoami(self):
        me = self.api().get("members/me", params={"fields": "username,fullName"})
        return {"who": me.get("fullName") or me.get("username"), "where": "Trello"}

    def boards(self):
        return [{"id": b["id"], "name": b["name"], "url": b.get("url")} for b in self.api().get("members/me/boards", params={"fields": "name,url,closed"})
                if not b.get("closed")]

    def lists(self, board):
        b = board if isinstance(board, dict) else self.board(board)
        return [{"id": x["id"], "name": x["name"], "board": b["id"]} for x in self.api().get(f"boards/{b['id']}/lists", params={"fields": "name,closed"})
                if not x.get("closed")]

    def board(self, name=None):
        bs = self.boards()
        if not bs:
            raise HubError("trello: you have no boards")
        b = pick(bs, name) if name else bs[0]
        if not b:
            raise HubError(f"trello: no board called {name} (boards: {', '.join(x['name'] for x in bs[:8])})")
        return b

    def list_(self, name, board=None):
        b = self.board(board)
        ls = self.lists(b)
        x = pick(ls, name) if name else (ls[0] if ls else None)
        if not x:
            raise HubError(f"trello: no list called {name} on {b['name']} (lists: {', '.join(i['name'] for i in ls)})")
        return dict(x, board_name=b["name"])

    def cards(self, board=None, list_name=None):
        b = self.board(board)
        cards = self.api().get(f"boards/{b['id']}/cards", params={"fields": "name,due,dueComplete,idList,url,desc"})
        names = {x["id"]: x["name"] for x in self.lists(b)}
        out = [{"id": c["id"], "name": c["name"], "list": names.get(c["idList"], "?"), "due": c.get("due"), "done": c.get("dueComplete"), "url": c.get("url")}
               for c in cards]
        return [c for c in out if not list_name or pick([{"name": c["list"]}], list_name)]

    def card(self, name, board=None):
        c = pick(self.cards(board), name)
        if not c:
            raise HubError(f"trello: no card called {name}")
        return c

    def create(self, name, list_name=None, board=None, desc=None, due=None):
        lst = self.list_(list_name, board)
        c = self.api().post("cards", json={"idList": lst["id"], "name": name, "pos": "top", **({"desc": desc} if desc else {}), **({"due": due} if due else {})})
        back = self.api().get(f"cards/{c['id']}", params={"fields": "name,idList"})
        return {"id": c["id"], "url": c.get("url") or c.get("shortUrl"), "where": f"{lst['board_name']} / {lst['name']}", "name": name,
                "verified": back.get("name") == name and back.get("idList") == lst["id"], "undo": {"service": "trello", "op": "delete", "id": c["id"]}}

    def move(self, card_name, to_list, board=None):
        c = self.card(card_name, board)
        lst = self.list_(to_list, board)
        before = c["list"]
        self.api().put(f"cards/{c['id']}", json={"idList": lst["id"]})
        back = self.api().get(f"cards/{c['id']}", params={"fields": "idList"})
        prev = self.list_(before, board)
        return {"id": c["id"], "url": c["url"], "where": f"{before} -> {lst['name']}", "name": c["name"], "verified": back.get("idList") == lst["id"],
                "undo": {"service": "trello", "op": "move_id", "id": c["id"], "list_id": prev["id"]}}

    def move_id(self, id, list_id):  # noqa: A002
        self.api().put(f"cards/{id}", json={"idList": list_id})
        return {"id": id}

    def comment(self, card_name, text, board=None):
        c = self.card(card_name, board)
        a = self.api().post(f"cards/{c['id']}/actions/comments", json={"text": text})
        return {"id": a["id"], "where": c["name"], "url": c["url"], "verified": (a.get("data") or {}).get("text") == text,
                "undo": {"service": "trello", "op": "delete_comment", "card": c["id"], "id": a["id"]}}

    def delete_comment(self, card, id):  # noqa: A002
        self.api().delete(f"cards/{card}/actions/{id}/comments")
        return {"deleted": id}

    def archive(self, card_name, board=None):
        c = self.card(card_name, board)
        self.api().put(f"cards/{c['id']}", json={"closed": True})
        return {"id": c["id"], "where": c["name"], "undo": {"service": "trello", "op": "unarchive", "id": c["id"]}}

    def unarchive(self, id):  # noqa: A002
        self.api().put(f"cards/{id}", json={"closed": False})
        return {"id": id}

    def delete(self, id):  # noqa: A002
        self.api().delete(f"cards/{id}")
        return {"deleted": id}
