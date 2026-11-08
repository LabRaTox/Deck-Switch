# Eigene Plugins schreiben

*[English version](../en/plugin-development.md)* · Zurück zur [Übersicht](../../README.de.md).

Es gibt vier Sorten, welche ein Plugin ist, sagt das Manifest-Feld `type`.
**Action-Plugins** (`action`) steuern Tasten, Dials und
Touchstrip-Segmente. **Iconset-Plugins** (`iconset`) liefern nur SVGs für
den Icon-Picker. **Schoner-Plugins** (`screensaver`) malen über das ganze
Deck, solange der Bildschirmschoner läuft, **Hintergrund-Plugins**
(`wallpaper`) malen den Grund des Touchstrips. Die letzten beiden tauchen
nicht in der Aktionsbibliothek auf, man wählt sie in den Einstellungen.

Plugins liegen in `~/.local/share/deckswitch/plugins/`. Jeder Ordner dort
trägt eine laufende Nummer, welches Plugin darin steckt, steht in seiner
`manifest.json`. Die mitgelieferten Plugins unter `backend/plugins/` sind
technisch identisch aufgebaut und taugen gut als Vorlage.

---

## Symbol

Ein Plugin darf ein Bild mitbringen, das es in der Übersicht vertritt:

```json
{ "icon": "icon.png" }
```

256 × 256 Pixel, PNG (auch JPEG, WebP oder SVG). Die Datei liegt im
Plugin-Ordner, und Pfade nach außen weist das Backend ab. Das Symbol
erscheint nur in der Plugin-Liste und nicht bei den Aktionen.

Dazu kannst du bis zu drei Bilder für die Detailansicht angeben:

```json
{ "screenshots": ["screenshots/deck.png", "screenshots/aktionen.png"] }
```

Bildschirmfotos müssen PNG, JPEG oder WebP sein, SVG geht hier nicht. Mit
mehr als drei Einträgen ist das Manifest ungültig, und das Plugin lädt
nicht.

## Action-Plugin

Ein minimales Beispiel: ein Plugin mit einer Aktion, die einen Zähler
hochzählt.

```
my-counter/
├── manifest.json
└── plugin.py
```

### manifest.json

