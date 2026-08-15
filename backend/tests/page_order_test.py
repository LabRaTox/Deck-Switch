"""Prüft Reihenfolge und Verschieben von Seiten und Unterseiten.

Deckt ab: Sortierung nach ``order`` (inkl. Altbestand ohne gepflegte Werte),
Umsortieren unter denselben Geschwistern, Umhängen an ein anderes Elternteil,
die Sperre gegen Ringschlüsse und die Frage, ob das Blättern am Gerät der
sortierten Reihenfolge folgt.

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/page_order_test.py
"""
import asyncio
import json
import sys

from deckswitch.config import Page, Profile
from deckswitch.runtime import Runtime
from deckswitch.server import create_app

FAILS = []


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self.body = body

    def json(self):
        return json.loads(self.body or b"{}")


def request(app, method, path, payload=None):
    """Ruft die ASGI-App direkt auf.

    Bewusst ohne ``TestClient``: der verlangt ``httpx``, das hier nicht
    installiert ist — und für ein paar JSON-Aufrufe reicht das ASGI-Protokoll
    von Hand.
    """
    body = json.dumps(payload).encode() if payload is not None else b""
    messages = [
        {"type": "http.request", "body": body, "more_body": False},
    ]
    received = {"status": 500, "body": b""}

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            received["status"] = message["status"]
        elif message["type"] == "http.response.body":
            received["body"] += message.get("body", b"")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8770),
    }

    async def run():
        await app(scope, receive, send)

    asyncio.run(run())
    return Response(received["status"], received["body"])


def check(name, condition, detail=""):
    print(("  ✔ " if condition else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def names(profile, parent_id):
    return [p.name for p in profile.children(parent_id)]


def main():
    # ---- reines Datenmodell ------------------------------------------------
    print("\n== Sortierung ==")
    root = Page(name="Start", order=0)
    profile = Profile(name="T", root_page_id=root.id, pages={root.id: root})
    for position, name in enumerate(["A", "B", "C"]):
        page = Page(name=name, parent_id=root.id, order=position)
        profile.pages[page.id] = page
    ids = {p.name: p.id for p in profile.pages.values()}

    check("Kinder in order-Reihenfolge", names(profile, root.id) == ["A", "B", "C"])

    # Altbestand: alle order=0 → Dict-Reihenfolge muss erhalten bleiben.
    for page in profile.pages.values():
        page.order = 0
    check("gleicher order behält Dict-Reihenfolge", names(profile, root.id) == ["A", "B", "C"])
    for position, name in enumerate(["A", "B", "C"]):
        profile.pages[ids[name]].order = position

    print("\n== Umsortieren ==")
    profile.move_page(ids["C"], root.id, 0)
    check("C nach ganz vorn", names(profile, root.id) == ["C", "A", "B"])
    profile.move_page(ids["C"], root.id, 2)
    check("C wieder ans Ende", names(profile, root.id) == ["A", "B", "C"])
    check(
        "order lückenlos 0..n-1",
        [p.order for p in profile.children(root.id)] == [0, 1, 2],
    )

    print("\n== Umhängen ==")
    profile.move_page(ids["B"], ids["A"], 0)
    check("B liegt unter A", names(profile, ids["A"]) == ["B"])
    check("altes Elternteil neu durchnummeriert", [p.order for p in profile.children(root.id)] == [0, 1])
    check("Geschwister ohne B", names(profile, root.id) == ["A", "C"])

    deep = Page(name="D", parent_id=ids["B"], order=0)
    profile.pages[deep.id] = deep
    check("Teilbaum von A", profile.subtree_ids(ids["A"]) == {ids["A"], ids["B"], deep.id})

    # ---- über die HTTP-Schnittstelle --------------------------------------
    print("\n== Endpunkte ==")
    runtime = Runtime()
    app = create_app(runtime)
    live = runtime.config.active_profile()
    live_root = live.root_page().id

    created = [
        request(app, "POST", "/api/pages", {"name": n, "parent_id": None}).json()
        for n in ("Eins", "Zwei", "Drei")
    ]
    check("neue Seiten hängen hinten an", [p["order"] for p in created] == [1, 2, 3])

    response = request(app, "POST", f"/api/pages/{created[2]['id']}/move", {"parent_id": None, "index": 0})
    check("move liefert 200", response.status_code == 200, str(response.status_code))
    check(
        "Drei steht vorn",
        [p.name for p in live.children(None)] == ["Drei", "Start", "Eins", "Zwei"],
        str([p.name for p in live.children(None)]),
    )

    response = request(
        app,
        "POST",
        f"/api/pages/{created[0]['id']}/move",
        {"parent_id": created[1]["id"], "index": 0},
    )
    check("Eins wird Unterseite von Zwei", response.status_code == 200)
    check("Zwei hat ein Kind", [p.name for p in live.children(created[1]["id"])] == ["Eins"])

    # Ringschluss: Zwei unter sein eigenes Kind hängen.
    response = request(
        app,
        "POST",
        f"/api/pages/{created[1]['id']}/move",
        {"parent_id": created[0]["id"], "index": 0},
    )
    check("Ringschluss abgelehnt", response.status_code == 400, str(response.status_code))
    check("Struktur unverändert", live.pages[created[1]["id"]].parent_id is None)

    response = request(app, "POST", f"/api/pages/{live_root}/move", {"parent_id": created[1]["id"], "index": 0})
    check("Startseite bleibt Wurzel", response.status_code == 400, str(response.status_code))

    print("\n== Blättern folgt der Sortierung ==")
    order_ids = [p.id for p in live.children(None)]
    runtime.navigate(order_ids[0])
    runtime.step_page(1, wrap=False)
    check(
        "nächste Seite ist der sortierte Nachbar",
        runtime.current_page_id() == order_ids[1],
        live.pages[runtime.current_page_id()].name,
    )

    print("\n== Löschen ==")
    before = len(live.pages)
    response = request(app, "DELETE", f"/api/pages/{created[1]['id']}")
    check("Unterseite mitgelöscht", len(live.pages) == before - 2, str(response.json()))
    check(
        "Rest lückenlos nummeriert",
        [p.order for p in live.children(None)] == list(range(len(live.children(None)))),
    )

    print("\n" + ("Alle Prüfungen bestanden." if not FAILS else f"FEHLER: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
