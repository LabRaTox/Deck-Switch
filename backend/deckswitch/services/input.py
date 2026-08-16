"""Tastendrücke und Text an den Rechner schicken.

Der Weg führt über ``/dev/uinput``: Wir melden ein virtuelles Keyboard beim
Kernel an und schreiben dort Ereignisse hinein. Das ist unter Wayland der
einzige Weg, der ohne Compositor-Unterstützung funktioniert — Werkzeuge wie
``wtype`` sprechen wlroots-Protokolle, die KWin nicht anbietet, und ``xdotool``
erreicht nur XWayland-Fenster.

Zwei Dinge, die man dabei leicht falsch macht:

* **Der Kernel kennt keine Zeichen, nur Tastenpositionen.** Welches Zeichen
  aus einer Position wird, entscheidet die Tastaturbelegung des Compositors.
  Wer für „z" stur ``KEY_Z`` schickt, tippt auf einer deutschen Belegung ein
  „y". Deshalb wird die Zuordnung Zeichen → Taste hier aus der *tatsächlich
  eingestellten* Belegung berechnet (libxkbcommon), nicht geraten.
* **Ein frisch angemeldetes uinput-Gerät braucht einen Moment**, bis
  libinput es übernommen hat. Wer sofort losschreibt, verliert die ersten
  Anschläge. Das Gerät bleibt deshalb offen und wird einmalig eingerichtet.

Rechte: ``/dev/uinput`` gehört der Gruppe ``input``. Wer da nicht drin ist,
bekommt eine verständliche Meldung statt eines Tracebacks — die udev-Regel
des Projekts richtet das ein.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time

log = logging.getLogger(__name__)

#: Pause zwischen Anschlägen beim Tippen von Text. Ohne Pause verschlucken
#: manche Programme (Terminals, Spiele) Zeichen, weil sie die Eingabe nur
#: einmal pro Frame abholen.
TYPE_DELAY_S = 0.012

#: So lange wartet die erste Eingabe nach dem Anmelden des Geräts.
SETTLE_S = 0.25

#: Obergrenze für „Text tippen". Bei 12 ms je Zeichen wären 5000 Zeichen
#: schon eine Minute, in der die Tastatur belegt ist und Anschläge in
#: irgendein Fenster laufen. Wer mehr braucht, will in Wahrheit die
#: Zwischenablage.
MAX_TEXT_LENGTH = 5000

#: Modifier, wie sie in einer Kombination stehen dürfen — Schreibweise egal.
MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "strg": "ctrl",
    "shift": "shift",
    "umschalt": "shift",
    "alt": "alt",
    "altgr": "altgr",
    "alt_gr": "altgr",
    "super": "super",
    "meta": "super",
    "win": "super",
    "cmd": "super",
}

#: Tasten, die kein Zeichen erzeugen und deshalb nicht über die Belegung
#: gefunden werden können. Namen bewusst tolerant (deutsch wie englisch).
NAMED_KEYS = {
    "enter": "KEY_ENTER",
    "return": "KEY_ENTER",
    "eingabe": "KEY_ENTER",
    "tab": "KEY_TAB",
    "tabulator": "KEY_TAB",
    "space": "KEY_SPACE",
    "leertaste": "KEY_SPACE",
    "backspace": "KEY_BACKSPACE",
    "rücktaste": "KEY_BACKSPACE",
    "delete": "KEY_DELETE",
    "entf": "KEY_DELETE",
    "escape": "KEY_ESC",
    "esc": "KEY_ESC",
    "up": "KEY_UP",
    "hoch": "KEY_UP",
    "down": "KEY_DOWN",
    "runter": "KEY_DOWN",
    "left": "KEY_LEFT",
    "links": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "rechts": "KEY_RIGHT",
    "home": "KEY_HOME",
    "pos1": "KEY_HOME",
    "end": "KEY_END",
    "ende": "KEY_END",
    "pageup": "KEY_PAGEUP",
    "bild_hoch": "KEY_PAGEUP",
    "pagedown": "KEY_PAGEDOWN",
    "bild_runter": "KEY_PAGEDOWN",
    "insert": "KEY_INSERT",
    "einfg": "KEY_INSERT",
    "print": "KEY_SYSRQ",
    "druck": "KEY_SYSRQ",
    "pause": "KEY_PAUSE",
    "menu": "KEY_COMPOSE",
    "capslock": "KEY_CAPSLOCK",
    "numlock": "KEY_NUMLOCK",
    "scrolllock": "KEY_SCROLLLOCK",
}
NAMED_KEYS.update({f"f{i}": f"KEY_F{i}" for i in range(1, 25)})

#: xkb-Modifiername → Taste, die wir dafür halten.
_XKB_MODIFIER_KEYS = {
    "Shift": "KEY_LEFTSHIFT",
    "Control": "KEY_LEFTCTRL",
    "Mod1": "KEY_LEFTALT",
    "Alt": "KEY_LEFTALT",
    "Mod4": "KEY_LEFTMETA",
    "Super": "KEY_LEFTMETA",
    "Mod5": "KEY_RIGHTALT",
    "LevelThree": "KEY_RIGHTALT",
}

_MODIFIER_KEY_NAMES = {
    "ctrl": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "alt": "KEY_LEFTALT",
    "altgr": "KEY_RIGHTALT",
    "super": "KEY_LEFTMETA",
}


class InputUnavailable(RuntimeError):
    """Eingaben lassen sich auf diesem System nicht schicken."""


def parse_combo(combo: str) -> tuple[list[str], str]:
    """Zerlegt ``"ctrl+shift+f5"`` in Modifier und Haupttaste.

    Die Haupttaste bleibt als Text stehen — ob sie über die Belegung oder
    über :data:`NAMED_KEYS` aufgelöst wird, entscheidet sich erst beim
    Senden, wenn die Belegung bekannt ist.
    """
    parts = [p.strip() for p in re.split(r"[+\s]+", combo or "") if p.strip()]
    modifiers: list[str] = []
    key = ""
    for part in parts:
        alias = MODIFIER_ALIASES.get(part.lower())
        if alias is not None:
            if alias not in modifiers:
                modifiers.append(alias)
        else:
            key = part
    return modifiers, key


class InputService:
    """Virtuelle Tastatur. Wird beim ersten Bedarf angelegt, nicht beim Start.

    Wer die App nur zum Lautstärkeregeln nutzt, soll kein Eingabegerät im
    System stehen haben.
    """

    def __init__(self) -> None:
        self._device = None
        self._lock = threading.Lock()
        self._ready_at = 0.0
        #: Tasten, die gerade absichtlich unten gehalten werden
        #: (Push-to-Talk). Ohne diese Liste bliebe eine Kombination im
        #: Kernel gedrückt, wenn das Loslassen nie kommt — etwa weil das
        #: Deck mittendrin abgezogen wurde.
        self._held: set[int] = set()
        #: Zeichen → (Tastencode, Modifier-Liste), aus der aktiven Belegung.
        self._chars: dict[str, tuple[int, list[str]]] = {}
        self._layout: str = ""
        self._unmapped: set[str] = set()

    # -- Öffentlich --------------------------------------------------------

    @property
    def layout(self) -> str:
        """Die Belegung, gegen die gerade abgebildet wird (z. B. ``de``)."""
        self._ensure_layout()
        return self._layout

    def available(self) -> tuple[bool, str]:
        """Geht das hier? Liefert ``(ok, Begründung)`` für die GUI."""
        try:
            import evdev  # noqa: F401
        except ImportError:
            return False, "Python-Paket 'evdev' fehlt"
        try:
            with open("/dev/uinput", "wb"):
                pass
        except PermissionError:
            return False, (
                "Kein Schreibrecht auf /dev/uinput — der Benutzer muss in der "
                "Gruppe 'input' sein (danach ab- und wieder anmelden)"
            )
        except OSError as exc:
            return False, f"/dev/uinput nicht nutzbar: {exc}"
        return True, ""

    def send_combo(self, combo: str) -> None:
        """Drückt eine Kombination einmal (drücken, loslassen)."""
        modifiers, key = parse_combo(combo)
        if not key and not modifiers:
            raise InputUnavailable("Keine Tastenkombination angegeben")

        code, extra_modifiers = self._resolve_key(key) if key else (None, [])
        held = [self._key_code(_MODIFIER_KEY_NAMES[m]) for m in modifiers]
        held += [
            self._key_code(name)
            for name in extra_modifiers
            if self._key_code(name) not in held
        ]

        with self._lock:
            device = self._open()
            self._settle()
            for mod in held:
                self._emit(device, mod, 1)
            if code is not None:
                self._emit(device, code, 1)
                self._emit(device, code, 0)
            for mod in reversed(held):
                self._emit(device, mod, 0)
            device.syn()

    def hold_combo(self, combo: str, pressed: bool) -> None:
        """Hält eine Kombination gedrückt bzw. lässt sie los (Push-to-Talk)."""
        modifiers, key = parse_combo(combo)
        code, extra_modifiers = self._resolve_key(key) if key else (None, [])
        held = [self._key_code(_MODIFIER_KEY_NAMES[m]) for m in modifiers]
        held += [self._key_code(name) for name in extra_modifiers]

        with self._lock:
            device = self._open()
            self._settle()
            if pressed:
                for mod in held:
                    self._emit(device, mod, 1)
                    self._held.add(mod)
                if code is not None:
                    self._emit(device, code, 1)
                    self._held.add(code)
            else:
                if code is not None:
                    self._emit(device, code, 0)
                    self._held.discard(code)
                for mod in reversed(held):
                    self._emit(device, mod, 0)
                    self._held.discard(mod)
            device.syn()

    def release_all(self) -> int:
        """Lässt alles los, was noch gedrückt gehalten wird.

        Gerufen, wenn ein Deck verschwindet oder die App endet: Ein
        steckengebliebenes Strg oder Shift macht den ganzen Desktop
        unbedienbar, und der Kernel räumt nur beim Abmelden des Geräts auf.
        """
        with self._lock:
            if not self._held or self._device is None:
                self._held.clear()
                return 0
            count = len(self._held)
            for code in sorted(self._held):
                try:
                    self._emit(self._device, code, 0)
                except Exception:  # pragma: no cover - beim Aufräumen egal
                    pass
            self._device.syn()
            self._held.clear()
            log.info("%d hängende Taste(n) losgelassen", count)
            return count

    def type_text(self, text: str, *, delay_s: float = TYPE_DELAY_S) -> int:
        """Tippt ``text`` Zeichen für Zeichen. Liefert die Zahl der Zeichen.

        Zeichen, die auf der aktiven Belegung nicht direkt erreichbar sind
        (etwa solche, die dort nur über Tottasten entstehen), werden
        übersprungen und einmalig ins Log geschrieben — lieber ein fehlendes
        Zeichen als eine Kombination, die etwas ganz anderes auslöst.
        """
        if len(text) > MAX_TEXT_LENGTH:
            raise InputUnavailable(
                f"Text ist zu lang ({len(text)} Zeichen, erlaubt sind "
                f"{MAX_TEXT_LENGTH}) — so lange wäre die Tastatur belegt."
            )

        self._ensure_layout()
        typed = 0
        with self._lock:
            device = self._open()
            self._settle()
            for char in text:
                if char == "\n":
                    entry: tuple[int, list[str]] | None = (
                        self._key_code("KEY_ENTER"),
                        [],
                    )
                elif char == "\t":
                    entry = (self._key_code("KEY_TAB"), [])
                else:
                    entry = self._chars.get(char)

                if entry is None:
                    if char not in self._unmapped:
                        self._unmapped.add(char)
                        log.warning(
                            "Zeichen %r ist auf der Belegung '%s' nicht direkt "
                            "erreichbar und wird übersprungen",
                            char,
                            self._layout,
                        )
                    continue

                code, modifier_names = entry
                mods = [self._key_code(name) for name in modifier_names]
                for mod in mods:
                    self._emit(device, mod, 1)
                self._emit(device, code, 1)
                self._emit(device, code, 0)
                for mod in reversed(mods):
                    self._emit(device, mod, 0)
                device.syn()
                typed += 1
                if delay_s > 0:
                    time.sleep(delay_s)
        return typed

    def close(self) -> None:
        self.release_all()
        with self._lock:
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:  # pragma: no cover - beim Beenden egal
                    pass
                self._device = None

    # -- Intern ------------------------------------------------------------

    def _emit(self, device, code: int, value: int) -> None:
        import evdev

        device.write(evdev.ecodes.EV_KEY, code, value)

    @staticmethod
    def _key_code(name: str) -> int:
        import evdev

        code = evdev.ecodes.ecodes.get(name)
        if code is None:
            raise InputUnavailable(f"Unbekannte Taste: {name}")
        return int(code)

    def _settle(self) -> None:
        """Wartet, bis der Compositor das frische Gerät übernommen hat."""
        remaining = self._ready_at - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

    def _open(self):
        if self._device is not None:
            return self._device

        ok, reason = self.available()
        if not ok:
            raise InputUnavailable(reason)

        import evdev
        from evdev import UInput

        self._ensure_layout()

        # Alle Tasten anmelden, die wir je brauchen könnten — nachträglich
        # lässt sich das Gerät nicht erweitern.
        codes = sorted(
            {
                code
                for name, code in evdev.ecodes.ecodes.items()
                if name.startswith("KEY_") and isinstance(code, int) and code < 256
            }
        )
        try:
            self._device = UInput(
                {evdev.ecodes.EV_KEY: codes},
                name="DECK//SWITCH virtuelle Tastatur",
                vendor=0x1D6B,
                product=0x0001,
            )
        except OSError as exc:
            raise InputUnavailable(f"Virtuelle Tastatur nicht anlegbar: {exc}") from exc

        self._ready_at = time.monotonic() + SETTLE_S
        log.info("Virtuelle Tastatur angemeldet (Belegung '%s')", self._layout)
        return self._device

    # -- Tastaturbelegung --------------------------------------------------

    def _resolve_key(self, key: str) -> tuple[int, list[str]]:
        """Haupttaste einer Kombination → (Tastencode, nötige Modifier).

        Ein einzelnes Zeichen wird über die Belegung gesucht: „Strg+Z" muss
        die Taste treffen, die auf *dieser* Belegung ein Z schreibt, nicht
        die, die auf einer amerikanischen dort läge.
        """
        name = NAMED_KEYS.get(key.lower())
        if name is not None:
            return self._key_code(name), []

        self._ensure_layout()
        entry = self._chars.get(key) or self._chars.get(key.lower())
        if entry is not None:
            code, modifiers = entry
            # Shift gehört bei einer Kombination nicht dazu: „Strg+Shift+1"
            # schreibt der User selbst hin, und ein „Strg+!" wäre auf der
            # deutschen Belegung sonst still ein „Strg+Shift+1".
            return code, [m for m in modifiers if m != "KEY_LEFTSHIFT"]

        # Letzter Versuch: Name wie in evdev (``KEY_KP1``).
        raw = key.upper() if key.upper().startswith("KEY_") else f"KEY_{key.upper()}"
        import evdev

        if raw in evdev.ecodes.ecodes:
            return self._key_code(raw), []
        raise InputUnavailable(f"Taste '{key}' nicht gefunden")

    def _ensure_layout(self) -> None:
        if self._chars:
            return
        layout = _detect_layout()
        self._layout = layout or "us"
        try:
            self._chars = _build_char_map(self._layout)
        except Exception as exc:
            log.warning(
                "Tastaturbelegung '%s' nicht auswertbar (%s) — es wird 'us' "
                "angenommen. Text mit Umlauten kann dadurch falsch ankommen.",
                self._layout,
                exc,
            )
            try:
                self._chars = _build_char_map("us")
                self._layout = "us"
            except Exception:
                self._chars = {}


def _detect_layout() -> str:
    """Die eingestellte Tastaturbelegung — erst KDE fragen, dann systemd."""
    if shutil.which("kreadconfig6"):
        value = _run(
            ["kreadconfig6", "--file", "kxkbrc", "--group", "Layout", "--key", "LayoutList"]
        )
        if value:
            return value.split(",")[0].strip()

    if shutil.which("localectl"):
        for line in _run(["localectl", "status"]).splitlines():
            if "X11 Layout" in line:
                return line.split(":", 1)[1].strip().split(",")[0]
            if "VC Keymap" in line and "n/a" not in line:
                return line.split(":", 1)[1].strip()
    return "us"


def _detect_variant() -> str:
    if shutil.which("kreadconfig6"):
        value = _run(
            ["kreadconfig6", "--file", "kxkbrc", "--group", "Layout", "--key", "VariantList"]
        )
        if value:
            return value.split(",")[0].strip()
    return ""


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _build_char_map(layout: str) -> dict[str, tuple[int, list[str]]]:
    """Zeichen → (Tastencode, Modifier) für eine Belegung.

    Gebaut aus derselben Bibliothek, mit der auch der Compositor arbeitet —
    damit stimmt die Zuordnung auch bei exotischen Varianten.
    """
    from xkbcommon import xkb

    context = xkb.Context()
    keymap = context.keymap_new_from_names(
        rules="evdev", model="pc105", layout=layout, variant=_detect_variant()
    )
    modifier_names = [keymap.mod_get_name(i) for i in range(keymap.num_mods())]

    mapping: dict[str, tuple[int, list[str]]] = {}
    for keycode in range(keymap.min_keycode(), keymap.max_keycode() + 1):
        try:
            levels = keymap.num_levels_for_key(keycode, 0)
        except Exception:
            continue
        for level in range(levels):
            symbols = keymap.key_get_syms_by_level(keycode, 0, level)
            if not symbols:
                continue
            try:
                char = xkb.keysym_to_string(symbols[0])
            except Exception:
                continue
            if not char or char in mapping:
                continue

            try:
                masks = keymap.key_get_mods_for_level(keycode, 0, level)
            except Exception:
                masks = []
            required = _mask_to_keys(masks[0] if masks else 0, modifier_names)
            if required is None:
                continue
            # xkb zählt Tastencodes ab 8, der Kernel ab 0.
            mapping[char] = (keycode - 8, required)
    return mapping


def _mask_to_keys(mask: int, modifier_names: list[str]) -> list[str] | None:
    """Modifier-Maske → Tasten, die dafür gedrückt werden müssen.

    ``None``, wenn die Ebene einen Modifier verlangt, den wir nicht
    nachstellen können (etwa CapsLock) — solche Zeichen werden lieber
    übersprungen als falsch getippt.
    """
    keys: list[str] = []
    for index, name in enumerate(modifier_names):
        if not mask & (1 << index):
            continue
        key = _XKB_MODIFIER_KEYS.get(name)
        if key is None:
            if name in ("Lock", "NumLock", "Mod2"):
                continue  # Zustandstasten — die drücken wir nicht mit
            return None
        if key not in keys:
            keys.append(key)
    return keys
