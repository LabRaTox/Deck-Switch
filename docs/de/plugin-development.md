# Eigene Plugins schreiben

*[English version](../en/plugin-development.md)* · Zurück zur [Übersicht](../../README.de.md).

Es gibt zwei Sorten: **Action-Plugins** steuern Tasten, Dials und
Touchstrip-Segmente, **Iconset-Plugins** liefern nur SVGs für den
Icon-Picker.

Plugins liegen in `~/.local/share/deckswitch/plugins/<plugin-id>/`.
Die mitgelieferten Plugins unter `backend/plugins/` sind technisch
identisch aufgebaut und taugen als Vorlage.

---

## Symbol

Ein Plugin darf ein Bild mitbringen, das es in der Übersicht vertritt:

```json
{ "icon": "icon.png" }
```

256 × 256 Pixel, PNG (auch JPEG, WebP oder SVG). Die Datei liegt im
Plugin-Ordner; Pfade nach außen weist das Backend ab. Das Symbol erscheint
ausschließlich in der Plugin-Liste, nicht bei den Aktionen.

## Action-Plugin

Minimales Beispiel — ein Plugin mit einer Aktion, die einen Zähler
hochzählt:

```
counter/
├── manifest.json
└── plugin.py
```

### manifest.json

```json
{
  "id": "counter",
  "name": { "de": "Zähler", "en": "Counter" },
  "version": "1.0.0",
  "type": "action",
  "entry": "plugin.py",
  "class": "CounterPlugin",
  "accent": "#8b5cf6",
  "actions": [
    {
      "id": "count",
      "name": { "de": "Zähler", "en": "Counter" },
      "inputs": ["key", "dial"],
      "default_icon": "number-123",
      "states": [
        { "id": "zero", "name": { "de": "Null", "en": "Zero" } },
        { "id": "counting", "name": { "de": "Zählt", "en": "Counting" } }
      ],
      "settings_schema": [
        {
          "key": "step",
          "type": "number",
          "label": { "de": "Schrittweite", "en": "Step size" },
          "default": 1,
          "min": 1,
          "max": 100
        }
      ]
    }
  ]
}
```

Das `settings_schema` ist wichtig: **die GUI baut ihr Formular allein
daraus**. Ein Plugin muss dafür nichts in der Oberfläche ergänzen.

Feldtypen: `text`, `number`, `bool`, `select`, `color`, `path`, `file`,
`hotkey` (Aufnahmefeld für Tastenkombinationen),
`password`. Bei `select` entweder feste `options` angeben oder über
`options_source` zur Laufzeit füllen lassen (siehe unten).

### plugin.py

```python
from deckswitch.plugins.base import ActionPlugin


class CounterPlugin(ActionPlugin):
    def on_key_down(self, action_id, settings, ctx):
        step = int(ctx.setting("step", 1))
        ctx.scratch["value"] = ctx.scratch.get("value", 0) + step
        # Kein request_redraw nötig: nach jeder Eingabe wird ohnehin neu
        # gezeichnet. Für Änderungen *von außen* wäre es dagegen Pflicht.

    def on_dial_rotate(self, action_id, settings, delta, ctx):
        step = int(ctx.setting("step", 1))
        ctx.scratch["value"] = ctx.scratch.get("value", 0) + delta * step

    def get_state(self, action_id, settings, ctx):
        return "zero" if ctx.scratch.get("value", 0) == 0 else "counting"

    def get_label(self, action_id, settings, ctx):
        return str(ctx.scratch.get("value", 0))
```

Das war alles. Gezeichnet wird über das gemeinsame Layout: Hintergrund,
Icon (passend zum State), Label darunter — Icon, Größen, Farben und
Hintergrund stellt der Nutzer in der GUI ein, ohne dass das Plugin etwas
dafür tun muss.

## Die Hooks

Alle sind optional, alle dürfen `def` **oder** `async def` sein. Synchrone
Hooks laufen in einem Worker-Thread — ein `subprocess.run` blockiert also
nie die Anwendung.

| Hook | Wann |
| --- | --- |
| `on_key_down(action_id, settings, ctx)` | Taste gedrückt |
| `on_key_up(action_id, settings, ctx)` | Taste losgelassen |
| `on_dial_rotate(action_id, settings, delta, ctx)` | Dial gedreht (`delta` ±) |
| `on_dial_push(action_id, settings, ctx)` | Dial gedrückt |
| `on_touch(action_id, settings, x, y, ctx)` | Touchstrip berührt (segment-relativ) |
| `on_tick(action_id, settings, ctx)` | periodisch, Standard 1×/Sekunde |
| `get_state(action_id, settings, ctx)` | welcher Zustand gilt gerade |
| `get_label(action_id, settings, ctx)` | dynamischer Text statt des konfigurierten |
| `render(action_id, settings, ctx)` | eigenes Bild zeichnen |
| `setup()` / `teardown()` | beim Laden/Beenden (Verbindungen aufbauen/schließen) |
| `on_plugin_config_changed(config)` | globale Plugin-Einstellungen geändert |
| `get_status()` | Verbindungszustand für die Plugin-Liste |
| `get_dynamic_options(source, context)` | Auswahllisten zur Laufzeit füllen |
| `gui_command(command, payload)` | Aktion, die die GUI direkt auslöst |

