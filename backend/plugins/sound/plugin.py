"""Soundboard — Klänge auf Tasten.

Der eigentliche Abspieler steckt in ``services/sound.py``; hier steht nur,
welche Taste welchen Klang startet und wie sie dabei aussieht.

Eine Besonderheit gegenüber „einfach abspielen": Jede Belegung darf ihr
**eigenes Ausgabegerät** wählen. Genau dafür ist ein Soundboard beim
Streamen da — der Jingle soll in die Sendung, nicht unbedingt in die eigenen
Kopfhörer. PipeWire kann das pro Wiedergabe, ohne an der Systemlautstärke zu
drehen.
"""

from __future__ import annotations

from deckswitch.plugins.base import ActionPlugin


class SoundPlugin(ActionPlugin):
    def on_key_down(self, action_id, settings, ctx):
        self._activate(action_id, settings, ctx)

    def on_dial_push(self, action_id, settings, ctx):
        self._activate(action_id, settings, ctx)

    def _activate(self, action_id, settings, ctx) -> None:
        sound = self.services.sound
        try:
            if action_id == "stop_all":
                stopped = sound.stop_all()
                self.notify_info(f"{stopped} Klang/Klänge angehalten")
                self.services.runtime.request_redraw()
                return

            path = (settings.get("path") or "").strip()
            if not path:
                raise ValueError("Keine Audiodatei eingestellt")

            options = {
                "sink": (settings.get("sink") or "").strip(),
                "volume": int(settings.get("volume") or 100),
                "loop": bool(settings.get("loop")),
            }
            if settings.get("mode") == "toggle":
                sound.toggle(path, owner=ctx.key, **options)
            else:
                sound.play(path, owner=ctx.key, **options)
        except Exception as exc:
            self.notify_error(f"{action_id}: {exc}")
        ctx.request_redraw()

    # -- Darstellung -------------------------------------------------------

    def get_state(self, action_id, settings, ctx):
        if action_id != "play":
            return None
        return "playing" if self.services.sound.is_playing(ctx.key) else "default"

    def get_label(self, action_id, settings, ctx):
        if ctx.appearance.label_text or action_id != "play":
            return None
        path = (settings.get("path") or "").strip()
        if not path:
            return None
        # Ohne eigene Beschriftung der Dateiname ohne Endung — das ist fast
        # immer der Name des Klangs.
        from pathlib import Path

        return Path(path).stem or None

    # -- Auswahllisten -----------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        if source != "sinks":
            return []
        entries = [{"value": "", "label": "Standardgerät"}]
        try:
            entries += [
                {"value": sink.name, "label": sink.description or sink.name}
                for sink in self.services.audio.list_sinks()
            ]
        except Exception as exc:
            self.log.warning("Ausgabegeräte nicht abrufbar: %s", exc)
        return entries

    def get_status(self):
        ok, reason = self.services.sound.available()
        return {"connected": ok, "detail": reason or "bereit"}
