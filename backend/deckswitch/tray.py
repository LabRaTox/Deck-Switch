"""Symbol im Systemabschnitt der Leiste (Tray).

Zeigt an, dass die Software läuft, und bietet ein Menü zum Öffnen der
Oberfläche, zum Neuverbinden und zum Beenden. Das Symbol spiegelt den
Gerätezustand: verbunden, gedimmt oder getrennt.

Umgesetzt über StatusNotifierItem — den D-Bus-Standard, den KDE Plasma,
GNOME (mit Erweiterung), Waybar und andere Leisten verstehen. Das vermeidet
eine GUI-Abhängigkeit im Backend: kein GTK, kein Qt, nur ``dbus-next``, das
ohnehin für D-Bus gebraucht wird.

Fehlt die Sitzung oder die Leiste (Server, TTY), wird das Tray still
übersprungen — das Backend läuft davon unbeeindruckt weiter.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import struct
import subprocess
import webbrowser
from collections.abc import Callable

from dbus_next import BusType, Variant
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, dbus_property, method, signal
from dbus_next.constants import PropertyAccess
from PIL import Image

from . import paths

from .services import brand

log = logging.getLogger(__name__)

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"

#: Größen, die dem Tray angeboten werden. Deckt die üblichen Panel-Höhen ab
#: (16/18/22/24) und die verdoppelten Werte für Bildschirmskalierung.
ICON_SIZES = (16, 18, 22, 24, 32, 36, 44, 48, 64)


# --------------------------------------------------------------------------
# Symbol
# --------------------------------------------------------------------------


def _argb_pixmap(image: Image.Image) -> list:
    """Wandelt ein Bild in das Pixmap-Format von StatusNotifierItem.

    Erwartet wird ARGB32 in Netzwerk-Byte-Reihenfolge — Pillow liefert RGBA
    in Little-Endian, die Kanäle müssen also umsortiert werden.
    """
    rgba = image.convert("RGBA")
    data = bytearray()
    for r, g, b, a in rgba.getdata():
        data += struct.pack(">BBBB", a, r, g, b)
    return [[rgba.width, rgba.height, bytes(data)]]


# --------------------------------------------------------------------------
# Menü (com.canonical.dbusmenu)
# --------------------------------------------------------------------------


class TrayMenu(ServiceInterface):
    """Das Kontextmenü des Tray-Symbols."""

    def __init__(self, entries: list[dict]) -> None:
        super().__init__("com.canonical.dbusmenu")
        self.entries = entries
        self._revision = 1

    # -- Eigenschaften -----------------------------------------------------

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> "u":  # noqa: F821
        return 3

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":  # noqa: F821
        return "normal"

    @dbus_property(access=PropertyAccess.READ)
    def TextDirection(self) -> "s":  # noqa: F821
        return "ltr"

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "as":  # noqa: F821
        return []

    # -- Aufbau ------------------------------------------------------------

    def _item(self, index: int, entry: dict) -> list:
        properties = {
            "label": Variant("s", entry.get("label", "")),
            "enabled": Variant("b", entry.get("enabled", True)),
            "visible": Variant("b", True),
        }
        if entry.get("separator"):
            properties["type"] = Variant("s", "separator")
        return [index + 1, properties, []]

    @method()
    def GetLayout(
        self, parentId: "i", recursionDepth: "i", propertyNames: "as"  # noqa: F821
    ) -> "u(ia{sv}av)":  # noqa: F821
        children = [
            Variant("(ia{sv}av)", self._item(i, entry))
            for i, entry in enumerate(self.entries)
        ]
        return [self._revision, [0, {"children-display": Variant("s", "submenu")}, children]]

    @method()
    def GetGroupProperties(
        self, ids: "ai", propertyNames: "as"  # noqa: F821
    ) -> "a(ia{sv})":  # noqa: F821
        result = []
        for i, entry in enumerate(self.entries):
            if not ids or (i + 1) in ids:
                item = self._item(i, entry)
                result.append([item[0], item[1]])
        return result

    @method()
    def GetProperty(self, id: "i", name: "s") -> "v":  # noqa: F821
        index = id - 1
        if 0 <= index < len(self.entries):
            return Variant("s", str(self.entries[index].get(name, "")))
        return Variant("s", "")

    @method()
    def Event(self, id: "i", eventId: "s", data: "v", timestamp: "u"):  # noqa: F821
        if eventId != "clicked":
            return
        index = id - 1
        if 0 <= index < len(self.entries):
            action = self.entries[index].get("action")
            if callable(action):
                asyncio.get_event_loop().call_soon(action)

    @method()
    def AboutToShow(self, id: "i") -> "b":  # noqa: F821
        return False

    @signal()
    def LayoutUpdated(self) -> "ui":  # noqa: F821
        self._revision += 1
        return [self._revision, 0]


# --------------------------------------------------------------------------
# Tray-Symbol (org.kde.StatusNotifierItem)
# --------------------------------------------------------------------------


class TrayItem(ServiceInterface):
    def __init__(self, tray: "SystemTray") -> None:
        super().__init__("org.kde.StatusNotifierItem")
        self.tray = tray

    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":  # noqa: F821
        return "Hardware"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":  # noqa: F821
        return "deckswitch"

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":  # noqa: F821
        return "DECK//SWITCH"

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":  # noqa: F821
        return "Active"

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":  # noqa: F821
        # Kein Theme-Icon: das Symbol wird gezeichnet und als Pixmap geliefert.
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def IconPixmap(self) -> "a(iiay)":  # noqa: F821
        return self.tray.pixmaps()

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconName(self) -> "s":  # noqa: F821
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconName(self) -> "s":  # noqa: F821
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def ToolTip(self) -> "(sa(iiay)ss)":  # noqa: F821
        return ["", [], "DECK//SWITCH", self.tray.tooltip()]

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":  # noqa: F821
        # False: ein Linksklick öffnet die Oberfläche, statt nur das Menü.
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":  # noqa: F821
        return MENU_PATH

    @method()
    def Activate(self, x: "i", y: "i"):  # noqa: F821
        self.tray.open_gui()

    @method()
    def SecondaryActivate(self, x: "i", y: "i"):  # noqa: F821
        self.tray.open_gui()

    @method()
    def Scroll(self, delta: "i", orientation: "s"):  # noqa: F821
        self.tray.on_scroll(delta)

    # Signale ohne Nutzdaten: dbus-next leitet die leere Signatur daraus ab,
    # dass keine Rückgabe-Annotation angegeben ist.
    @signal()
    def NewIcon(self):
        pass

    @signal()
    def NewToolTip(self):
        pass

    @signal()
    def NewStatus(self) -> "s":  # noqa: F821
        return "Active"


# --------------------------------------------------------------------------
# Steuerung
# --------------------------------------------------------------------------


class SystemTray:
    """Meldet ein Tray-Symbol an und hält es aktuell."""

    def __init__(
        self,
        *,
        url: str,
        on_reconnect: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        on_brightness: Callable[[int], None] | None = None,
    ) -> None:
        self.url = url
        self._on_reconnect = on_reconnect
        self._on_quit = on_quit
        self._on_brightness = on_brightness

        self.bus: MessageBus | None = None
        self.item: TrayItem | None = None
        self.menu: TrayMenu | None = None

        self.connected = False
        self.dimmed = False
        self.device_name = ""
        self.detail = "Backend läuft"

    # -- Anmelden ----------------------------------------------------------

    async def start(self) -> bool:
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            log.info("Kein Sitzungsbus — Tray-Symbol übersprungen")
            return False

        try:
            self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
        except Exception as exc:
            log.info("Sitzungsbus nicht erreichbar, kein Tray-Symbol: %s", exc)
            return False

        self.item = TrayItem(self)
        self.menu = TrayMenu(self._entries())
        self.bus.export(ITEM_PATH, self.item)
        self.bus.export(MENU_PATH, self.menu)

        name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        try:
            await self.bus.request_name(name)
            introspection = await self.bus.introspect(WATCHER_NAME, WATCHER_PATH)
            proxy = self.bus.get_proxy_object(WATCHER_NAME, WATCHER_PATH, introspection)
            watcher = proxy.get_interface(WATCHER_NAME)
            await watcher.call_register_status_notifier_item(name)
        except Exception as exc:
            # Keine Leiste, die StatusNotifierItem versteht — kein Grund,
            # das Backend zu stoppen.
            log.info("Tray-Symbol nicht anmeldbar (keine passende Leiste?): %s", exc)
            await self.stop()
            return False

        log.info("Tray-Symbol angemeldet")
        return True

    async def stop(self) -> None:
        bus, self.bus = self.bus, None
        if bus is not None:
            with contextlib.suppress(Exception):
                bus.disconnect()

    # -- Zustand -----------------------------------------------------------

    def update(self, *, connected: bool, dimmed: bool = False, device_name: str = "",
               detail: str = "") -> None:
        changed = (connected, dimmed) != (self.connected, self.dimmed)
        self.connected = connected
        self.dimmed = dimmed
        self.device_name = device_name
        if detail:
            self.detail = detail

        if self.item is None:
            return
        with contextlib.suppress(Exception):
            self.item.NewToolTip()
            if changed:
                self.item.NewIcon()

    def pixmaps(self) -> list:
        # Reichlich Größen anbieten: Findet die Leiste keine passende, skaliert
        # sie selbst — und ein hochgerechnetes 22er sieht bei 24 Pixeln
        # ausgefranst aus. Jede Größe wird ohnehin frisch gezeichnet.
        result = []
        for size in ICON_SIZES:
            image = brand.icon_image(size, connected=self.connected, dimmed=self.dimmed)
            result.extend(_argb_pixmap(image))
        return result

    def tooltip(self) -> str:
        if self.connected:
            state = f"{self.device_name or 'Gerät'} verbunden"
            if self.dimmed:
                state += " (abgedunkelt)"
        else:
            state = "Kein Gerät verbunden"
        return f"{state}\n{self.url}"

    # -- Menüaktionen ------------------------------------------------------

    def _entries(self) -> list[dict]:
        return [
            {"label": "Oberfläche öffnen", "action": self.open_gui},
            {"separator": True, "label": ""},
            {"label": "Gerät neu verbinden", "action": self._reconnect},
            {"separator": True, "label": ""},
            {"label": "Beenden", "action": self._quit},
        ]

    def open_gui(self) -> None:
        """Öffnet das Fenster; ersatzweise die Oberfläche im Browser.

        Das Fenster ist der reguläre Weg in die Anwendung. Nur wenn es
        keines gibt — nicht gebaut, nicht installiert — bleibt der Browser,
        der dieselbe Oberfläche vom selben Server bekommt.
        """
        befehl = paths.gui_command()
        if befehl is not None:
            try:
                # Eigene Sitzung: Das Fenster soll weiterleben, wenn das
                # Backend neu startet, und nicht an dessen Prozessgruppe
                # hängen.
                # Ausgaben landen im Nichts, nicht im Journal: WebKitGTK
                # schreibt beim Start seitenweise eigene Fehlermeldungen,
                # die hier nur das Log zumüllen würden. Dass gestartet
                # wurde, hält stattdessen diese Zeile fest.
                subprocess.Popen(
                    befehl,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                log.info("Fenster gestartet: %s", " ".join(befehl))
                return
            except OSError as exc:
                log.warning("Fenster ließ sich nicht starten: %s", exc)

        try:
            webbrowser.open(self.url)
        except Exception as exc:
            log.warning("Oberfläche ließ sich nicht öffnen: %s", exc)

    def _reconnect(self) -> None:
        if self._on_reconnect is not None:
            self._on_reconnect()

    def _quit(self) -> None:
        if self._on_quit is not None:
            self._on_quit()

    def on_scroll(self, delta: int) -> None:
        """Scrollen über dem Symbol regelt die Helligkeit."""
        if self._on_brightness is not None:
            self._on_brightness(5 if delta > 0 else -5)