Eine Falle: Ein **synchroner** Hook läuft im Worker-Thread, dort gibt es
keinen Event-Loop — `asyncio.create_task` scheitert dann mit „no running
event loop“. Zwei Auswege:

* den Hook als `async def` deklarieren (dann läuft er im Loop), oder
* `self.run_async(coro)` benutzen. Der Helfer funktioniert aus jedem Thread
  und ist der richtige Weg in `render`, wo ein `async def` nicht in Frage
  kommt.

### Verbindungszustand anzeigen

Plugins, die von etwas Externem abhängen, melden ihren Zustand an die GUI —
dort erscheint er als grüner bzw. grauer Punkt in der Plugin-Liste:

```python
def get_status(self):
    if self.connected:
        return {"connected": True, "detail": f"{self.host} · {len(self.scenes)} Szenen"}
    return {"connected": False, "detail": "nicht erreichbar"}

# Bei jedem Wechsel melden (threadsicher):
self.services.runtime.publish_plugin_status(self.manifest.id)
```

Wer keine Verbindung hat, lässt `get_status` weg — dann zeigt die GUI auch
nichts an, statt eine Bedeutung vorzutäuschen.

### Der Kontext (`ctx`)

Dieselbe Aktion kann mehrfach belegt sein — etwa eine Taste je
Ausgabegerät. Der `ctx` sagt, welche Belegung gerade dran ist:

* `ctx.index`, `ctx.input_type` (`"key"`/`"dial"`), `ctx.page_id`
* `ctx.size` — Zeichenfläche: `(120, 120)` für Tasten, `(200, 100)` je Segment
* `ctx.setting(name, default)` — Einstellung mit Rückfallwert
* `ctx.scratch` — freier Zwischenspeicher, überlebt zwischen Aufrufen
* `ctx.request_redraw()` — genau diese Kachel sofort neu zeichnen
* `ctx.services` — Audio, Icons, Rendering, Runtime und die Systemdienste
* `ctx.deck_serial` — auf welchem Deck die Belegung liegt
* `ctx.frame_time` — Laufzeit in Sekunden; animierte Bilder wählen daraus
  ihr Einzelbild

**Bei mehreren Decks wichtig:** `ctx.services.runtime` zeigt auf *das Deck,
auf dem gedrückt wurde*. Wer über `self.services.runtime` navigiert, landet
dagegen beim Hauptdeck — das ist bei einem einzelnen Gerät dasselbe, bei
zweien aber falsch. Faustregel: Alles, was mit einer Belegung zu tun hat,
über `ctx.services.runtime`; alles Übrige (Fehler melden, Config speichern)
darf über `self.services.runtime` gehen.

## Zustände von außen

Ändert sich etwas ohne Zutun des Nutzers, soll die Anzeige nicht bis zum
nächsten Tick warten. Dafür ist `request_redraw` da — und es ist
threadsicher, darf also aus einem Watcher-Thread heraus gerufen werden:

```python
async def setup(self):
    self.services.audio.add_listener(self._on_change)

def _on_change(self, event, facility):
    self.services.runtime.request_redraw()   # alles neu zeichnen
```

`ctx.request_redraw()` zeichnet nur die eine Kachel neu und ist deshalb
vorzuziehen, wenn klar ist, welche betroffen ist.

## Auswahllisten zur Laufzeit

Wenn die Optionen erst beim Betrieb feststehen (Audio-Geräte, OBS-Szenen),
im Manifest `options_source` setzen und im Plugin auflösen:

```json
{ "key": "sink", "type": "select", "options_source": "sinks" }
```

```python
def get_dynamic_options(self, source, context=None):
    if source == "sinks":
        return [{"value": s.name, "label": s.description}
                for s in self.services.audio.list_sinks()]
    return []
```

Hängt eine Liste von einem anderen Feld ab — die Filter *einer* Quelle, die
Quellen *einer* Szene —, wird das im Manifest deklariert:

```json
{
  "key": "filter",
  "type": "select",
  "options_source": "filters",
  "options_depend_on": ["source"]
}
```

Die bereits gesetzten Einstellungen kommen dann als ``context`` an, und die
GUI lädt die Liste neu, sobald sich das übergeordnete Feld ändert.

## Selbst zeichnen

Nur nötig, wenn das Standard-Layout nicht reicht — etwa für einen
Pegelbalken:

```python
def render(self, action_id, settings, ctx):
    render = self.services.render
    image = render.background(ctx.size, ctx.appearance, accent="#8b5cf6")
    render.draw_bar(image, 0.6, color="#8b5cf6")
    render.draw_text_at(image, "60%", x=ctx.size[0] - 12, y=8, align="right")
    return image
```

Bausteine im Render-Service: `background`, `compose` (Icon + Label wie im
Standard), `draw_bar`, `draw_text`, `draw_text_at`, `draw_badge`,
`blank`, `empty_slot`.

Wichtig: **den Hintergrund aus `ctx.appearance` nehmen**, nicht hart
schwarz füllen — sonst ignoriert das Plugin die Einstellungen des Nutzers.

