"""KI-Nutzung auf Tasten und Dials: Session, Woche, Guthaben und Kosten.

Die Daten kommen von CodexBar (``codexbar serve``) auf diesem Rechner.
Läuft CodexBar nicht, fragt das Plugin Claude direkt ab. Beides steckt in
:mod:`.ai_usage`, dieses Modul arbeitet nur mit dem Ergebnis.

Ein Poller versorgt alle Belegungen, keine Taste fragt selbst nach.
Neu gezeichnet wird nur, wenn sich an einer Taste etwas Sichtbares ändert.
Dafür vergleicht der Tick je Belegung eine Signatur aus Zustand, Zahl und
Countdown-Minute und fordert erst bei einem Unterschied ein neues Bild an.

Fehlt ein Wert, zeigt die Taste ihn nicht an. Es wird nichts geschätzt.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

from deckswitch import events as ev
from deckswitch.plugins.base import ActionPlugin

from . import texte, uebersicht, zeichnen as z
from .ai_usage import Alerts, Poller, PollSettings, ProviderUsage, level
from .ai_usage.model import DEFAULT_CRIT, DEFAULT_WARN, UsageWindow, utcnow

ACCENT = "#8b5cf6"

#: So lange bleibt die Detailansicht nach einem Tippen auf den Touchstrip.
DETAIL_S = 6.0

#: Standardsymbol je Zustand, wenn unter Aussehen keines gewählt ist.
STATE_ICONS = {
    "ok": "gauge",
    "warn": "gauge",
    "crit": "alert-triangle",
    "stale": "clock-pause",
    "error": "plug-connected-x",
    "login_missing": "lock",
}

MESSAGE_COLOR = {"error": "#f87171", "login_missing": "#fbbf24"}


@dataclass(slots=True)
class View:
    """Was eine Belegung gerade zeigt.

    Der Tick vergleicht die :meth:`signature`, und das Zeichnen verwendet
    dieselbe Ansicht. Damit zeigt die Taste genau den Stand, nach dem über
    das Neuzeichnen entschieden wurde.
    """

    state: str
    title: str = ""
    provider: ProviderUsage | None = None
    window: UsageWindow | None = None
    value: str = ""
    fraction: float | None = None
    level: str | None = None
    caption: str = ""
    countdown: str | None = None
    message: str = ""
    stale: bool = False
    pulse: bool = False
    rank: int = 0
    unit: str = ""

    def signature(self) -> tuple:
        return (self.state, self.title, self.value, self.level, self.caption,
                self.countdown, self.message, self.stale, self.pulse, self.rank,
                self.unit, round(self.fraction or 0, 3))


class AIUsagePlugin(ActionPlugin):
    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        self.poller = Poller()
        self.alerts = Alerts()
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._polling = False

    # ======================================================================
    # Lebenszyklus
    # ======================================================================

    async def setup(self):
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="ai-usage-poll")

    async def teardown(self):
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def on_plugin_config_changed(self, config):
        # Nach einer Änderung (Adresse, Token-Datei, Fallback) sofort neu
        # abfragen und nicht bis zum Ende des laufenden Intervalls warten.
        loop = getattr(self.services.runtime, "_loop", None)
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake.set)

    async def _loop(self):
        while True:
            if self._in_use() or self._config_bool("notify", False):
                try:
                    await self.refresh()
                except Exception:  # noqa: BLE001 - die Schleife darf nicht sterben
                    # Etwa eine abgebrochene Antwort von CodexBar. Ohne diesen
                    # Fang endete der Task, und es käme nie wieder ein Stand.
                    self.log.exception("Abfrage fehlgeschlagen")
            settings = self._poll_settings()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=settings.refresh_s)
            self._wake.clear()

    async def refresh(self) -> bool:
        """Eine Abfragerunde im Executor. Läuft schon eine, kommt keine zweite dazu."""
        if self._polling:
            return False
        self._polling = True
        try:
            settings = self._poll_settings()
            loop = asyncio.get_running_loop()
            changed = await loop.run_in_executor(None, self.poller.poll, settings)
        finally:
            self._polling = False
        self.services.runtime.publish_plugin_status(self.manifest.id)
        if changed:
            await self._check_alerts()
        return changed

    def _poll_settings(self) -> PollSettings:
        return PollSettings.from_config(self.plugin_config)

    def _in_use(self) -> bool:
        """Gibt es irgendwo eine Belegung dieses Plugins?

        Ohne Belegung fragt das Plugin nicht ab. Sonst würde der
        Claude-Fallback jede Minute bei Anthropic anfragen, obwohl keine
        Taste die Werte zeigt.
        """
        def walk(slot) -> bool:
            if slot is None:
                return False
            if slot.plugin_id == self.manifest.id:
                return True
            children = [slot.long_press, slot.double_press, slot.turn_left, slot.turn_right,
                        *slot.stack]
            return any(walk(child) for child in children)

        for profile in self.services.config.profiles.values():
            for page in profile.pages.values():
                for slot in [*page.keys.values(), *page.dials.values()]:
                    if walk(slot):
                        return True
        return False

    # ======================================================================
    # Einstellungen
    # ======================================================================

    def _config_bool(self, key: str, default: bool) -> bool:
        value = self.plugin_config.get(key)
        return default if value is None else bool(value)

    def _config_number(self, key: str, default: float) -> float:
        try:
            value = float(self.plugin_config.get(key))
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _thresholds(self, settings: dict | None = None) -> tuple[float, float]:
        warn = self._config_number("warn_pct", DEFAULT_WARN)
        crit = self._config_number("crit_pct", DEFAULT_CRIT)
        if settings:
            # 0 bedeutet „globale Schwelle verwenden“, so steht es im Formular.
            with contextlib.suppress(TypeError, ValueError):
                if float(settings.get("warn_pct") or 0) > 0:
                    warn = float(settings["warn_pct"])
            with contextlib.suppress(TypeError, ValueError):
                if float(settings.get("crit_pct") or 0) > 0:
                    crit = float(settings["crit_pct"])
        return warn, crit

    def _color(self, state_level: str | None) -> str:
        defaults = {"ok": "#22c55e", "warn": "#eab308", "crit": "#ef4444"}
        if state_level not in defaults:
            return z.MUTED
        return str(self.plugin_config.get(f"color_{state_level}") or defaults[state_level])

    # ======================================================================
    # Was eine Belegung zeigt
    # ======================================================================

    def _providers(self) -> list[ProviderUsage]:
        return self.poller.providers()

    def _provider(self, provider_id: str | None) -> ProviderUsage | None:
        if not provider_id:
            return None
        for entry in self._providers():
            if entry.id == provider_id:
                return entry
        return None

    def _no_data_view(self, title: str = "") -> View:
        """Ansicht, wenn es keinen Stand gibt, weil weder CodexBar noch der Fallback geliefert haben."""
        if self.poller.snapshot is None and not self.poller.polls:
            # Plugin ist gerade erst geladen und hat noch nie abgefragt.
            self.run_async(self.refresh())
            return View(state="stale", title=title, message="…")
        error = self.poller.error or self.poller.codexbar_error
        message = self.t("no_data")
        if error is not None and error.kind == "login_missing":
            return View(state="login_missing", title=title, message=self.t("login_missing"))
        return View(state="error", title=title, message=message)

    def _window_kind(self, settings: dict, ctx) -> str:
        return ctx.scratch.get("window") or settings.get("window") or "session"

    def _pick_window(self, provider: ProviderUsage, kind: str) -> UsageWindow | None:
        if kind == "auto":
            return provider.peak()
        return provider.window(kind)

    def _display(self, settings: dict, ctx) -> str:
        return ctx.scratch.get("display") or settings.get("display") or "used"

    def _usage_view(self, provider: ProviderUsage, kind: str, settings: dict, ctx,
                    *, title: str | None = None, rank: int = 0) -> View:
        """Ansicht für eine Taste mit einem Fenster eines Anbieters."""
        name = title if title is not None else provider.name

        if provider.error:
            state = provider.error_kind or "error"
            return View(state=state, title=name, provider=provider,
                        message=self.t("login_missing") if state == "login_missing"
                        else self.t("error"), rank=rank)

        window = self._pick_window(provider, kind)
        if window is None or window.used_pct is None:
            # Der Anbieter meldet dieses Fenster nicht (z. B. nur Guthaben).
            return View(state="stale" if provider.stale else "ok", title=name, provider=provider,
                        value="---", caption=texte.window_label(kind, kind)
                        if kind != "auto" else "", message=self.t("not_reported"),
                        stale=provider.stale, rank=rank)

        warn, crit = self._thresholds(settings)
        used = window.used_pct
        state_level = level(used, warn, crit)
        shown = used if self._display(settings, ctx) == "used" else 100.0 - used
        state = "stale" if provider.stale else state_level
        pulse = False
        if state == "crit" and ctx.setting("pulse", False):
            pulse = int(time.monotonic()) % 2 == 0

        return View(
            state=state,
            title=name,
            provider=provider,
            window=window,
            value=texte.percent(shown),
            fraction=shown / 100.0,
            level=state_level,
            caption=texte.window_label(window.kind, window.label),
            countdown=texte.countdown(window.resets_at, utcnow()),
            stale=provider.stale,
            pulse=pulse,
            rank=rank,
        )

    def _view(self, action_id: str, settings: dict, ctx) -> View:
        if action_id == "overview":
            return View(state="ok")
        if self.poller.snapshot is None:
            # Ohne Daten ist auch der Anzeigename des Anbieters unbekannt.
            return self._no_data_view()

        if action_id == "highest":
            return self._highest_view(settings, ctx)
        if action_id == "dial":
            provider = self._dial_provider(settings, ctx)
            if provider is None:
                return View(state="error", message=self.t("pick_provider"))
            return self._usage_view(provider, "session", settings, ctx)

        provider_id = settings.get("provider")
        if not provider_id:
            return View(state="error", message=self.t("pick_provider"))
        provider = self._provider(provider_id)
        if provider is None:
            return View(state="error", title=str(provider_id), message=self.t("not_reported"))
        if action_id == "credits":
            return self._credits_view(provider, settings, ctx)
        return self._usage_view(provider, self._window_kind(settings, ctx), settings, ctx)

    # -- Höchste Auslastung ------------------------------------------------

    def _ranking(self, settings: dict, ctx) -> list[ProviderUsage]:
        kind = self._window_kind(settings, ctx)

        def pct(provider: ProviderUsage) -> float | None:
            window = self._pick_window(provider, kind)
            return window.used_pct if window else None

        ranked = [p for p in self._providers() if not p.error and pct(p) is not None]
        return sorted(ranked, key=lambda p: pct(p), reverse=True)

    def _highest_view(self, settings: dict, ctx) -> View:
        ranked = self._ranking(settings, ctx)
        if not ranked:
            return View(state="ok", title=self.t("none_active"), value="---",
                        message=self.t("none_active"))
        rank = int(ctx.scratch.get("rank", 0)) % len(ranked)
        provider = ranked[rank]
        title = f"{rank + 1}. {provider.name}" if rank else provider.name
        return self._usage_view(provider, self._window_kind(settings, ctx), settings, ctx,
                                title=title, rank=rank)

    # -- Guthaben und Kosten -----------------------------------------------

    def _credit_modes(self, provider: ProviderUsage) -> list[str]:
        modes = []
        if provider.credits is not None:
            modes.append("credits")
        if provider.cost_today_usd is not None:
            modes.append("cost_today")
        if provider.cost_30d_usd is not None:
            modes.append("cost_30d")
        return modes

    def _credits_view(self, provider: ProviderUsage, settings: dict, ctx) -> View:
        if provider.error:
            state = provider.error_kind or "error"
            return View(state=state, title=provider.name, provider=provider,
                        message=self.t(state))
        modes = self._credit_modes(provider)
        state = "stale" if provider.stale else "ok"
        if not modes:
            return View(state=state, title=provider.name, provider=provider, value="---",
                        caption=self.t("credits"), message=self.t("unavailable"),
                        stale=provider.stale)

        wanted = settings.get("show") or "auto"
        start = modes.index(wanted) if wanted in modes else 0
        mode = modes[(start + int(ctx.scratch.get("mode_offset", 0))) % len(modes)]

        unit = ""
        if mode == "credits":
            value, unit = texte.credits(*provider.credits)
        else:
            value = texte.money(provider.cost_today_usd if mode == "cost_today"
                                else provider.cost_30d_usd)
            if provider.cost_estimated:
                # Steht unter dem Betrag, damit niemand ihn für eine Rechnung hält.
                unit = self.t("estimated")
        return View(state=state, title=provider.name, provider=provider, value=value,
                    caption=self.t(mode), unit=unit, stale=provider.stale)

    # -- Dial --------------------------------------------------------------

    def _dial_provider(self, settings: dict, ctx) -> ProviderUsage | None:
        providers = self._providers()
        if not providers:
            return None
        chosen = ctx.scratch.get("provider") or settings.get("provider")
        for provider in providers:
            if provider.id == chosen:
                return provider
        # Ohne Auswahl der erste Anbieter mit Werten, damit der Dial nicht mit
        # einem nicht eingerichteten Anbieter beginnt.
        usable = [p for p in providers if p.windows and not p.error]
        return usable[0] if usable else providers[0]

    # ======================================================================
    # Eingaben
    # ======================================================================

    async def on_key_down(self, action_id, settings, ctx):
        if action_id == "overview":
            await self._open_overview(settings, ctx)
            return
        ctx.scratch["pressed_at"] = time.monotonic()

    async def on_key_up(self, action_id, settings, ctx):
        if action_id == "overview":
            return
        started = ctx.scratch.pop("pressed_at", None)
        held = time.monotonic() - started if started else 0.0
        threshold = self._long_press_s(ctx)

        if held >= threshold and not ctx.is_long_press:
            # Langer Druck: sofort neu abfragen, ohne auf das Intervall zu warten.
            await self.refresh()
        elif action_id == "provider":
            current = self._window_kind(settings, ctx)
            if current == "auto":
                provider = self._provider(settings.get("provider"))
                peak = provider.peak() if provider else None
                current = peak.kind if peak else "session"
            ctx.scratch["window"] = "weekly" if current == "session" else "session"
        elif action_id == "highest":
            ctx.scratch["rank"] = int(ctx.scratch.get("rank", 0)) + 1
            if ctx.scratch["rank"] >= max(1, len(self._ranking(settings, ctx))):
                ctx.scratch["rank"] = 0
        elif action_id == "credits":
            ctx.scratch["mode_offset"] = int(ctx.scratch.get("mode_offset", 0)) + 1
        ctx.request_redraw()

    def _long_press_s(self, ctx) -> float:
        device = getattr(ctx.services.runtime, "device_settings", None)
        ms = getattr(device, "long_press_ms", None) or 500
        return max(0.2, ms / 1000)

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        providers = self._providers()
        if not providers:
            return
        current = self._dial_provider(settings, ctx)
        ids = [p.id for p in providers]
        index = ids.index(current.id) if current and current.id in ids else 0
        step = 1 if delta > 0 else -1
        ctx.scratch["provider"] = ids[(index + step) % len(ids)]
        ctx.scratch["detail_until"] = 0
        ctx.request_redraw()

    async def on_dial_push(self, action_id, settings, ctx):
        ctx.scratch["display"] = "remaining" if self._display(settings, ctx) == "used" else "used"
        ctx.request_redraw()

    async def on_touch(self, action_id, settings, x, y, ctx):
        showing = ctx.scratch.get("detail_until", 0) > time.monotonic()
        ctx.scratch["detail_until"] = 0 if showing else time.monotonic() + DETAIL_S
        ctx.request_redraw()

    def on_tick(self, action_id, settings, ctx):
        if action_id == "overview":
            return
        view = self._view(action_id, settings, ctx)
        signature = (view.signature(), self._detail_open(ctx))
        if ctx.scratch.get("signature") != signature:
            ctx.scratch["signature"] = signature
            ctx.request_redraw()

    def _detail_open(self, ctx) -> bool:
        return ctx.scratch.get("detail_until", 0) > time.monotonic()

    # -- Übersicht ---------------------------------------------------------

    async def _open_overview(self, settings, ctx):
        runtime = ctx.services.runtime
        if self.poller.snapshot is None:
            await self.refresh()
        providers = [(p.id, p.name) for p in self._providers()]
        if not providers:
            self.notify_info(self.t("overview_empty"))
            return

        deck = getattr(runtime, "deck", None)
        profile = deck.profile if deck is not None else self.services.config.active_profile()
        device = getattr(runtime, "device", None)
        info = getattr(device, "info", None)
        key_count = getattr(info, "key_count", 0) or 8

        pages = uebersicht.sync(
            profile, ctx.page_id, providers,
            key_count=key_count, settings=settings,
            texts=self.t,
        )
        runtime.save_config()
        bus = getattr(runtime, "bus", None)
        if bus is not None:
            bus.publish(ev.EVT_CONFIG_CHANGED, reason="ai_usage_overview")
        runtime.navigate(pages[0].id)

    # ======================================================================
    # Darstellung
    # ======================================================================

    def get_state(self, action_id, settings, ctx):
        if action_id == "overview":
            return None
        return self._view(action_id, settings, ctx).state

    def render(self, action_id, settings, ctx):
        if action_id == "overview":
            return self.services.render.render_slot(ctx)
        view = self._view(action_id, settings, ctx)
        ctx.scratch["signature"] = (view.signature(), self._detail_open(ctx))

        if ctx.input_type == "dial":
            if self._detail_open(ctx) and view.provider is not None:
                return self._render_detail(view, settings, ctx)
            return self._render_segment(view, settings, ctx)
        if view.state in ("error", "login_missing") or (view.message == "…"):
            return self._render_message(view, ctx)
        if action_id == "credits":
            return self._render_credits(view, ctx)
        style = settings.get("style") or "ring"
        if style == "icon":
            return self._render_icon_style(view, ctx)
        if style == "bar":
            return self._render_bar(view, settings, ctx)
        return self._render_ring(view, settings, ctx)

    # -- Gemeinsames -------------------------------------------------------

    def _base(self, view: View, settings: dict, ctx):
        image = self.services.render.background(ctx.size, ctx.appearance, accent=ACCENT)
        if settings.get("color_target") == "background" and view.level and not view.stale:
            z.tint(image, self._color(view.level))
        return image

    def _finish(self, image, view: View, ctx):
        """Dimmt veraltete Werte und zeichnet den Puls. Läuft als letzter Schritt."""
        factor = z.scale(ctx.size)
        if view.stale:
            z.dim(image)
            icon = self._state_icon(ctx, "stale", size=z.px(18, factor), color=z.SOFT)
            image.alpha_composite(icon, (image.width - icon.width - z.px(4, factor), z.px(4, factor)))
        if view.pulse:
            z.pulse_frame(image, self._color("crit"), z.px(6, factor))
        return image

    def _state_icon(self, ctx, state: str, *, size: int, color: str | None = None):
        ref = ctx.appearance.icon_for_state(state)
        return self.services.icons.resolve(
            ref,
            size=size,
            fallback_name=STATE_ICONS.get(state, "gauge"),
            fallback_set=self.services.icons.system_iconset,
            color=color if ref is None else None,
        )

    def _value_color(self, view: View) -> str:
        return z.MUTED if view.stale else self._color(view.level)

    # -- Tasten ------------------------------------------------------------

    def _render_ring(self, view: View, settings: dict, ctx):
        render = self.services.render
        image = self._base(view, settings, ctx)
        width, height = ctx.size
        factor = z.scale(ctx.size)

        render.draw_text_at(image, view.title, x=width // 2, y=z.px(4, factor),
                            size=z.px(13, factor), color=z.SOFT, align="center",
                            max_width=width - z.px(8, factor))

        radius = min(width, height) * 0.27
        centre = (width / 2, height * 0.52)
        z.ring(image, centre, radius, z.px(8, factor), view.fraction, self._value_color(view))

        size = z.px(22 if len(view.value) <= 3 else 18, factor)
        render.draw_text_at(image, view.value, x=width // 2, y=round(centre[1] - size * 0.62),
                            size=size, color=ctx.appearance.label_color, bold=True,
                            align="center")

        self._bottom_line(image, view, ctx)
        return self._finish(image, view, ctx)

    def _render_bar(self, view: View, settings: dict, ctx):
        render = self.services.render
        image = self._base(view, settings, ctx)
        width, height = ctx.size
        factor = z.scale(ctx.size)

        render.draw_text_at(image, view.title, x=width // 2, y=z.px(4, factor),
                            size=z.px(13, factor), color=z.SOFT, align="center",
                            max_width=width - z.px(8, factor))
        render.draw_text_at(image, view.value, x=width // 2, y=z.px(26, factor),
                            size=z.px(30, factor), color=ctx.appearance.label_color, bold=True,
                            align="center")
        if view.caption:
            render.draw_text_at(image, view.caption, x=width // 2, y=z.px(62, factor),
                                size=z.px(11, factor), color=z.MUTED, align="center",
                                max_width=width - z.px(8, factor))
        margin = z.px(10, factor)
        top = z.px(80, factor)
        z.bar(image, (margin, top, width - margin, top + z.px(9, factor)), view.fraction,
              self._value_color(view))
        if view.countdown:
            render.draw_text_at(image, view.countdown, x=width // 2, y=height - z.px(17, factor),
                                size=z.px(11, factor), color=z.SOFT, align="center")
        return self._finish(image, view, ctx)

    def _bottom_line(self, image, view: View, ctx):
        """Untere Zeile mit Fenster und Countdown, gekürzt, wenn der Platz nicht reicht."""
        width, height = ctx.size
        factor = z.scale(ctx.size)
        parts = [p for p in (view.caption, view.countdown) if p]
        if not view.countdown and view.message:
            parts.append(view.message)
        self.services.render.draw_text_at(
            image, " · ".join(parts), x=width // 2, y=height - z.px(17, factor),
            size=z.px(11, factor), color=z.SOFT, align="center",
            max_width=width - z.px(6, factor),
        )

    def _render_icon_style(self, view: View, ctx):
        """Symbol je Zustand und darunter die Zahl, im Standard-Layout der App."""
        label = view.value if view.value else view.message
        image = self.services.render.render_slot(ctx, state=view.state, label_override=label,
                                                 accent=ACCENT)
        return self._finish(image, view, ctx)

    def _render_message(self, view: View, ctx):
        """Bei Fehler, fehlender Anmeldung oder ohne Daten zeigt die Taste ein Symbol statt einer Zahl."""
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size
        factor = z.scale(ctx.size)
        color = MESSAGE_COLOR.get(view.state, z.MUTED)

        if view.title:
            render.draw_text_at(image, view.title, x=width // 2, y=z.px(4, factor),
                                size=z.px(13, factor), color=z.SOFT, align="center",
                                max_width=width - z.px(8, factor))
        icon = self._state_icon(ctx, view.state, size=z.px(40, factor), color=color)
        image.alpha_composite(icon, ((width - icon.width) // 2, round(height * 0.24)))

        lines = z.wrap(view.message, z.px(11, factor), width - z.px(8, factor))
        line_height = z.px(13, factor)
        top = height - z.px(6, factor) - line_height * len(lines)
        for i, line in enumerate(lines):
            render.draw_text_at(image, line, x=width // 2, y=top + i * line_height,
                                size=z.px(11, factor), color=color, align="center")
        return image

    def _render_credits(self, view: View, ctx):
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size
        factor = z.scale(ctx.size)

        render.draw_text_at(image, view.caption, x=width // 2, y=z.px(6, factor),
                            size=z.px(12, factor), color=z.SOFT, align="center")
        size = z.px(26 if len(view.value) <= 6 else 19, factor)
        render.draw_text_at(image, view.value, x=width // 2, y=round(height * 0.36),
                            size=size, color=ctx.appearance.label_color, bold=True,
                            align="center", max_width=width - z.px(6, factor))
        second = view.unit or (view.message if view.value == "---" else "")
        if second:
            render.draw_text_at(image, second, x=width // 2, y=round(height * 0.62),
                                size=z.px(11, factor), color=z.MUTED, align="center",
                                max_width=width - z.px(6, factor))
        render.draw_text_at(image, view.title, x=width // 2, y=height - z.px(17, factor),
                            size=z.px(11, factor), color=z.SOFT, align="center",
                            max_width=width - z.px(6, factor))
        return self._finish(image, view, ctx)

    # -- Touchstrip --------------------------------------------------------

    def _render_segment(self, view: View, settings: dict, ctx):
        """Name, zwei Balken (Session/Woche), Countdown und Prognose."""
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size
        factor = z.scale(ctx.size, base=100)
        provider = view.provider
        margin = z.px(10, factor)

        if provider is None or view.state in ("error", "login_missing") or view.message == "…":
            return self._render_segment_message(image, view, ctx)

        # Kopfzeile mit Name und Plan, dazu ein Punkt, wenn der Anbieter eine
        # Störung meldet. Bei der Anzeige „übrig“ steht das Wort rechts oben,
        # in der Fußzeile ist dafür kein Platz.
        display = self._display(settings, ctx)
        right = width - margin
        if provider.status in ("warning", "critical"):
            color = self._color("warn" if provider.status == "warning" else "crit")
            z.dot(image, (right - z.px(4, factor), z.px(14, factor)), z.px(4, factor), color)
            right -= z.px(14, factor)
        if display == "remaining":
            render.draw_text_at(image, self.t("remaining"), x=right, y=z.px(8, factor),
                                size=z.px(10, factor), color=z.MUTED, align="right")
            right -= z.px(34, factor)
        head = provider.name + (f"  {provider.plan}" if provider.plan else "")
        render.draw_text_at(image, head, x=margin, y=z.px(6, factor), size=z.px(13, factor),
                            color=ctx.appearance.label_color, bold=True,
                            max_width=right - margin - z.px(4, factor))

        rows = self._segment_rows(provider)
        warn, crit = self._thresholds(settings)
        label_w = z.px(58, factor)
        value_w = z.px(38, factor)
        for i, window in enumerate(rows[:2]):
            y = z.px(30 + i * 22, factor)
            used = window.used_pct
            shown = None if used is None else (used if display == "used" else 100.0 - used)
            render.draw_text_at(image, texte.window_label(window.kind, window.label),
                                x=margin, y=y, size=z.px(11, factor), color=z.SOFT,
                                max_width=label_w - z.px(4, factor))
            color = z.MUTED if provider.stale else self._color(level(used, warn, crit))
            bar_y = y + z.px(4, factor)
            z.bar(image, (margin + label_w, bar_y, width - margin - value_w, bar_y + z.px(7, factor)),
                  None if shown is None else shown / 100.0, color)
            render.draw_text_at(image, texte.percent(shown), x=width - margin, y=y,
                                size=z.px(12, factor), color=ctx.appearance.label_color,
                                bold=True, align="right")

        if not rows:
            self._segment_credit_line(image, provider, ctx, y=z.px(34, factor))

        # Fußzeile mit Countdown und Prognose des ersten Fensters.
        first = rows[0] if rows else None
        parts = []
        if first is not None:
            remaining = texte.countdown(first.resets_at, utcnow())
            if remaining:
                parts.append(self.t("resets_in", zeit=remaining))
            forecast = texte.pace(first)
            if forecast:
                parts.append(forecast)
        if parts:
            render.draw_text_at(image, " · ".join(parts), x=margin, y=height - z.px(18, factor),
                                size=z.px(10, factor), color=z.MUTED,
                                max_width=width - 2 * margin)
        return self._finish(image, view, ctx)

    def _segment_rows(self, provider: ProviderUsage) -> list[UsageWindow]:
        """Session und Woche. Hat ein Anbieter keines von beiden, seine ersten zwei Fenster."""
        preferred = [w for kind in ("session", "weekly") if (w := provider.window(kind))]
        if preferred:
            return preferred
        return [w for w in provider.windows if w.used_pct is not None][:2]

    def _segment_credit_line(self, image, provider: ProviderUsage, ctx, *, y: int):
        render = self.services.render
        factor = z.scale(ctx.size, base=100)
        margin = z.px(10, factor)
        if provider.credits is not None:
            value, unit = texte.credits(*provider.credits)
            text = f"{self.t('credits')}: {value} {unit}".strip()
        elif provider.cost_today_usd is not None or provider.cost_30d_usd is not None:
            text = self._cost_text(provider)
            if provider.cost_estimated:
                render.draw_text_at(image, self.t("estimated"), x=margin, y=y + z.px(20, factor),
                                    size=z.px(10, factor), color=z.MUTED,
                                    max_width=image.width - 2 * margin)
        else:
            text = self.t("not_reported")
        render.draw_text_at(image, text, x=margin, y=y, size=z.px(14, factor),
                            color=ctx.appearance.label_color, bold=True,
                            max_width=image.width - 2 * margin)

    def _render_segment_message(self, image, view: View, ctx):
        render = self.services.render
        width, height = ctx.size
        factor = z.scale(ctx.size, base=100)
        color = MESSAGE_COLOR.get(view.state, z.MUTED)
        icon = self._state_icon(ctx, view.state, size=z.px(40, factor), color=color)
        left = z.px(12, factor)
        image.alpha_composite(icon, (left, (height - icon.height) // 2))
        x = left + icon.width + z.px(12, factor)
        name = view.provider.name if view.provider else view.title
        if name:
            render.draw_text_at(image, name, x=x, y=z.px(14, factor), size=z.px(13, factor),
                                color=ctx.appearance.label_color, bold=True,
                                max_width=width - x - z.px(8, factor))
        # Im Segment ist genug Platz für die eigentliche Fehlermeldung.
        detail = view.provider.error if view.provider and view.provider.error else view.message
        for i, line in enumerate(z.wrap(detail or "", z.px(10, factor), width - x - z.px(8, factor))):
            render.draw_text_at(image, line, x=x, y=z.px(38 + i * 14, factor),
                                size=z.px(10, factor), color=color)
        return image

    def _render_detail(self, view: View, settings: dict, ctx):
        """Detailansicht nach Tippen mit allen Fenstern, Guthaben und Kosten."""
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size
        factor = z.scale(ctx.size, base=100)
        provider = view.provider
        margin = z.px(8, factor)
        warn, crit = self._thresholds(settings)

        render.draw_text_at(image, provider.name, x=margin, y=z.px(4, factor),
                            size=z.px(11, factor), color=z.SOFT, bold=True,
                            max_width=width - 2 * margin)

        lines = []
        for window in provider.windows:
            if window.used_pct is None:
                continue
            remaining = texte.countdown(window.resets_at, utcnow()) or ""
            lines.append((texte.window_label(window.kind, window.label),
                          texte.percent(window.used_pct), remaining,
                          self._color(level(window.used_pct, warn, crit))))
        extra = []
        if provider.credits is not None:
            value, unit = texte.credits(*provider.credits)
            extra.append(f"{self.t('credits')} {value} {unit}".strip())
        has_cost = provider.cost_today_usd is not None or provider.cost_30d_usd is not None
        if has_cost:
            extra.append(self._cost_text(provider))

        room = 4 if not extra else 3
        row_h = z.px(16, factor)
        for i, (label, pct, remaining, color) in enumerate(lines[:room]):
            y = z.px(20, factor) + i * row_h
            render.draw_text_at(image, label, x=margin, y=y, size=z.px(10, factor), color=z.SOFT,
                                max_width=z.px(86, factor))
            render.draw_text_at(image, pct, x=z.px(132, factor), y=y, size=z.px(11, factor),
                                color=color, bold=True, align="right")
            render.draw_text_at(image, remaining, x=width - margin, y=y, size=z.px(10, factor),
                                color=z.MUTED, align="right")
        if extra:
            if has_cost and provider.cost_estimated:
                # Die Kennzeichnung passt nicht mit in die Zeile, sie steht darüber.
                render.draw_text_at(image, self.t("estimated"), x=margin,
                                    y=height - z.px(29, factor), size=z.px(9, factor),
                                    color=z.MUTED, max_width=width - 2 * margin)
            render.draw_text_at(image, " · ".join(extra), x=margin, y=height - z.px(16, factor),
                                size=z.px(10, factor), color=ctx.appearance.label_color,
                                max_width=width - 2 * margin)
        return self._finish(image, view, ctx)

    def _cost_text(self, provider: ProviderUsage) -> str:
        """„Heute $1.04 · 30 Tage $18.22“, fehlende Teile weggelassen."""
        parts = []
        if provider.cost_today_usd is not None:
            parts.append(f"{self.t('cost_today')} {texte.money(provider.cost_today_usd)}")
        if provider.cost_30d_usd is not None:
            parts.append(f"{self.t('cost_30d')} {texte.money(provider.cost_30d_usd)}")
        return " · ".join(parts)

    # ======================================================================
    # Benachrichtigung
    # ======================================================================

    async def _check_alerts(self):
        if not self._config_bool("notify", False):
            return
        _, crit = self._thresholds()
        for provider, window in self.alerts.check(self._providers(), crit):
            title = self.t(
                "notify_title",
                name=provider.name,
                label=texte.window_label(window.kind, window.label),
                pct=texte.percent(window.used_pct),
            )
            remaining = texte.countdown(window.resets_at, utcnow())
            body = self.t("notify_body", zeit=remaining) if remaining else ""
            await self._desktop_notify(title, body)

    async def _desktop_notify(self, title: str, body: str) -> None:
        """Schickt eine Meldung über ``org.freedesktop.Notifications``. Das versteht jeder Benachrichtigungsdienst."""
        try:
            from dbus_next.aio import MessageBus

            bus = await MessageBus().connect()
            try:
                introspection = await bus.introspect(
                    "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
                )
                proxy = bus.get_proxy_object(
                    "org.freedesktop.Notifications", "/org/freedesktop/Notifications", introspection
                )
                interface = proxy.get_interface("org.freedesktop.Notifications")
                await interface.call_notify("DECK//SWITCH", 0, "dialog-warning", title, body,
                                            [], {}, 10000)
            finally:
                bus.disconnect()
        except Exception as exc:  # noqa: BLE001 - ohne Benachrichtigung läuft das Plugin weiter
            self.log.warning("Desktop-Benachrichtigung ging nicht raus: %s", exc)

    # ======================================================================
    # GUI
    # ======================================================================

    def get_status(self):
        snapshot = self.poller.snapshot
        codexbar_error = self.poller.codexbar_error
        if snapshot is None:
            error = self.poller.error or codexbar_error
            return {"connected": False,
                    "detail": str(error) if error else self.t("status_no_data")}
        count = len(snapshot.providers)
        if snapshot.source == "claude":
            row = snapshot.providers[0] if snapshot.providers else None
            if row is not None and row.error_kind == "login_missing":
                return {"connected": False, "detail": row.error}
            reason = f". {codexbar_error}" if codexbar_error else ""
            return {"connected": True, "detail": self.t("status_claude_direct") + reason}
        detail = self.t("status_codexbar", version=snapshot.version or "", count=count).replace("  ", " ")
        if snapshot.warning:
            detail += f" · {snapshot.warning}"
        if self.poller.error or codexbar_error:
            detail += " · " + self.t("status_last_poll", error=self.poller.error or codexbar_error)
        return {"connected": codexbar_error is None, "detail": detail}

    def get_dynamic_options(self, source, context=None):
        if source != "providers":
            return []
        if self.poller.snapshot is None:
            # Läuft im Worker-Thread, ein blockierender Abruf ist hier erlaubt.
            self.poller.poll(self._poll_settings())
        options = [{"value": p.id, "label": p.name} for p in self._providers()]
        current = (context or {}).get("provider")
        if current and current not in {o["value"] for o in options}:
            options.append({"value": current, "label": f"{current} ({self.t('not_reported')})"})
        return options

    async def gui_command(self, command, payload):
        if command == "refresh":
            await self.refresh()
            return {"ok": True, **(self.get_status() or {})}
        if command == "status":
            return self.get_status() or {}
        raise NotImplementedError(self.t("unknown_command", command=command))
