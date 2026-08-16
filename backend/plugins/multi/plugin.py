"""Mehrere Aktionen auf einer Taste.

Zwei Spielarten, wie bei Elgato:

* **Multi-Aktion** — eine Kette, die von oben nach unten abläuft. Auf Wunsch
  in Schleife, dann hält ein zweiter Druck sie an.
* **Umschalter** — zwei Ketten. Der erste Druck läuft die eine ab, der
  nächste die andere. Die Taste weiß, wo sie steht, und zeigt es auch.

Die Schritte selbst stehen nicht in den Plugin-Einstellungen, sondern im
Datenmodell der Belegung (``Slot.steps``). Der Grund: Ein Schritt ist ein
*Verweis auf eine Action* und damit dasselbe wie eine Belegung. So kann die
App beim Entfernen eines Plugins auch die Schritte finden, die darauf
zeigen — in einem undurchsichtigen Einstellungs-Dictionary könnte sie das
nicht.
"""

from __future__ import annotations

from deckswitch.plugins.base import ActionPlugin


class MultiPlugin(ActionPlugin):
    # -- Eingaben ----------------------------------------------------------

    async def on_key_down(self, action_id, settings, ctx):
        await self._activate(action_id, settings, ctx)

    async def on_dial_push(self, action_id, settings, ctx):
        await self._activate(action_id, settings, ctx)

    async def _activate(self, action_id, settings, ctx) -> None:
        # Über ``ctx``: Die Kette gehört dem Deck, auf dem sie gedrückt wurde.
        runtime = ctx.services.runtime
        slot = ctx.slot

        # Läuft die Kette gerade, hält der Druck sie an. Ohne das wäre eine
        # Wiederholschleife nicht mehr loszuwerden.
        if runtime.steps_running(ctx):
            runtime.stop_steps(ctx)
            ctx.request_redraw()
            return

        if action_id == "switch":
            # Erst umschalten, dann laufen lassen: Die Taste soll sofort den
            # neuen Zustand zeigen, auch wenn die Kette noch arbeitet.
            forward = not slot.toggled
            steps = slot.steps if forward else slot.steps_off
            slot.toggled = forward
            runtime.save_config()
            ctx.request_redraw()
            if not steps:
                self.notify_info(
                    "Für diese Richtung sind keine Schritte hinterlegt"
                )
                return
            await runtime.run_steps(steps, ctx)
            return

        if not slot.steps:
            self.notify_error("Diese Multi-Aktion hat noch keine Schritte")
            return

        await runtime.run_steps(
            slot.steps, ctx, repeat=bool(ctx.setting("repeat", slot.repeat))
        )
        ctx.request_redraw()

    # -- Darstellung -------------------------------------------------------

    def get_state(self, action_id, settings, ctx):
        if action_id == "switch":
            return "on" if ctx.slot.toggled else "off"
        return "running" if ctx.services.runtime.steps_running(ctx) else "default"

    def get_label(self, action_id, settings, ctx):
        # Ohne eigene Beschriftung wenigstens die Zahl der Schritte zeigen —
        # eine leere Kette sieht man der Taste sonst nicht an.
        if ctx.appearance.label_text:
            return None
        count = len([s for s in ctx.slot.steps if s.enabled])
        if action_id == "switch":
            other = len([s for s in ctx.slot.steps_off if s.enabled])
            return f"{count} / {other}"
        return f"{count} Schritte" if count != 1 else "1 Schritt"