## Services

* `services.audio` — PipeWire: `get_volume`, `set_volume`, `change_volume`,
  `toggle_mute`, `list_sinks`, `list_sources`, `switch_output`,
  `list_streams`, `add_listener`
* `services.icons` — `resolve(icon_ref, size=…)`, `list_icons`
* `services.render` — siehe oben
* `services.runtime` — `request_redraw`, `navigate`, `navigate_home`,
  `navigate_back`, `page_number`, `step_page`, `notify`, `save_config`;
  über `ctx` zusätzlich `device_settings` (Helligkeit & Co. dieses Decks),
  `cycle_stack` und die Ketten-Steuerung `run_steps` / `stop_steps` /
  `steps_running`
* `services.input` — virtuelle Tastatur: `send_combo("ctrl+shift+f5")`,
  `hold_combo(combo, pressed)` für Push-to-Talk, `type_text(text)`,
  `available()`. Die Zuordnung Zeichen → Taste kommt aus der aktiven
  Tastaturbelegung, nicht aus einer Annahme.
* `services.media` — der gerade laufende Player über MPRIS:
  `control("play_pause"|"next"|…)`, `refresh()`, `list_players()`,
  `state` (spielt, Titel, Interpret)
* `services.desktop` — Sitzung und Fenster: `power("lock"|"suspend"|…)`,
  `invoke_shortcut(component, name)` für KDEs globale Kurzbefehle,
  `list_shortcuts(component)`, `screenshot(mode)`, `close_application()`
* `services.sound` — Soundboard: `play(pfad, owner=ctx.key, sink=…)`,
  `toggle`, `stop`, `stop_all`, `is_playing(ctx.key)`
* `services.config` — die gesamte Konfiguration (lesend)
* `self.plugin_config` — die globalen Einstellungen dieses Plugins

## Globale Plugin-Einstellungen

Alles, was nicht zu einer einzelnen Belegung gehört (Serveradresse,
Zugangsdaten), gehört ins `config_schema` des Manifests. Die GUI zeigt es
unter *Plugins → \<Plugin\> → Plugin-Einstellungen*, das Plugin liest es
über `self.plugin_config`.

## Fehler melden

`self.notify_error("…")` schreibt ins Log **und** in die Fehleranzeige der
GUI. Wirft ein Hook eine Ausnahme, fängt die Runtime sie ab, zeigt eine
rote Fehlerkachel auf dem Gerät und listet den Fehler in der Oberfläche —
ein kaputtes Plugin legt also nie die ganze Anwendung lahm.

## Drehrichtungen

Ein Dial kann je Drehrichtung eine eigene Action tragen. Ist eine belegt,
bekommt sie die Drehung **wie einen kurzen Tastendruck** — also
`on_key_down` und `on_key_up`, nicht `on_dial_rotate`. Eine Action, die nur
`on_dial_rotate` beantwortet, taugt damit nicht als Richtungsbelegung; wer
beides anbieten will, beantwortet beide Hooks.

Umgekehrt gilt: Solange keine Richtung belegt ist, ändert sich nichts —
`on_dial_rotate` bekommt weiter jedes Delta.

## Was Plugins über Multi-Aktionen wissen müssen

Eine Multi-Aktion ruft ganz normale Actions auf — genau so, wie es ein
Tastendruck täte: erst `on_key_down`, dann `on_key_up`. Ein Plugin muss
dafür nichts vorbereiten. Zwei Dinge sind trotzdem gut zu wissen:

* Jeder Schritt bekommt einen **eigenen `ctx.scratch`**. Eine Aktion, die
  ihren Zustand dort führt (etwa ein Umschalter), zählt also je Schritt
  getrennt.
* Eine Kette läuft als eigene Aufgabe und kann **jederzeit abgebrochen**
  werden. Wer in einem Hook etwas startet, das aufgeräumt werden muss,
  sollte das nicht auf einen späteren Hook-Aufruf verschieben.

## Kein Symbol

`IconRef(kind="none")` heißt ausdrücklich „hier soll kein Symbol stehen" —
auch nicht das `default_icon` aus dem Manifest. Das braucht, wer ein fertig
gestaltetes Tastenbild als Hintergrund setzt; Symbol und Text stecken dann
schon darin.

## Iconset-Plugin

Nur ein Manifest und ein Ordner mit SVGs:

```json
{
  "id": "iconset-meins",
  "name": "Meine Icons",
  "version": "1.0.0",
  "type": "iconset",
  "license": "CC-BY-4.0",
  "icons_dir": "icons"
}
```

Der Dateiname ohne Endung ist der Icon-Name. SVGs, die mit
`stroke="currentColor"` bzw. `fill="currentColor"` arbeiten, lassen sich
in der GUI einfärben; alle anderen werden über ihre Alpha-Maske getönt.

## Ausprobieren

```fish
./scripts/start-backend.sh --verbose
```

In der GUI *Plugins → Plugins neu laden*. Weil Python bereits importierte
Module zwischenspeichert, ist nach Codeänderungen ein Neustart des
Backends allerdings der verlässlichere Weg.
