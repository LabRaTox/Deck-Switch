"""Profil automatisch wechseln, wenn ein Programm nach vorn kommt.

Wer OBS öffnet, will die Streaming-Tasten sehen; wer in den Editor wechselt,
seine Entwicklungstasten. Das ist der Sinn: Das Deck folgt dem, was gerade
vorn ist.

**Warum das ein KWin-Skript braucht.** Unter Wayland verrät kein Protokoll
einer gewöhnlichen Anwendung, welches Fenster den Fokus hat — das ist
Absicht und nicht zu umgehen. Der Compositor weiß es, und KDE lässt Skripte
in ihn hinein. Also läuft dort ein paar Zeilen JavaScript, das bei jedem
Fensterwechsel eine D-Bus-Nachricht an uns schickt. Anderswo (GNOME, wlroots)
geht derselbe Weg anders oder gar nicht; deshalb steht hier eine klare
Absage statt eines halben Versuchs.

Was gemeldet wird, ist die **Fensterklasse** (``resourceClass``, etwa ``obs``
oder ``code``) und der Fenstertitel. Beides bleibt in diesem Prozess: Es geht
nicht in die Konfiguration und nirgends nach außen.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import paths

if TYPE_CHECKING:  # pragma: no cover
    from ..runtime import Runtime

log = logging.getLogger(__name__)

#: Unser Name auf dem Sitzungsbus — das KWin-Skript ruft hierher.
DIENST = "de.labratox.deckswitch"
PFAD = "/fenster"
SCHNITTSTELLE = "de.labratox.Fenster"

#: KWin selbst.
KWIN = "org.kde.KWin"
KWIN_SCRIPTING = "/Scripting"

#: Unter diesem Namen liegt unser Skript im Compositor. **Nicht** der
#: Dateipfad: ``loadScript`` nimmt beides, ``unloadScript`` aber nur den
#: Namen — mit dem Pfad antwortet es ``false`` und lässt das Skript liegen.
#: Gemessen am 2026-08-23, nachdem Prüfskripte im laufenden KWin
#: hängengeblieben waren.
SKRIPTNAME = "deckswitch"

#: Das Skript, das im Compositor läuft. Bewusst kurz: Es entscheidet nichts,
#: es meldet nur. Alles Weitere passiert hier, wo es zu lesen und zu prüfen
#: ist.
SKRIPT = """// Von DECK//SWITCH angelegt — meldet Fensterwechsel über D-Bus.
function melde(fenster) {
  if (!fenster) return;
  callDBus("%(dienst)s", "%(pfad)s", "%(schnittstelle)s", "Aktiv",
           String(fenster.resourceClass || ""), String(fenster.caption || ""));
}
workspace.windowActivated.connect(melde);
melde(workspace.activeWindow);
""" % {"dienst": DIENST, "pfad": PFAD, "schnittstelle": SCHNITTSTELLE}


class SmartProfileService:
    """Hört auf Fensterwechsel und schaltet Profile um."""

    def __init__(self, runtime: "Runtime") -> None:
        self.runtime = runtime
        self.verfuegbar = False
        self.grund = "noch nicht gestartet"
        #: Zuletzt gesehenes Fenster — für die Anzeige in der GUI.
        self.letztes_fenster: tuple[str, str] = ("", "")
        self._bus: Any = None
        self._skript_pfad = ""

    # -- Aufbau ------------------------------------------------------------

    async def start(self) -> None:
        """Meldet uns am Bus an und lädt das Skript in den Compositor."""
        if not self._regeln_vorhanden():
            self.grund = "keine Regel eingerichtet"
            log.debug("Smart Profiles: %s", self.grund)
            return
        try:
            await self._starte()
        except Exception as exc:  # noqa: BLE001 — ein fehlender Compositor ist kein Absturz
            self.grund = f"{type(exc).__name__}: {exc}"
            log.info("Smart Profiles nicht verfügbar: %s", self.grund)

    def _regeln_vorhanden(self) -> bool:
        return any(profil.auto_apps for profil in self.runtime.config.profiles.values())

    async def _starte(self) -> None:
        from dbus_next.aio import MessageBus
        from dbus_next.service import ServiceInterface, method

        dienst = self

        class Fenster(ServiceInterface):
            def __init__(self) -> None:
                super().__init__(SCHNITTSTELLE)

            @method()
            def Aktiv(self, klasse: "s", titel: "s"):  # noqa: N802, F821 — Name und Signatur gibt D-Bus vor
                dienst._auf_fenster(klasse, titel)

        self._bus = await MessageBus().connect()
        self._bus.export(PFAD, Fenster())
        antwort = await self._bus.request_name(DIENST)
        log.debug("Smart Profiles: Busname %s → %s", DIENST, antwort)

        pfad = paths.DATA_DIR / "kwin" / "aktivesfenster.js"
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(SKRIPT, encoding="utf-8")
        self._skript_pfad = str(pfad)

        # Erst abräumen: Nach einem Absturz ohne sauberes Ende liegt das
        # Skript noch im Compositor, und ``loadScript`` antwortet dann mit
        # ``-1`` statt einer Nummer. Ohne diese Zeile führte das zu einem
        # Pfad ``/Scripting/Script-1``, den es nicht gibt.
        with contextlib.suppress(Exception):
            await self._kwin("unloadScript", "s", SKRIPTNAME)

        nummer = int(await self._kwin("loadScript", "ss", self._skript_pfad, SKRIPTNAME))
        if nummer < 0:
            raise RuntimeError(
                "KWin nimmt das Skript nicht an (vielleicht läuft eine zweite "
                "Instanz von DECK//SWITCH?)"
            )
        await self._kwin_script(nummer, "run")
        self.verfuegbar = True
        self.grund = ""
        log.info("Smart Profiles bereit (KWin-Skript %s)", nummer)

    async def stop(self) -> None:
        """Skript wieder entladen — sonst läuft es bis zum Abmelden weiter."""
        if self._skript_pfad:
            try:
                geklappt = await self._kwin("unloadScript", "s", SKRIPTNAME)
                if not geklappt:
                    log.warning("Smart Profiles: KWin hat das Skript nicht entladen")
            except Exception as exc:  # noqa: BLE001
                log.debug("Smart Profiles: Entladen fehlgeschlagen: %s", exc)
            self._skript_pfad = ""
        if self._bus is not None:
            self._bus.disconnect()
            self._bus = None
        self.verfuegbar = False

    # -- KWin --------------------------------------------------------------

    async def _kwin(self, methode: str, signatur: str, *argumente: Any) -> Any:
        from dbus_next import Message, MessageType

        antwort = await self._bus.call(
            Message(destination=KWIN, path=KWIN_SCRIPTING,
                    interface="org.kde.kwin.Scripting", member=methode,
                    signature=signatur, body=list(argumente))
        )
        if antwort.message_type is MessageType.ERROR:
            raise RuntimeError(f"KWin: {antwort.body[0] if antwort.body else antwort.error_name}")
        return antwort.body[0] if antwort.body else 0

    async def _kwin_script(self, nummer: int, methode: str) -> None:
        from dbus_next import Message

        await self._bus.call(
            Message(destination=KWIN, path=f"{KWIN_SCRIPTING}/Script{nummer}",
                    interface="org.kde.kwin.Script", member=methode)
        )

    # -- Die Regel ---------------------------------------------------------

    def _auf_fenster(self, klasse: str, titel: str) -> None:
        """Ein anderes Fenster ist nach vorn gekommen."""
        self.letztes_fenster = (klasse, titel)
        profil = self._passendes_profil(klasse, titel)
        for deck in self.runtime.decks.values():
            deck.auto_profil(profil.id if profil is not None else None)

    def _passendes_profil(self, klasse: str, titel: str):
        """Das erste Profil, dessen Muster auf dieses Fenster passt.

        Verglichen wird ohne Rücksicht auf Groß- und Kleinschreibung und als
        Teilzeichenkette: ``obs`` trifft ``obs`` wie ``obs-studio``. Gesucht
        wird in Klasse **und** Titel — manche Programme melden eine nichts
        sagende Klasse, tragen den Namen aber im Titel.
        """
        heuhaufen = f"{klasse}\\n{titel}".casefold()
        for profil in self.runtime.config.profiles.values():
            for muster in profil.auto_apps:
                nadel = muster.strip().casefold()
                if nadel and nadel in heuhaufen:
                    return profil
        return None

    def status(self) -> dict[str, Any]:
        """Was die GUI über diesen Dienst wissen will."""
        klasse, titel = self.letztes_fenster
        return {
            "available": self.verfuegbar,
            "reason": self.grund,
            "window": {"app": klasse, "title": titel},
        }

    async def neu_bewerten(self) -> None:
        """Nach einer Änderung an den Regeln neu aufsetzen.

        Kommt die erste Regel dazu, muss der Dienst überhaupt erst starten;
        fällt die letzte weg, hat er nichts mehr zu tun und das Skript kann
        aus dem Compositor.
        """
        soll = self._regeln_vorhanden()
        if soll and not self.verfuegbar:
            await self.start()
        elif not soll and self.verfuegbar:
            await self.stop()
            self.grund = "keine Regel eingerichtet"
        elif soll and self.verfuegbar:
            # Regeln geändert, Dienst läuft: einmal auf das aktuelle Fenster
            # anwenden, damit die Änderung sofort greift.
            klasse, titel = self.letztes_fenster
            if klasse or titel:
                self._auf_fenster(klasse, titel)
