"""Seiten- und Ordner-Navigation des Decks selbst.

„Ordner“ ist keine eigene Entität — es ist eine Seite mit ``parent_id``. Damit
sind Ordner, Unterseiten und Blättern dieselbe Mechanik, und das Datenmodell
bleibt eine simple Baumstruktur.
"""

from __future__ import annotations

from deckswitch.plugins.base import ActionPlugin

ACCENT = "#64748b"


class StreamdeckPlugin(ActionPlugin):
    # -- Eingaben ----------------------------------------------------------

    def on_key_down(self, action_id, settings, ctx):
        self._activate(action_id, settings, ctx)

    def on_dial_push(self, action_id, settings, ctx):
        self._activate(action_id, settings, ctx)

    def on_dial_rotate(self, action_id, settings, delta, ctx):
        runtime = self.services.runtime
        if action_id == "brightness":
            self._change_brightness(delta * int(ctx.setting("step", 5)))
        elif action_id in ("next_page", "prev_page", "page_number", "goto_page"):
            # Am Dial fühlt sich Blättern per Drehen natürlicher an als Drücken.
            self._step_page(delta, wrap=bool(ctx.setting("wrap", True)))

    def _activate(self, action_id, settings, ctx) -> None:
        runtime = self.services.runtime
        if action_id == "home":
            runtime.navigate_home()
        elif action_id == "back":
            runtime.navigate_back()
        elif action_id in ("folder", "goto_page"):
            page_id = settings.get("page_id")
            if not page_id:
                self.notify_error("Keine Zielseite eingestellt")
                return
            runtime.navigate(page_id)
        elif action_id == "next_page":
            self._step_page(1, wrap=bool(ctx.setting("wrap", True)))
        elif action_id == "prev_page":
            self._step_page(-1, wrap=bool(ctx.setting("wrap", True)))
        elif action_id == "brightness":
            self._toggle_brightness()

    # -- Zustand und Beschriftung -----------------------------------------

    def get_label(self, action_id, settings, ctx):
        runtime = self.services.runtime
        if action_id == "page_number":
            mode = ctx.setting("format", "number_of_total")
            siblings = runtime.sibling_pages()
            current = runtime.page_number()
            if mode == "number":
                return str(current)
            if mode == "name":
                page = self.services.config.active_profile().pages.get(
                    runtime.current_page_id()
                )
                return page.name if page else str(current)
            return f"{current}/{len(siblings)}"
        if action_id == "folder" and not ctx.appearance.label_text:
            page = self.services.config.active_profile().pages.get(settings.get("page_id", ""))
            return page.name if page else None
        if action_id == "brightness" and not ctx.appearance.label_text:
            return f"{self.services.config.device.brightness}%"
        return None

    def on_tick(self, action_id, settings, ctx):
        if action_id != "page_number":
            return
        label = self.get_label(action_id, settings, ctx)
        if ctx.scratch.get("label") != label:
            ctx.scratch["label"] = label
            ctx.request_redraw()

    def render(self, action_id, settings, ctx):
        if action_id == "page_number":
            return self._render_page_number(settings, ctx)
        if action_id == "brightness" and ctx.input_type == "dial":
            return self._render_brightness(ctx)
        return self.services.render.render_slot(
            ctx,
            state=None,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
        )

    def _render_page_number(self, settings, ctx):
        """Große Zahl statt Icon — die Seitenanzeige ist der Text."""
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        text = self.get_label("page_number", settings, ctx) or "1"
        size = int(ctx.setting("text_size", 40))

        if ctx.setting("show_icon", False):
            icon = self.services.icons.resolve(
                ctx.appearance.icon_for_state(None),
                size=max(16, min(ctx.size) // 3),
                fallback_name="file-description",
                fallback_set=self.services.config.app.active_iconset,
                color=ctx.appearance.label_color,
            )
            image.alpha_composite(icon, ((ctx.size[0] - icon.width) // 2, 6))
            render.draw_text(
                image, text, y=ctx.size[1] - size - 8, size=size,
                color=ctx.appearance.label_color, bold=True
            )
        else:
            render.draw_text(
                image,
                text,
                y=(ctx.size[1] - int(size * 1.2)) // 2,
                size=size,
                color=ctx.appearance.label_color,
                bold=True,
            )
        return image

    def _render_brightness(self, ctx):
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        value = self.services.config.device.brightness
        icon = self.services.icons.resolve(
            ctx.appearance.icon_for_state(None),
            size=max(24, ctx.size[1] - 46),
            fallback_name="sun",
            fallback_set=self.services.config.app.active_iconset,
            color=ctx.appearance.label_color,
        )
        image.alpha_composite(icon, (10, (ctx.size[1] - icon.height) // 2 - 6))
        render.draw_text(image, f"{value}%", y=6, size=ctx.appearance.label_size,
                         color=ctx.appearance.label_color)
        render.draw_bar(
            image,
            value / 100,
            box=(10 + icon.width + 10, ctx.size[1] - 30, ctx.size[0] - 12, ctx.size[1] - 20),
            color="#fbbf24",
        )
        return image

    # -- GUI ---------------------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        if source != "pages":
            return []
        profile = self.services.config.active_profile()
        options = []
        for page_id in _ordered_page_ids(profile):
            page = profile.pages[page_id]
            depth = len(profile.path_to_root(page_id)) - 1
            options.append(
                {"value": page_id, "label": f"{'– ' * depth}{page.name}"}
            )
        return options

    # -- Intern ------------------------------------------------------------

    def _step_page(self, delta: int, *, wrap: bool) -> None:
        # Dieselbe Mechanik, die auch das Wischen über den Touchstrip nutzt.
        self.services.runtime.step_page(delta, wrap=wrap)

    def _change_brightness(self, delta: int) -> None:
        device = self.services.config.device
        device.brightness = max(5, min(100, device.brightness + delta))
        self.services.runtime.device.set_brightness(device.brightness)
        self.services.runtime.save_config()
        self.services.runtime.request_redraw()

    def _toggle_brightness(self) -> None:
        """Auf einer Taste: zwischen gedimmt und hell umschalten."""
        device = self.services.config.device
        device.brightness = 30 if device.brightness > 40 else 80
        self.services.runtime.device.set_brightness(device.brightness)
        self.services.runtime.save_config()
        self.services.runtime.request_redraw()


def _ordered_page_ids(profile) -> list[str]:
    """Seiten in Baumreihenfolge (Wurzeln zuerst, Kinder eingerückt)."""
    children: dict[str | None, list[str]] = {}
    for page in profile.pages.values():
        children.setdefault(page.parent_id, []).append(page.id)

    ordered: list[str] = []
    seen: set[str] = set()

    def walk(parent_id):
        for page_id in children.get(parent_id, []):
            if page_id in seen:
                continue
            seen.add(page_id)
            ordered.append(page_id)
            walk(page_id)

    walk(None)
    # Verwaiste Seiten (kaputter parent-Verweis) trotzdem anbieten.
    ordered.extend(pid for pid in profile.pages if pid not in seen)
    return ordered