```json
{
  "id": "my-counter",
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

Das `settings_schema` ist wichtig, denn **die GUI baut ihr Formular allein
daraus**. Ein Plugin muss dafür nichts in der Oberfläche ergänzen.

Feldtypen: `text`, `number`, `bool`, `select`, `color`, `path`, `file`,
`hotkey` (Aufnahmefeld für Tastenkombinationen),
`password`. Bei `select` entweder feste `options` angeben oder über
`options_source` zur Laufzeit füllen lassen (siehe unten).

Ein Feld kann mehr tragen als Schlüssel, Typ, Beschriftung und Vorgabe.
`placeholder` zeigt einen Hinweis im leeren Eingabefeld, `help` eine
Erklärung zum Feld. Beide dürfen wie `label` zweisprachig sein. `min`,
`max` und `step` begrenzen ein `number`-Feld. `depends_on` zeigt das Feld
nur, wenn andere Felder einen bestimmten Wert haben, eine Liste heißt dort
einer von mehreren Werten:

```json
{
  "key": "interface",
  "type": "select",
  "options_source": "interfaces",
  "depends_on": { "metric": ["net_down", "net_up"] }
}
```

### Weitere Manifest-Felder

Diese Felder gelten für jeden Typ:

| Feld | Bedeutung |
| --- | --- |
| `description` | volle Beschreibung in der Detailansicht, gern zweisprachig |
| `summary` | ein Satz für die Plugin-Liste. Fehlt er, zeigt die Liste die Beschreibung auf zwei Zeilen gekürzt |
| `author` | wer das Plugin geschrieben hat |
| `category` | wohin das Plugin in der Übersicht gehört, Vorgabe `other` |
| `support` | Adresse für Fragen und Fehlerberichte, steht unter *Hilfe* |
| `changelog` | was sich zuletzt geändert hat, steht unter *Was ist neu* |
| `license` | Lizenzhinweis, steht in der Detailansicht |
| `accent` | Farbe des Plugins in der Aktionsbibliothek und der Plugin-Liste |

Erlaubte Werte für `category`: `system`, `audio`, `business`, `creative`,
`development`, `engagement`, `finance`, `gaming`, `lighting`, `monitoring`,
`music`, `productivity`, `screensaver`, `smarthome`, `social`, `streaming`,
`utilities`, `video`, `other`. Jeder andere Wert macht das Manifest
ungültig, und das Plugin lädt nicht.

Eine Aktion kennt neben `id`, `name`, `inputs`, `default_icon`, `states`
und `settings_schema` diese Felder:

* `description` steht bei der Aktion in der Bibliothek.
* `default_label` wird als Beschriftung eingetragen, wenn die Aktion auf
  eine Taste gezogen wird.
* `states[].default_icon` ist das Icon für einen Zustand, solange der
  Nutzer keines gewählt hat. Fehlt es, gilt das `default_icon` der Aktion.
* `requires` nennt, was die Sitzung können muss, damit die Aktion etwas
  bewirkt. Fehlt davon etwas, taucht die Aktion in der Bibliothek nicht
  auf, und eine Taste, die sie schon trägt, zeigt den Grund. Unbekannte
  Namen gelten als vorhanden. Die Namen sind `keyboard_input`,
  `window_control`, `global_shortcuts`, `screenshot`, `screen_power`,
  `session_power`, `session_manager`, `overlay`, `ddc`, `audio`,
  `sound_playback`, `tray`, `open_uri` und `process_control`. Auch ein
  Eintrag in den `options` eines Feldes kann `requires` tragen, die GUI
  markiert dann nur diesen Eintrag.

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
Icon passend zum State, Label darunter. Icon, Größen, Farben und Hintergrund
stellt der Nutzer in der GUI ein, dafür muss das Plugin nichts tun.

## Die Hooks

Alle sind optional. Nicht jeder Hook darf `async def` sein, die rechte
Spalte sagt, welche Form die App erwartet.

| Hook | Wann | Form |
| --- | --- | --- |
| `on_key_down(action_id, settings, ctx)` | Taste gedrückt | `def` oder `async def` |
| `on_key_up(action_id, settings, ctx)` | Taste losgelassen | `def` oder `async def` |
| `on_dial_rotate(action_id, settings, delta, ctx)` | Dial gedreht (`delta` ±) | `def` oder `async def` |
| `on_dial_push(action_id, settings, ctx)` | Dial gedrückt | `def` oder `async def` |
| `on_touch(action_id, settings, x, y, ctx)` | Touchstrip berührt (segment-relativ) | `def` oder `async def` |
| `on_tick(action_id, settings, ctx)` | periodisch, Standard 1×/Sekunde | `def` oder `async def` |
| `render(action_id, settings, ctx)` | eigenes Bild zeichnen | `def` oder `async def` |
| `get_dynamic_options(source, context)` | Auswahllisten zur Laufzeit füllen | `def` oder `async def` |
| `get_state(action_id, settings, ctx)` | welcher Zustand gilt gerade | `def` |
| `get_label(action_id, settings, ctx)` | dynamischer Text statt des konfigurierten | `def` |
| `get_status()` | Verbindungszustand für die Plugin-Liste | `def` |
| `on_plugin_config_changed(config)` | globale Plugin-Einstellungen geändert | `def` |
| `setup()` / `teardown()` | beim Laden/Beenden (Verbindungen aufbauen/schließen) | `async def` |
| `gui_command(command, payload)` | Aktion, die die GUI direkt auslöst | `async def` |

Hooks mit `def` oder `async def` laufen in einem Worker-Thread, wenn sie
synchron sind. Ein `subprocess.run` blockiert also nie die Anwendung. Als `async def`
laufen sie im Event-Loop und dürfen ihn nicht blockieren.

Die reinen `def`-Hooks ruft die App direkt auf und wartet nicht auf sie.
Sie sollen sofort antworten, aus dem Zustand, den das Plugin schon kennt.
`get_state` und `get_label` ruft das Standard-`render` auf. Wer `render`
überschreibt, entscheidet selbst, ob und wie er sie benutzt.

`setup()`, `teardown()` und `gui_command()` werden erwartet (`await`). Ein
einfaches `def` scheitert dort.

Eine Falle: Ein **synchroner** Hook läuft im Worker-Thread, und dort gibt
es keinen Event-Loop. `asyncio.create_task` scheitert dann mit „no running
event loop". Zwei Auswege:

* den Hook als `async def` deklarieren, wo die Tabelle das erlaubt (dann
  läuft er im Loop), oder
* `self.run_async(coro)` benutzen. Der Helfer funktioniert aus jedem
  Thread, auch aus eigenen Watcher-Threads und aus den reinen
  `def`-Hooks.

### Verbindungszustand anzeigen

Plugins, die von etwas Externem abhängen, melden ihren Zustand an die GUI.
Dort erscheint er als grüner oder grauer Punkt in der Plugin-Liste:

```python
def get_status(self):
    if self.connected:
        return {"connected": True, "detail": f"{self.host} · {len(self.scenes)} Szenen"}
    return {"connected": False, "detail": "nicht erreichbar"}

