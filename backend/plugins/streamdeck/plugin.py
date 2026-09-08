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
        if action_id == "brightness":
            self._change_brightness(ctx, delta * int(ctx.setting("step", 5)))
        elif action_id in ("next_page", "prev_page", "page_number", "goto_page"):
            # Am Dial fühlt sich Blättern per Drehen natürlicher an als Drücken.
            self._step_page(ctx, delta, wrap=bool(ctx.setting("wrap", True)))

    def _activate(self, action_id, settings, ctx) -> None:
        # Über ``ctx`` und nicht über ``self``: Bei mehreren Decks muss die
        # Navigation das Gerät treffen, auf dem gedrückt wurde.
        runtime = ctx.services.runtime
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
            self._step_page(ctx, 1, wrap=bool(ctx.setting("wrap", True)))
        elif action_id == "prev_page":
            self._step_page(ctx, -1, wrap=bool(ctx.setting("wrap", True)))
        elif action_id == "brightness":
            self._toggle_brightness(ctx)
        elif action_id == "overlay":
            self._overlay(settings, ctx)
        elif action_id == "profile":
            self._profil(settings, ctx)

    def _profil(self, settings, ctx) -> None:
        """Schaltet das Deck auf ein anderes Profil.

        Ohne Angabe geht es zurück zum vorigen — damit reicht eine Taste je
        Profil, und der Weg zurück braucht keine eigene.
        """
        gewaehlt = (settings.get("profile_id") or "").strip()
        name = ""
        if gewaehlt:
            profil = self.services.config.profiles.get(gewaehlt)
            if profil is None:
                self.notify_error("Das eingestellte Profil gibt es nicht mehr")
                return
            name = profil.name
        if not ctx.services.runtime.switch_profile(name):
            # Kein Fehler: Wer auf dem Profil steht, das die Taste meint,
            # hat nichts falsch gemacht.
            self.services.runtime.request_redraw()

    def _overlay(self, settings, ctx) -> None:
        """Zeigt oder versteckt ein virtuelles Deck.

        Der Weg über eine Taste ist bewusst der erste: Einen globalen
        Kurzbefehl zum Herbeirufen gibt es unter Wayland nicht geschenkt —
        ein Deck, das man ohnehin in der Hand hat, tut es genauso.
        """
        dienst = self.services.overlay
        ziel = (settings.get("deck") or "").strip()
        if not ziel:
            self.notify_error("Kein virtuelles Deck ausgewählt")
            return

        modus = settings.get("mode") or "toggle"
        am_zeiger = bool(settings.get("at_cursor", True))

        async def schalten():
            try:
                if modus == "show":
                    await dienst.show(ziel, at_cursor=am_zeiger)
                elif modus == "hide":
                    dienst.hide(ziel)
                else:
                    await dienst.toggle(ziel, at_cursor=am_zeiger)
            except Exception as exc:
                self.notify_error(str(exc))
            ctx.request_redraw()

        self.run_async(schalten())

    def get_state(self, action_id, settings, ctx):
        if action_id == "profile":
            gewaehlt = (settings.get("profile_id") or "").strip()
            return "active" if gewaehlt and gewaehlt == ctx.profile_id else "inactive"
        if action_id != "overlay":
            return None
        ziel = (settings.get("deck") or "").strip()
        sichtbar = bool(ziel) and self.services.overlay.is_visible(ziel)
        return "visible" if sichtbar else "hidden"

    # -- Zustand und Beschriftung -----------------------------------------

    def get_label(self, action_id, settings, ctx):
        runtime = ctx.services.runtime
        if action_id == "profile" and not ctx.appearance.label_text:
            gewaehlt = (settings.get("profile_id") or "").strip()
            profil = self.services.config.profiles.get(gewaehlt)
            return profil.name if profil is not None else "Zurück"
        pages = self.services.config.profile(ctx.profile_id).pages
        if action_id == "page_number":
            mode = ctx.setting("format", "number_of_total")
            siblings = runtime.sibling_pages()
            current = runtime.page_number()
            if mode == "number":
                return str(current)
            if mode == "name":
                page = pages.get(runtime.current_page_id())
                return page.name if page else str(current)
            return f"{current}/{len(siblings)}"
        if action_id == "folder" and not ctx.appearance.label_text:
            page = pages.get(settings.get("page_id", ""))
            return page.name if page else None
        if action_id == "brightness" and not ctx.appearance.label_text:
            return f"{runtime.device_settings.brightness}%"
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
        zustand = self.get_state(action_id, settings, ctx)
        bild = self.services.render.render_slot(
            ctx,
            state=zustand,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
        )
        if action_id == "profile" and zustand == "active":
            self.services.render.draw_badge(bild, ctx.setting("active_badge", "#22c55e"))
        return bild

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
                fallback_set=self.services.icons.system_iconset,
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
        # Gleiches Segment-Layout wie beim Lautstärke-Dial: Balken unten in
        # eigener Zone, Text oben, Icon links dazwischen. Alle Maße hängen an
        # der Höhe — auf einem virtuellen Deck ist ein Segment kleiner.
        balken = render.bar_box(ctx.size)
        rand = balken[0]
        hoehe = ctx.size[1]
        inhalt = balken[1] - rand
        icon = self.services.icons.resolve(
            ctx.appearance.icon_for_state(None),
            size=max(16, min(inhalt, round(min(ctx.size) * ctx.appearance.icon_size / 100))),
            fallback_name="sun",
            fallback_set=self.services.icons.system_iconset,
            color=ctx.appearance.label_color,
        )
        image.alpha_composite(icon, (rand, rand + (inhalt - icon.height) // 2))
        render.draw_text_at(
            image,
            f"{value}%",
            x=ctx.size[0] - rand,
            y=rand,
            size=max(9, min(ctx.appearance.label_size, round(hoehe * 0.30))),
            color=ctx.appearance.label_color,
            align="right",
        )
        render.draw_bar(image, value / 100, box=balken, color="#fbbf24")
        return image

    # -- GUI ---------------------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        if source == "virtual_decks":
            # ``is_overlay`` und nicht ``is_virtual``: Letzteres heißt nur
            # „kein Gerät am USB" und umfasst auch die Netz-Decks. Die
            # laufen aber im Browser eines anderen Rechners — sie auf dem
            # eigenen Bildschirm einzublenden ergibt keinen Sinn, und die
            # Taste bliebe wirkungslos.
            return [
                {"value": deck.key, "label": deck.label}
                for deck in self.services.runtime.decks_in_order()
                if deck.binding.is_overlay
            ]
        if source == "profiles":
            # Leer als erste Wahl: Das ist der Weg zurück, und er ist die
            # häufigste zweite Taste neben einem Profilwechsel.
            return [{"value": "", "label": "Zurück zum vorigen"}] + [
                {"value": profil.id, "label": profil.name}
                for profil in self.services.config.profiles.values()
            ]
        if source != "pages":
            return []
        # Welche Seiten zur Auswahl stehen, hängt am Deck: Jedes Gerät hat
        # sein eigenes Profil und damit seinen eigenen Seitenbaum.
        profile = self.services.runtime.profile_for((context or {}).get("__deck"))
        options = []
        for page_id in _ordered_page_ids(profile):
            page = profile.pages[page_id]
            depth = len(profile.path_to_root(page_id)) - 1
            options.append(
                {"value": page_id, "label": f"{'– ' * depth}{page.name}"}
            )
        return options

    # -- Intern ------------------------------------------------------------

    def _step_page(self, ctx, delta: int, *, wrap: bool) -> None:
        # Dieselbe Mechanik, die auch das Wischen über den Touchstrip nutzt.
        ctx.services.runtime.step_page(delta, wrap=wrap)

    def _change_brightness(self, ctx, delta: int) -> None:
        # Die Helligkeit gehört dem Deck, nicht der App: Zwei angeschlossene
        # Geräte dürfen unterschiedlich hell leuchten.
        runtime = ctx.services.runtime
        settings = runtime.device_settings
        settings.brightness = max(5, min(100, settings.brightness + delta))
        runtime.device.set_brightness(settings.brightness)
        runtime.save_config()
        runtime.request_redraw()

    def _toggle_brightness(self, ctx) -> None:
        """Auf einer Taste: zwischen gedimmt und hell umschalten."""
        runtime = ctx.services.runtime
        settings = runtime.device_settings
        settings.brightness = 30 if settings.brightness > 40 else 80
        runtime.device.set_brightness(settings.brightness)
        runtime.save_config()
        runtime.request_redraw()


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
