"""Audio-Plugin: Lautstärke, Mikrofon, Ausgabegeräte.

Alles läuft über den Audio-Service (``wpctl``/``pactl``). Änderungen von
außen — Systemeinstellungen, Mixer, andere Software — kommen über
``pactl subscribe`` herein und lösen ein sofortiges Neuzeichnen aus; der
periodische Tick ist nur das Sicherheitsnetz.
"""

from __future__ import annotations

from PIL import Image

from deckswitch.plugins.base import ActionPlugin, SlotContext
from deckswitch.services.audio import DEFAULT_SINK, DEFAULT_SOURCE
from deckswitch.services.backgrounds import parse_color

ACCENT = "#3b82f6"


class AudioPlugin(ActionPlugin):
    # -- Eingaben ----------------------------------------------------------

    def on_dial_rotate(self, action_id, settings, delta, ctx):
        if action_id == "volume":
            step = float(ctx.setting("step", 2))
            self.services.audio.change_volume(_target(settings), delta * step)
        elif action_id == "app_volume":
            stream = self._find_stream(settings)
            if stream is None:
                return
            step = float(ctx.setting("step", 5))
            self.services.audio.change_stream_volume(stream["index"], delta * step)
        elif action_id == "mic_mute":
            # Auf einem Dial verhält sich Mic-Mute wie ein Mikrofonpegel.
            step = float(ctx.setting("step", 2))
            self.services.audio.change_volume(_target(settings, source=True), delta * step)

    def on_dial_push(self, action_id, settings, ctx):
        self._activate(action_id, settings, ctx)

    def on_key_down(self, action_id, settings, ctx):
        if action_id == "mic_mute" and ctx.setting("push_to_talk", False):
            # Push-to-Talk: beim Drücken öffnen, beim Loslassen wieder zu.
            self.services.audio.set_mute(_target(settings, source=True), False)
            return
        self._activate(action_id, settings, ctx)

    def on_key_up(self, action_id, settings, ctx):
        if action_id == "mic_mute" and ctx.setting("push_to_talk", False):
            self.services.audio.set_mute(_target(settings, source=True), True)

    def on_touch(self, action_id, settings, x, y, ctx):
        """Tippen auf das Segment schaltet stumm — unabhängig von der Stelle.

        Die Tippposition wird bewusst ignoriert: Der Streifen liegt direkt
        über den Dials, und ein Balken, der die Lautstärke dorthin setzt, wo
        man ihn berührt, springt bei jedem versehentlichen Streifen. Tippen
        macht deshalb dasselbe wie ein Druck auf den Dial.
        """
        self._activate(action_id, settings, ctx)

    def _activate(self, action_id, settings, ctx: SlotContext) -> None:
        audio = self.services.audio
        if action_id == "volume":
            audio.toggle_mute(_target(settings))
        elif action_id == "mic_mute":
            audio.toggle_mute(_target(settings, source=True))
        elif action_id == "output_device":
            sink = settings.get("sink")
            if not sink:
                self.notify_error("Kein Ausgabegerät in den Einstellungen gewählt")
                return
            ok = audio.switch_output(sink, move_streams=ctx.setting("move_streams", True))
            if not ok:
                self.notify_error(f"Wechsel zu '{sink}' fehlgeschlagen")
            # Alle Geräte-Tasten neu zeichnen — der Rahmen wandert.
            self.services.runtime.request_redraw()
        elif action_id == "app_volume":
            stream = self._find_stream(settings)
            if stream is not None:
                audio.toggle_stream_mute(stream["index"])

    # -- Zustand -----------------------------------------------------------

    def get_state(self, action_id, settings, ctx):
        audio = self.services.audio
        if action_id == "volume":
            return "muted" if audio.get_volume(_target(settings)).muted else "default"
        if action_id == "mic_mute":
            return "muted" if audio.get_volume(_target(settings, source=True)).muted else "default"
        if action_id == "output_device":
            return "active" if self._is_active_sink(settings) else "inactive"
        return None

    def get_label(self, action_id, settings, ctx):
        if action_id == "output_device" and not ctx.appearance.label_text:
            # Ohne eigenes Label den Gerätenamen zeigen — sonst stünde da nichts.
            sink = settings.get("sink")
            for info in self.services.audio.list_sinks():
                if info.name == sink:
                    return info.description
        return None

    def on_tick(self, action_id, settings, ctx):
        """Sicherheitsnetz für Zustände ohne eigenes Event."""
        state = self.get_state(action_id, settings, ctx)
        level = self._level(action_id, settings)
        signature = (state, round(level, 3) if level is not None else None)
        if ctx.scratch.get("signature") != signature:
            ctx.scratch["signature"] = signature
            ctx.request_redraw()

    # -- Darstellung -------------------------------------------------------

    def render(self, action_id, settings, ctx):
        state = self.get_state(action_id, settings, ctx)
        level = self._level(action_id, settings)

        if ctx.input_type == "dial":
            return self._render_segment(action_id, settings, ctx, state, level)

        width, height = ctx.size
        mit_balken = (
            action_id in ("volume", "app_volume")
            and ctx.setting("show_bar", True)
            and level is not None
        )
        box = (10, height - 12, width - 10, height - 6)
        image = self.services.render.render_slot(
            ctx,
            state=state,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
            # Platz für den Balken, sonst läge er auf der Beschriftung.
            reserve_bottom=self.services.render.bar_reserve(ctx.size, box) if mit_balken else 0,
        )
        if mit_balken:
            self.services.render.draw_bar(
                image, level, box=box, color=ctx.setting("bar_color", ACCENT)
            )
        if action_id == "output_device" and state == "active":
            self.services.render.draw_badge(
                image, ctx.setting("active_badge", "#22c55e")
            )
        if action_id == "mic_mute" and state == "muted":
            _tint_overlay(image, ctx.setting("muted_tint", "#ef4444"))
        return image

    def _render_segment(
        self, action_id, settings, ctx: SlotContext, state, level
    ) -> Image.Image:
        """Layout für ein Segment: Icon links, Text oben, Balken unten.

        Alle Maße hängen an der Segmenthöhe, nicht an festen Pixelwerten.
        Der Touchstrip des Geräts ist 200×100 groß, ein virtuelles Deck legt
        seine Segmente aber frei fest — bei halber Höhe saß der Balken sonst
        mitten im Prozenttext.
        """
        render = self.services.render
        width, height = ctx.size
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)

        balken = render.bar_box(ctx.size)
        rand = balken[0]
        show_percent = level is not None and ctx.setting("show_percent", True)
        show_bar = level is not None and ctx.setting("show_bar", True)

        # Der Balken sitzt am unteren Rand; alles andere teilt sich den Rest
        # darüber. So bleibt bei jeder Höhe Luft zwischen Zahl und Balken.
        inhalt_hoehe = (balken[1] - rand) if show_bar else (height - rand)

        icon_px = max(
            16,
            min(inhalt_hoehe, round(min(ctx.size) * ctx.appearance.icon_size / 100)),
        )
        icon = self.services.icons.resolve(
            ctx.appearance.icon_for_state(state),
            size=icon_px,
            fallback_name=self._fallback_icon(action_id, state),
            fallback_set=self.services.config.app.active_iconset,
            color=ctx.appearance.label_color,
        )
        image.alpha_composite(icon, (rand, rand + (inhalt_hoehe - icon.height) // 2))

        # Schriftgröße mitwachsen lassen: Die eingestellte Größe passt für
        # den Streifen des Geräts, auf einer halb so hohen Kachel nicht.
        schrift = max(9, min(ctx.appearance.label_size, round(height * 0.30)))
        label = ctx.appearance.label_text or self._default_label(action_id, settings)
        text_left = rand + icon_px + max(6, rand)
        # Prozentwert steht rechts — das Label darf nicht darunter laufen.
        label_width = width - text_left - (round(schrift * 3.2) if show_percent else rand)

        if label and ctx.appearance.show_label:
            render.draw_text_at(
                image,
                label,
                x=text_left,
                y=rand,
                size=schrift,
                color=ctx.appearance.label_color,
                max_width=max(20, label_width),
            )

        if show_percent:
            render.draw_text_at(
                image,
                f"{round(level * 100)}%",
                x=width - rand,
                y=rand,
                size=schrift,
                color="#9ca3af" if state == "muted" else ctx.appearance.label_color,
                align="right",
            )

        if show_bar:
            color = "#6b7280" if state == "muted" else ctx.setting("bar_color", ACCENT)
            render.draw_bar(
                image,
                level,
                # Über die volle Breite: Der Balken hat unten eine eigene
                # Zone, dort steht nichts mehr, was ihn einrücken müsste.
                box=balken,
                color=color,
            )

        if action_id == "output_device" and state == "active":
            render.draw_badge(image, ctx.setting("active_badge", "#22c55e"), width=3)
        return image

    # -- GUI ---------------------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        audio = self.services.audio
        if source == "sinks":
            return [
                {"value": s.name, "label": s.description + (" (Standard)" if s.is_default else "")}
                for s in audio.list_sinks()
            ]
        if source == "sinks_with_default":
            return [{"value": DEFAULT_SINK, "label": "Standardgerät"}] + [
                {"value": s.name, "label": s.description} for s in audio.list_sinks()
            ]
        if source == "sources":
            return [{"value": s.name, "label": s.description} for s in audio.list_sources()]
        if source == "sources_with_default":
            return [{"value": DEFAULT_SOURCE, "label": "Standard-Mikrofon"}] + [
                {"value": s.name, "label": s.description} for s in audio.list_sources()
            ]
        return []

    # -- Intern ------------------------------------------------------------

    def _level(self, action_id, settings) -> float | None:
        audio = self.services.audio
        if action_id == "volume":
            state = audio.get_volume(_target(settings))
            return state.volume if state.available else None
        if action_id == "mic_mute":
            state = audio.get_volume(_target(settings, source=True))
            return state.volume if state.available else None
        if action_id == "app_volume":
            stream = self._find_stream(settings)
            return stream["volume"] if stream else None
        return None

    def _find_stream(self, settings) -> dict | None:
        name = (settings.get("app_name") or "").strip().lower()
        if not name:
            return None
        for stream in self.services.audio.list_streams():
            if name in stream["name"].lower():
                return stream
        return None

    def _is_active_sink(self, settings) -> bool:
        sink = settings.get("sink")
        return bool(sink) and self.services.audio.get_default_sink() == sink

    def _fallback_icon(self, action_id, state) -> str | None:
        action = self.manifest.action(action_id)
        if action is None:
            return None
        for entry in action.states:
            if entry.id == state and entry.default_icon:
                return entry.default_icon
        return action.default_icon

    def _default_label(self, action_id, settings) -> str:
        if action_id == "app_volume":
            return settings.get("app_name") or "App"
        if action_id == "output_device":
            sink = settings.get("sink")
            for info in self.services.audio.list_sinks():
                if info.name == sink:
                    return info.description
        return ""


def _target(settings: dict, source: bool = False) -> str:
    default = DEFAULT_SOURCE if source else DEFAULT_SINK
    return settings.get("target") or default


def _tint_overlay(image: Image.Image, color: str, alpha: int = 60) -> None:
    rgba = parse_color(color, (239, 68, 68, 255))
    overlay = Image.new("RGBA", image.size, (*rgba[:3], alpha))
    image.alpha_composite(overlay)