# Bei jedem Wechsel melden (threadsicher):
self.services.runtime.publish_plugin_status(self.manifest.id)
```

Wer keine Verbindung hat, lässt `get_status` einfach weg. Dann zeigt die
GUI dort auch nichts an.

### Der Kontext (`ctx`)

Dieselbe Aktion kann mehrfach belegt sein, zum Beispiel eine Taste je
Ausgabegerät. Der `ctx` sagt, welche Belegung gerade dran ist:

* `ctx.index`, `ctx.input_type` (`"key"`/`"dial"`), `ctx.page_id`,
  `ctx.profile_id`
* `ctx.key` ist ein fester Name für die Belegung (Seite, Eingabeart,
  Index), etwa als `owner` für das Soundboard
* `ctx.size` ist die Zeichenfläche: auf einem Stream Deck + `(120, 120)`
  für Tasten und `(200, 100)` je Segment. Virtuelle Decks können andere
  Größen haben
* `ctx.setting(name, default)` holt eine Einstellung mit Rückfallwert
* `ctx.slot` ist die ganze Belegung, `ctx.appearance` ihr Aussehen
  (Hintergrund, Icon, Beschriftung)
* `ctx.is_long_press` ist `True`, wenn der Halten-Zweig einer Taste
  auslöst
* `ctx.scratch` ist freier Zwischenspeicher und überlebt zwischen Aufrufen
* `ctx.request_redraw()` zeichnet genau diese Kachel sofort neu
* `ctx.services` sind Audio, Icons, Rendering, Runtime und die Systemdienste
* `ctx.deck_serial` sagt, auf welchem Deck die Belegung liegt
* `ctx.frame_time` ist die Laufzeit in Sekunden, animierte Bilder wählen
  daraus ihr Einzelbild

Drücken, Doppeldruck und Halten einer Taste sind getrennte Belegungen, und
jede bekommt ihren eigenen `ctx.scratch`. Was der Druck-Zweig dort ablegt,
sieht der Halten-Zweig nicht.

**Bei mehreren Decks wichtig:** `ctx.services.runtime` zeigt auf *das Deck,
auf dem gedrückt wurde*. Wer über `self.services.runtime` navigiert, landet
beim Hauptdeck. Bei einem einzelnen Gerät ist das dasselbe, bei zweien ist es
falsch. Faustregel: Alles, was mit einer Belegung zu tun hat, geht über
`ctx.services.runtime`. Der Rest, also Fehler melden und Config speichern,
darf über `self.services.runtime` gehen.

## Zustände von außen

Ändert sich etwas ohne Zutun des Nutzers, soll die Anzeige nicht bis zum
nächsten Tick warten. Dafür ist `request_redraw` da. Es ist threadsicher und
darf auch aus einem Watcher-Thread gerufen werden:

```python
async def setup(self):
    self.services.audio.add_listener(self._on_change)

def _on_change(self, event, facility):
    self.services.runtime.request_redraw()   # alles neu zeichnen
