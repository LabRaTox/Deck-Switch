"""Prüft die Gesten-Erkennung auf dem Touchstrip mit kontrollierter Uhr.

Hintergrund: Das Gerät meldet einen durchgehenden Wisch in Teilstrecken von
je rund 40–120 px. Diese Tests decken das Zusammenfassen der Teilstrecken,
Richtungswechsel, Pausen zwischen Gesten und die Sperre gegen mehrfaches
Weiterblättern ab.

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/swipe_gesture_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio, sys, time as timemod
from deckswitch.runtime import Runtime
from deckswitch.config import Page
FAILS=[]
def check(n,c,d=""):
    print(("  ✔ " if c else "  ✘ ")+n+(f"  ({d})" if d else ""))
    if not c: FAILS.append(n)
async def main():
    rt=Runtime(); await rt.start(); await asyncio.sleep(0.3)
    # Wischen gehört dem einzelnen Deck — der Zustand liegt dort.
    deck=rt.primary
    print("  Schwelle:", deck.settings.swipe_min_distance, "px")
    p=deck.profile; root=p.root_page()
    b=Page(name="B",parent_id=None); c=Page(name="C",parent_id=None)
    p.pages[b.id]=b; p.pages[c.id]=c
    deck.navigate(root.id)
    clock=[1000.0]; real=timemod.monotonic
    timemod.monotonic=lambda: clock[0]
    def drag(dx,dy=0,x=300): return {"x":x,"y":50,"x_out":x+dx,"y_out":50+dy}
    def reset():
        deck._swipe_distance=0; deck._swipe_last_at=clock[0]; deck._swipe_blocked_until=0
    try:
        print("\n== Teilstrecken summieren sich ==")
        reset(); start=deck.current_page_id()
        for part in (-25,-20):
            deck._handle_swipe(drag(part)); clock[0]+=0.1
        check("nach 45 px noch kein Wechsel", deck.current_page_id()==start)
        deck._handle_swipe(drag(-20))
        check("ab 65 px wechselt die Seite", deck.current_page_id()!=start)

        print("\n== Einzeln zu kurze Teilstrecken ==")
        clock[0]+=2; reset(); start=deck.current_page_id()
        for _ in range(4):
            deck._handle_swipe(drag(-15)); clock[0]+=0.08
        check("4×15 px lösen zusammen aus", deck.current_page_id()!=start)

        print("\n== Richtungswechsel ==")
        clock[0]+=2; reset()
        deck._handle_swipe(drag(-60)); clock[0]+=0.1
        left=deck.current_page_id()
        deck._swipe_blocked_until=0
        deck._handle_swipe(drag(+60))
        check("Wisch zurück wechselt zurück", deck.current_page_id()!=left)

        print("\n== Pause trennt Gesten ==")
        clock[0]+=2; reset(); start=deck.current_page_id()
        deck._handle_swipe(drag(-30)); clock[0]+=1.0
        deck._handle_swipe(drag(-30))
        check("mit Pause dazwischen kein Wechsel", deck.current_page_id()==start,
              "zwei getrennte kurze Berührungen")

        print("\n== Sperre gegen Mehrfachblättern ==")
        clock[0]+=2; reset()
        deck._handle_swipe(drag(-80)); first=deck.current_page_id()
        clock[0]+=0.1; deck._handle_swipe(drag(-80))
        clock[0]+=0.1; deck._handle_swipe(drag(-80))
        check("Rest des Wischs blättert nicht weiter", deck.current_page_id()==first)
        clock[0]+=1.0; reset()
        deck._handle_swipe(drag(-80))
        check("nach der Sperre geht es wieder", deck.current_page_id()!=first)

        print("\n== Nichts landet beim Plugin ==")
        clock[0]+=2; reset()
        check("winzige Teilstrecke konsumiert", deck._handle_swipe(drag(-5)) is True)
        check("senkrechtes Streifen konsumiert", deck._handle_swipe(drag(3,dy=40)) is True)

        print("\n== Senkrecht blättert nie ==")
        clock[0]+=2; reset(); start=deck.current_page_id()
        for _ in range(5):
            deck._handle_swipe(drag(5,dy=60)); clock[0]+=0.1
        check("senkrechte Bewegung ohne Wechsel", deck.current_page_id()==start)

        print("\n== Richtung ==")
        order=[x.id for x in rt.sibling_pages()]
        clock[0]+=2; deck.navigate(order[0]); reset()
        deck._handle_swipe(drag(-80))
        check("nach links → nächste Seite", deck.current_page_id()==order[1])
        clock[0]+=2; reset()
        deck._handle_swipe(drag(+80))
        check("nach rechts → vorherige Seite", deck.current_page_id()==order[0])

        print("\n== Umbruch am Ende ==")
        clock[0]+=2; deck.navigate(order[-1]); reset()
        deck._handle_swipe(drag(-80))
        check("wrap=True springt zur ersten Seite", deck.current_page_id()==order[0])
        deck.settings.swipe_wraps=False
        clock[0]+=2; deck.navigate(order[-1]); reset()
        deck._handle_swipe(drag(-80))
        check("wrap=False bleibt am Ende", deck.current_page_id()==order[-1])
        deck.settings.swipe_wraps=True

        print("\n== Abschaltbar ==")
        deck.settings.swipe_switches_page=False
        clock[0]+=2; deck.navigate(order[0]); reset()
        consumed=deck._handle_swipe(drag(-200))
        check("deaktiviert wechselt nicht", deck.current_page_id()==order[0])
        check("und gibt die Geste ans Plugin weiter", consumed is False)
        deck.settings.swipe_switches_page=True
    finally:
        timemod.monotonic=real

    print("\n== Tippen erreicht weiterhin das Plugin ==")
    import pathlib
    from deckswitch.plugins.base import ActionPlugin, Manifest
    from deckswitch.plugins.loader import LoadedPlugin
    from deckswitch.config import Slot, Appearance
    taps=[]
    m=Manifest.model_validate({"id":"pr","name":"P","type":"action","entry":"x.py",
        "class":"P","actions":[{"id":"a","name":"A","inputs":["dial"]}]})
    class P(ActionPlugin):
        def on_touch(self, action_id, settings, x, y, ctx): taps.append((x,y))
    rt.registry.plugins["pr"]=LoadedPlugin(manifest=m,directory=pathlib.Path("."),
        instance=P(m,rt._services_for(pathlib.Path("."))),builtin=True,enabled=True)
    rt.config.active_profile().pages[deck.current_page_id()].dials[1]=Slot(
        plugin_id="pr",action_id="a",appearance=Appearance())
    await rt._handle_touch("short", {"x":250,"y":40})
    check("Tippen kommt segment-relativ an", taps==[(50,40)], str(taps))
    taps.clear()
    await rt._handle_touch("drag", {"x":600,"y":50,"x_out":100,"y_out":50})
    check("Wischen erreicht das Plugin nicht", taps==[], str(taps))
    await rt.stop()
    print()
    print("FEHLGESCHLAGEN: "+", ".join(FAILS) if FAILS else "Alle Prüfungen bestanden.")
    sys.exit(1 if FAILS else 0)
asyncio.run(main())
