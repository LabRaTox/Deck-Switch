"""Prüft die Gesten-Erkennung auf dem Touchstrip mit kontrollierter Uhr.

Hintergrund: Das Gerät meldet einen durchgehenden Wisch in Teilstrecken von
je rund 40–120 px. Diese Tests decken das Zusammenfassen der Teilstrecken,
Richtungswechsel, Pausen zwischen Gesten und die Sperre gegen mehrfaches
Weiterblättern ab.

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/swipe_gesture_test.py
"""
import asyncio, sys, time as timemod
from deckswitch.runtime import Runtime
from deckswitch.config import Page
FAILS=[]
def check(n,c,d=""):
    print(("  ✔ " if c else "  ✘ ")+n+(f"  ({d})" if d else ""))
    if not c: FAILS.append(n)
async def main():
    rt=Runtime(); await rt.start(); await asyncio.sleep(0.3)
    print("  Schwelle:", rt.config.device.swipe_min_distance, "px")
    p=rt.config.active_profile(); root=p.root_page()
    b=Page(name="B",parent_id=None); c=Page(name="C",parent_id=None)
    p.pages[b.id]=b; p.pages[c.id]=c
    rt.navigate(root.id)
    clock=[1000.0]; real=timemod.monotonic
    timemod.monotonic=lambda: clock[0]
    def drag(dx,dy=0,x=300): return {"x":x,"y":50,"x_out":x+dx,"y_out":50+dy}
    def reset():
        rt._swipe_distance=0; rt._swipe_last_at=clock[0]; rt._swipe_blocked_until=0
    try:
        print("\n== Teilstrecken summieren sich ==")
        reset(); start=rt.current_page_id()
        for part in (-25,-20):
            rt._handle_swipe(drag(part)); clock[0]+=0.1
        check("nach 45 px noch kein Wechsel", rt.current_page_id()==start)
        rt._handle_swipe(drag(-20))
        check("ab 65 px wechselt die Seite", rt.current_page_id()!=start)

        print("\n== Einzeln zu kurze Teilstrecken ==")
        clock[0]+=2; reset(); start=rt.current_page_id()
        for _ in range(4):
            rt._handle_swipe(drag(-15)); clock[0]+=0.08
        check("4×15 px lösen zusammen aus", rt.current_page_id()!=start)

        print("\n== Richtungswechsel ==")
        clock[0]+=2; reset()
        rt._handle_swipe(drag(-60)); clock[0]+=0.1
        left=rt.current_page_id()
        rt._swipe_blocked_until=0
        rt._handle_swipe(drag(+60))
        check("Wisch zurück wechselt zurück", rt.current_page_id()!=left)

        print("\n== Pause trennt Gesten ==")
        clock[0]+=2; reset(); start=rt.current_page_id()
        rt._handle_swipe(drag(-30)); clock[0]+=1.0
        rt._handle_swipe(drag(-30))
        check("mit Pause dazwischen kein Wechsel", rt.current_page_id()==start,
              "zwei getrennte kurze Berührungen")

        print("\n== Sperre gegen Mehrfachblättern ==")
        clock[0]+=2; reset()
        rt._handle_swipe(drag(-80)); first=rt.current_page_id()
        clock[0]+=0.1; rt._handle_swipe(drag(-80))
        clock[0]+=0.1; rt._handle_swipe(drag(-80))
        check("Rest des Wischs blättert nicht weiter", rt.current_page_id()==first)
        clock[0]+=1.0; reset()
        rt._handle_swipe(drag(-80))
        check("nach der Sperre geht es wieder", rt.current_page_id()!=first)

        print("\n== Nichts landet beim Plugin ==")
        clock[0]+=2; reset()
        check("winzige Teilstrecke konsumiert", rt._handle_swipe(drag(-5)) is True)
        check("senkrechtes Streifen konsumiert", rt._handle_swipe(drag(3,dy=40)) is True)

        print("\n== Senkrecht blättert nie ==")
        clock[0]+=2; reset(); start=rt.current_page_id()
        for _ in range(5):
            rt._handle_swipe(drag(5,dy=60)); clock[0]+=0.1
        check("senkrechte Bewegung ohne Wechsel", rt.current_page_id()==start)

        print("\n== Richtung ==")
        order=[x.id for x in rt.sibling_pages()]
        clock[0]+=2; rt.navigate(order[0]); reset()
        rt._handle_swipe(drag(-80))
        check("nach links → nächste Seite", rt.current_page_id()==order[1])
        clock[0]+=2; reset()
        rt._handle_swipe(drag(+80))
        check("nach rechts → vorherige Seite", rt.current_page_id()==order[0])

        print("\n== Umbruch am Ende ==")
        clock[0]+=2; rt.navigate(order[-1]); reset()
        rt._handle_swipe(drag(-80))
        check("wrap=True springt zur ersten Seite", rt.current_page_id()==order[0])
        rt.config.device.swipe_wraps=False
        clock[0]+=2; rt.navigate(order[-1]); reset()
        rt._handle_swipe(drag(-80))
        check("wrap=False bleibt am Ende", rt.current_page_id()==order[-1])
        rt.config.device.swipe_wraps=True

        print("\n== Abschaltbar ==")
        rt.config.device.swipe_switches_page=False
        clock[0]+=2; rt.navigate(order[0]); reset()
        consumed=rt._handle_swipe(drag(-200))
        check("deaktiviert wechselt nicht", rt.current_page_id()==order[0])
        check("und gibt die Geste ans Plugin weiter", consumed is False)
        rt.config.device.swipe_switches_page=True
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
    rt.config.active_profile().pages[rt.current_page_id()].dials[1]=Slot(
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