```

`ctx.request_redraw()` zeichnet nur die eine Kachel neu. Nimm das, wenn du
weißt, welche betroffen ist.

## Auswahllisten zur Laufzeit

Wenn die Optionen erst im Betrieb feststehen, etwa Audio-Geräte oder
OBS-Szenen, setzt du im Manifest `options_source` und löst es im Plugin auf:

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

Hängt eine Liste von einem anderen Feld ab, etwa die Filter *einer* Quelle
oder die Quellen *einer* Szene, deklarierst du das im Manifest:

```json
{
  "key": "filter",
  "type": "select",
  "options_source": "filters",
  "options_depend_on": ["source"]
}
```

Die bereits gesetzten Einstellungen kommen dann als `context` an, und die
GUI lädt die Liste neu, sobald sich das übergeordnete Feld ändert.

## Selbst zeichnen

Das brauchst du nur, wenn das Standard-Layout nicht reicht, zum Beispiel
für einen Pegelbalken:

```python
def render(self, action_id, settings, ctx):
    render = self.services.render
    image = render.background(ctx.size, ctx.appearance, accent="#8b5cf6")
    render.draw_bar(image, 0.6, color="#8b5cf6")
    render.draw_text_at(image, "60%", x=ctx.size[0] - 12, y=8, align="right")
    return image
```

Bausteine im Render-Service: `background`, `compose` (Icon + Label wie im
Standard), `bar_box`, `draw_bar`, `draw_meter` (Aussteuerungsanzeige von
-60 bis 0 dBFS), `draw_text`, `draw_text_at`, `draw_badge`, `blank`,
`empty_slot`, `error_slot`.

Oft passt das Standard-Layout fast und braucht nur eine Ergänzung. Dann
zeichnet `render_slot(ctx, state=…, label_override=…, accent=…,
icon_override=…, reserve_bottom=…)` es, und du malst darüber.
`icon_override` setzt ein fertiges Bild an die Stelle des Icons (ein Cover,
ein Serverlogo), `icon_px(ctx.size, ctx.appearance.icon_size)` liefert die
passende Kantenlänge. `reserve_bottom` hält unten Platz frei, damit die
Beschriftung nicht unter einem Balken liegt, `bar_reserve(ctx.size, box)`
rechnet diesen Platz für einen Balken in `box` aus:

```python
def render(self, action_id, settings, ctx):
    render = self.services.render
    box = render.bar_box(ctx.size)
    image = render.render_slot(
        ctx,
        state=self.get_state(action_id, settings, ctx),
        reserve_bottom=render.bar_reserve(ctx.size, box),
    )
    render.draw_bar(image, 0.6, box=box)
    return image
