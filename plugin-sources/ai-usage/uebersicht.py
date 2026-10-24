"""Die Ordnerseite hinter „Übersicht öffnen“.

Ein Ordner ist in DECK//SWITCH eine Seite mit ``parent_id``. Die Übersicht
legt unter der Seite, auf der die Taste liegt, eine Unterseite an. Links
oben liegt „Zurück“ aus dem Streamdeck-Plugin, danach folgt je aktivem
Anbieter eine Taste „Anbieter“. Passen nicht alle auf eine Seite, hängt
darunter eine weitere, und die letzte Taste führt dorthin.

Bei jedem Druck wird die Seite aktualisiert. Neue Anbieter kommen dazu,
abgeschaltete verschwinden. Tasten, die schon da waren, bleiben dieselben
Objekte, damit Änderungen am Aussehen aus der GUI erhalten bleiben.

Erkannt wird die Seite an ihren eigenen Tasten (``overview: true`` in den
Einstellungen) und nicht an einer gespeicherten ID. Wird die Seite
gelöscht, legt der nächste Druck sie neu an.
"""

from __future__ import annotations

from deckswitch.config import Appearance, Page, Slot

PLUGIN_ID = "ai-usage"
MARKER = "overview"


def is_overview_page(page: Page) -> bool:
    return any(
        slot.plugin_id == PLUGIN_ID and slot.settings.get(MARKER) is True
        for slot in page.keys.values()
    )


def chain(profile, parent_id: str) -> list[Page]:
    """Die bestehenden Übersichtsseiten unter ``parent_id``, in Reihenfolge."""
    pages: list[Page] = []
    current = parent_id
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        found = next((p for p in profile.children(current) if is_overview_page(p)), None)
        if found is None:
            break
        pages.append(found)
        current = found.id
    return pages


def split(providers: list[str], key_count: int) -> list[list[str]]:
    """Verteilt die Anbieter auf Seiten.

    Jede Seite hat links oben „Zurück“. Alle Seiten außer der letzten
    brauchen zusätzlich „Weiter“, dort ist also eine Taste weniger frei.
    """
    room_last = max(1, key_count - 1)
    room_more = max(1, key_count - 2)
    if len(providers) <= room_last:
        return [providers]
    chunks = []
    rest = list(providers)
    while len(rest) > room_last:
        chunks.append(rest[:room_more])
        rest = rest[room_more:]
    chunks.append(rest)
    return chunks


def sync(profile, parent_id: str, providers: list[tuple[str, str]], *, key_count: int,
         settings: dict, texts) -> list[Page]:
    """Bringt die Übersicht unter ``parent_id`` auf den Stand von ``providers``.

    ``providers`` ist eine Liste aus ``(id, name)``. ``texts`` liefert zu
    einem Schlüssel den Text in der eingestellten Sprache. Zurück kommen die
    Seiten der Übersicht; die erste ist das Ziel des Tastendrucks.
    """
    existing = chain(profile, parent_id)
    reuse: dict[str, Slot] = {}
    for page in existing:
        for slot in page.keys.values():
            if slot.plugin_id == PLUGIN_ID and slot.settings.get(MARKER) is True:
                reuse.setdefault(str(slot.settings.get("provider")), slot)

    ids = [pid for pid, _ in providers]
    chunks = split(ids, key_count)
    pages: list[Page] = []
    parent = parent_id
    title = texts("overview")

    for number, chunk in enumerate(chunks):
        page = existing[number] if number < len(existing) else None
        if page is None:
            page = Page(name=title if number == 0 else f"{title} {number + 1}", parent_id=parent)
            profile.pages[page.id] = page
        page.parent_id = parent

        keys: dict[int, Slot] = {0: _back(page, texts("back"))}
        for offset, provider_id in enumerate(chunk, start=1):
            slot = reuse.get(provider_id) or Slot(plugin_id=PLUGIN_ID, action_id="provider")
            slot.settings.update({
                "provider": provider_id,
                MARKER: True,
                "window": settings.get("window") or "session",
                "display": settings.get("display") or "used",
                "style": settings.get("style") or "ring",
            })
            keys[offset] = slot
        page.keys = keys
        pages.append(page)
        parent = page.id

    # „Weiter“ kommt erst jetzt dazu, weil vorher die Folgeseiten noch nicht feststehen.
    for page, following in zip(pages, pages[1:]):
        page.keys[key_count - 1] = Slot(
            plugin_id="streamdeck",
            action_id="folder",
            settings={"page_id": following.id},
            appearance=Appearance(label_text=texts("more")),
        )

    # Nicht mehr benötigte Seiten samt ihren Unterseiten entfernen.
    for stale in existing[len(pages):]:
        for page_id in profile.subtree_ids(stale.id):
            profile.pages.pop(page_id, None)

    return pages


def _back(page: Page, label: str) -> Slot:
    current = page.keys.get(0)
    if current is not None and current.plugin_id == "streamdeck" and current.action_id == "back":
        return current
    return Slot(plugin_id="streamdeck", action_id="back", appearance=Appearance(label_text=label))