```

Wichtig: **Nimm den Hintergrund aus `ctx.appearance`** und füll nicht hart
schwarz. Sonst ignoriert das Plugin die Einstellungen des Nutzers.

## Services

* `services.audio` (PipeWire): `get_volume`, `set_volume`, `change_volume`,
  `toggle_mute`, `set_mute`, `list_sinks`, `list_sources`,
  `get_default_sink`, `get_default_source`, `switch_output`,
  `list_streams`, `move_stream`, `add_listener`. Einzelne
  Anwendungs-Streams über ihren Index: `set_stream_volume`,
  `change_stream_volume`, `toggle_stream_mute`
* `services.icons`: `resolve(icon_ref, size=…)`, `list_icons(set_id)`
  (Namen in einem Iconset), `system_iconset` (ID des eingebauten Sets)
* `services.render`: siehe oben
* `services.runtime`: `request_redraw`, `navigate`, `navigate_home`,
  `navigate_back`, `current_page_id`, `page_number`, `sibling_pages`,
  `step_page`, `notify`, `save_config`, `publish_plugin_status`; über
  `ctx` zusätzlich `switch_profile(name)` (leerer Name geht zum vorigen
  Profil zurück), `device_settings` (Helligkeit & Co. dieses Decks),
  `cycle_stack` und die Ketten-Steuerung `run_steps` / `stop_steps` /
  `steps_running`
* `services.input` ist die virtuelle Tastatur:
  `send_combo("ctrl+shift+f5")`, `hold_combo(combo, pressed)` für
  Push-to-Talk, `type_text(text)`, `available()`. Die Zuordnung
  Zeichen → Taste kommt aus der aktiven Tastaturbelegung, nicht aus einer
  Annahme.
* `services.media` ist der gerade laufende Player über MPRIS:
  `await control("play_pause"|"next"|…)`, `await refresh()`,
  `await list_players()`, `state` (spielt, Titel, Interpret)
* `services.desktop` deckt Sitzung und Fenster ab: `await
  power("lock"|"suspend"|…)`, `await invoke_shortcut(component, name)` für
  globale Kurzbefehle, `await list_components()`, `await
  list_shortcuts(component)`, `screenshot(mode)`,
  `close_application(pattern, force=False)` (liefert, wie viele Prozesse
  beendet wurden)
* `services.sound` ist das Soundboard: `play(pfad, owner=ctx.key, sink=…)`,
  `toggle`, `stop`, `stop_all`, `is_playing(ctx.key)`, `available()`
* `services.overlay` zeigt das Overlay eines virtuellen Decks:
  `is_visible(deck)`, `await toggle(deck)`, `await show(deck)`,
  `hide(deck)`. `deck` ist die Kennung des Decks wie in `ctx.deck_serial`
* `services.config` ist die gesamte Konfiguration (lesend)
* `services.plugin_dir` ist der eigene Ordner des Plugins, für
  mitgelieferte Dateien
* `self.plugin_config` enthält die globalen Einstellungen dieses Plugins

Aufrufe mit `await` sind Coroutinen. Aus einem synchronen Hook startest du
sie mit `self.run_async(…)`. `available()` von Input und Sound liefert ein
Paar `(ok, grund)`, der Grund ist Text für die GUI.

## Globale Plugin-Einstellungen

Alles, was nicht zu einer einzelnen Belegung gehört (Serveradresse,
Zugangsdaten), gehört ins `config_schema` des Manifests. Die GUI zeigt es
unter *Plugins → \<Plugin\> → Plugin-Einstellungen*, das Plugin liest es
über `self.plugin_config`.

## Fehler melden

`self.notify_error("…")` schreibt ins Log **und** in die Fehleranzeige der
GUI. `self.notify_info("…")` ist für erwartbare Zustände gedacht, einen
Dienst, der gerade nicht läuft, oder einen fehlenden Player. Es geht nur
ins Log, die GUI zeigt es nicht an.

Wirft ein Hook eine Ausnahme, fängt die Runtime sie ab und listet den
Fehler in der Oberfläche. Eine rote Fehlerkachel auf dem Gerät gibt es nur
bei einem scheiternden `render`, und dazu zählen `get_state` und
`get_label`, die darin aufgerufen werden. Dieselbe Kachel erscheint, wenn
`render` etwas anderes als ein Bild zurückgibt. Scheitert ein
Eingabe-Hook, `on_tick` oder `on_plugin_config_changed`, wird der Fehler
erfasst und die Kachel ganz normal neu gezeichnet. Ein kaputtes Plugin legt
also nie die ganze Anwendung lahm.

## Texte übersetzen

Alles, was ein Mensch zu sehen bekommt, gehört in Sprachdateien im
Plugin-Ordner: Fehlermeldungen, Statuszeilen, Bedienhinweise, Texte auf
Tasten und im Touchstrip. Das Manifest ist schon zweisprachig, das gilt
für alles andere.

```
my-counter/
  locales/
    de.json
    en.json
```

```json
// locales/de.json
{ "nicht_erreichbar": "{dienst} ist nicht erreichbar", "zaehler": "Zähler" }

// locales/en.json
{ "nicht_erreichbar": "{dienst} is not reachable", "zaehler": "Counter" }
```

Im Code steht nur der Schlüssel:

```python
self.notify_error(self.t("nicht_erreichbar", dienst="OBS"))
```

`self.t()` nimmt die Sprache, die in der App eingestellt ist. Fehlt ein
Text, kommt der englische, dann der deutsche, zuletzt der Schlüssel
selbst. Hilfsmodule ohne `self` benutzen `plugin_text` aus
`deckswitch.plugins.base` mit dem eigenen Ordner und der Plugin-ID.

Log-Zeilen bleiben unübersetzt, sie stehen nur im Journal.

## Drehrichtungen

Ein Dial kann je Drehrichtung eine eigene Action tragen. Ist eine belegt,
bekommt sie die Drehung **wie einen kurzen Tastendruck**, also `on_key_down`
und `on_key_up` und nicht `on_dial_rotate`. Eine Action, die nur
`on_dial_rotate` beantwortet, taugt damit nicht als Richtungsbelegung. Wer
beides anbieten will, beantwortet beide Hooks.

Solange keine Richtung belegt ist, ändert sich nichts: `on_dial_rotate`
bekommt weiter jedes Delta.

## Was Plugins über Multi-Aktionen wissen müssen

Eine Multi-Aktion ruft ganz normale Actions auf, genau so wie es ein
Tastendruck täte: erst `on_key_down`, dann `on_key_up`. Ein Plugin muss dafür
nichts vorbereiten. Zwei Dinge sind trotzdem gut zu wissen:

* Jeder Schritt bekommt einen **eigenen `ctx.scratch`**. Eine Aktion, die
  ihren Zustand dort führt (etwa ein Umschalter), zählt also je Schritt
  getrennt.
* Eine Kette läuft als eigene Aufgabe und kann **jederzeit abgebrochen**
  werden. Wer in einem Hook etwas startet, das aufgeräumt werden muss,
  sollte das nicht auf einen späteren Hook-Aufruf verschieben.

## Kein Symbol

`IconRef(kind="none")` heißt ausdrücklich „hier soll kein Symbol stehen",
auch nicht das `default_icon` aus dem Manifest. Das brauchst du, wenn du ein
fertig gestaltetes Tastenbild als Hintergrund setzt. Symbol und Text stecken
dann schon darin.

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
`stroke="currentColor"` oder `fill="currentColor"` arbeiten, lassen sich in
der GUI einfärben. Alle anderen tönt die App über ihre Alpha-Maske.

## Schoner- und Hintergrund-Plugins

Beide bekommen eine Leinwand statt einer Taste. Die Klasse erbt von
`ScreensaverPlugin` oder `WallpaperPlugin` aus `deckswitch.plugins.base`.
Beide Namen stehen für dieselbe Basisklasse `CanvasPlugin`, und der Loader
weist bei diesen Typen eine Klasse ab, die nicht von ihr erbt. `entry` und
`class` sind wie beim Action-Plugin Pflicht.

```python
import time

from PIL import Image

from deckswitch.plugins.base import ScreensaverPlugin


class SimpleClock(ScreensaverPlugin):
    interval_s = 30.0

    def render(self, size, elapsed_s):
        image = Image.new("RGBA", size, (0, 0, 0, 255))
        height = size[1] // 4
        self.services.render.draw_text(
            image, time.strftime("%H:%M"), y=(size[1] - height) // 2, size=height
        )
        return image
```

`render(size, elapsed_s)` liefert ein Bild der Größe `size`. Die App
zerlegt es selbst auf Tasten und Touchstrip. `elapsed_s` zählt die
Sekunden, seit der Schoner läuft. `render` wird synchron aufgerufen, ist
also ein einfaches `def`.

* `interval_s` ist der Abstand zwischen zwei Bildern in Sekunden. `0`
  zeichnet einmal und lässt das Bild stehen.
* Liefert ein Schoner `None`, bleibt das vorige Bild stehen.
* `self.deck_layout` sagt, wo die Kacheln auf der Leinwand liegen:
  `deck_layout.keys` ist eine Liste aus `(x, y, w, h)` je Taste in
  Lesereihenfolge, `deck_layout.strip` das Rechteck des Touchstrips. Wer
  etwas pro Taste zeigen will, braucht das, sonst landet der Inhalt in den
  Fugen zwischen den Tasten.
* Ein Hintergrund-Plugin bekommt nur den Streifen als Leinwand,
  `deck_layout` bleibt dort `None`. Die App zeichnet es mit `elapsed_s` 0
  und wiederholt es nicht nach `interval_s`. Ein Hintergrund muss ein Bild
  liefern.

`setup()`, `teardown()`, `on_plugin_config_changed()`, `self.t()` und
`self.plugin_config` funktionieren wie beim Action-Plugin.

## Verpacken und installieren

Die ID darf Kleinbuchstaben, Ziffern, Punkt, Unterstrich und Bindestrich
enthalten, beginnt mit einem Buchstaben oder einer Ziffer und ist höchstens
64 Zeichen lang (`^[a-z0-9][a-z0-9._-]{0,63}$`). IDs der mitgelieferten
Plugins sind vergeben. Alle Typen außer `iconset` brauchen `entry` und
`class`.

Lokal installiert die App nur ZIP-Archive. Die `manifest.json` liegt in der
Wurzel des Archivs, in einem einzelnen Ordner oder eine Ebene tiefer. Ein
Archiv enthält genau ein Plugin. Es darf höchstens 64 MB groß sein und
entpackt höchstens 256 MB. Mehr als 20.000 Einträge nimmt die App nicht an.
Symbolische Links, Pfade mit `..` und Backslashes in Namen werden
abgewiesen.

Wie man installiert, steht unter [Plugins](plugins.md#nachinstallieren),
die Links für den Browser unter
[streamdeck://-Links](plugins.md#streamdeck-links).

### Mindestversion der App

Braucht dein Plugin ein neueres DECK//SWITCH, trägst du diese Version als
Text ins Manifest ein:

```json
{ "min_app_version": "1.4.0" }
```

Das Feld ist freiwillig. Ist die laufende App älter, verweigert sie die
Installation, aus einem ZIP ebenso wie von einer Adresse oder aus dem
Store, und die Meldung nennt die nötige Version. In der Plugin-Liste bleibt
der Knopf eines solchen Updates gesperrt und zeigt den Hinweis „Braucht
DECK//SWITCH {version} oder neuer“.

Ein Plugin, das `self.t()` benutzt, braucht mindestens `"1.4.0"`.

## Ausprobieren

```sh
./scripts/start-backend.sh --verbose
```

In der GUI dann *Plugins → Nach neuen Plugins sehen*. Der Knopf lädt nur
Plugins, die neu sind, verschwunden sind oder im Manifest eine andere
`version` tragen. Eine Codeänderung ohne neue Versionsnummer kommt so nicht
an, deshalb nach Codeänderungen das Backend neu starten.

## Abhängigkeiten

Jedes Plugin kann Pakete nennen, die es braucht. Sie stehen im Manifest, den
Rest macht der Installer.

```json
"dependencies": {
  "python": ["icalendar>=6.0"],
  "system": ["ffmpeg", {"arch": "python-gobject", "debian": "python3-gi", "fedora": "python3-gobject", "suse": "python3-gobject"}]
}
```

* **`python`** nennt Pakete von PyPI, in der üblichen Schreibweise mit
  Version. Direkte Adressen werden abgelehnt. Besondere Rechte sind nicht
  nötig: `uv` legt fertige Wheels nach `<plugins>/.deps/<id>/`, ein Paket ohne
  Wheel geht also nicht. Der Ordner kommt beim Laden ans Ende von `sys.path`.
  Ein Plugin kann damit Pakete ergänzen, aber keines des Backends ersetzen,
  und der Ordner verschwindet mit dem Plugin. Verlangen zwei Plugins
  verschiedene Versionen eines Pakets, teilen sie sich die zuerst geladene.
* **`system`** nennt Pakete der Distribution. Ein einfacher Name gilt überall.
  Wo die Namen abweichen, nennt ein Objekt einen je Familie: `arch`, `debian`
  (auch Ubuntu), `fedora` und `suse` (openSUSE). Fehlt der Name für eine Familie, stoppt dort die
  Installation. Fehlt ein Paket, fragt `pkexec` nach dem Passwort, und pacman,
  apt, dnf oder zypper installieren es. Auf einem Fedora mit Image wie Bazzite nennt
  die Meldung stattdessen den `rpm-ostree`-Befehl. Ohne einen dieser
  Paketmanager wird jeder Name als Programm gesucht.

**Die Installation stoppt, bis alles da ist.** Lässt sich etwas nicht
installieren, wird das Plugin nicht installiert, eine ältere Fassung bleibt
liegen, und der Fehler nennt den Befehl für die Hand.

Nenne nur Pakete, denen du traust, mit einer unteren Versionsgrenze.

## Einreichen

Ist das Plugin fertig, kannst du es über *Plugins → Plugin einreichen* in den
Store geben. Dafür musst du im Store angemeldet sein. Zieh ein Archiv in das
Feld, ZIP, TAR, tar.gz und tgz gehen alle.

Der Store sieht sich den Python-Quelltext an und notiert, was auffällt:
Adressen, Netzbibliotheken, Programmaufrufe, zur Laufzeit erzeugter Code.
Diese Funde bekommt später jeder zu sehen, der dein Plugin installieren will.
Wenn dein Plugin ins Netz greift, schreib in die Beschreibung wozu.
