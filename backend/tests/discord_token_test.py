"""Prüft die Ablage und Erneuerung des Discord-Tokens.

Discord stellt das Token für 7 Tage aus und gibt bei jeder Erneuerung ein
neues ``refresh_token`` heraus; das alte ist danach ungültig (gemessen am
2026-10-24). Diese Suite spielt das ohne Netz nach: Die Erneuerung wird
durch eine Attrappe ersetzt, die sich genauso verhält.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/discord_token_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio, json, pathlib, stat, sys, threading, time

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "discord"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)
from deckswitch.plugins.base import Manifest, Services
from deckswitch.config import default_config
from _pluginlader import lade

dcmod = lade(PLUGIN_DIR)
ipcmod = sys.modules[dcmod.DiscordIpc.__module__]

FAILS = []
def check(n, c, d=""):
    print(("  ✔ " if c else "  ✘ ") + n + (f"  ({d})" if d else ""))
    if not c: FAILS.append(n)

TAG = 7 * 24 * 3600

class Discord:
    """Verhält sich wie Discords Token-Endpunkt: jedes refresh_token gilt einmal."""
    def __init__(self):
        self.gueltig = {"r1"}
        self.aufrufe = 0
        self.zaehler = 1
        self.sperre = threading.Lock()
    def erneuere(self, client_id, secret, refresh):
        with self.sperre:
            self.aufrufe += 1
            time.sleep(0.05)
            if refresh not in self.gueltig:
                raise ipcmod.DiscordIpcError("invalid_grant")
            self.gueltig.discard(refresh)
            self.zaehler += 1
            neu = f"r{self.zaehler}"
            self.gueltig.add(neu)
            return {"access_token": f"a{self.zaehler}", "refresh_token": neu,
                    "expires_in": TAG, "token_type": "Bearer", "scope": "rpc"}

config = default_config()
config.plugin_settings["discord"] = {"client_id": "123", "client_secret": "geheim"}
services = Services(audio=None, icons=None, render=None, runtime=None,
                    config=config, plugin_dir=PLUGIN_DIR)
manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))

def lege_ab(**felder):
    dcmod.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    dcmod.TOKEN_FILE.write_text(json.dumps({"client_id": "123", **felder}))


async def main():
    plugin = dcmod.DiscordPlugin(manifest, services)

    print("== Ablage ==")
    token = dcmod._store_token("123", {"access_token": "a1", "refresh_token": "r1", "expires_in": TAG})
    gelesen = dcmod._load_token("123")
    check("die ganze Antwort wird gespeichert",
          gelesen["access_token"] == "a1" and gelesen["refresh_token"] == "r1", str(gelesen))
    check("mit Ablaufzeit statt Dauer", abs(gelesen["expires_at"] - (time.time() + TAG)) < 5)
    check("die Datei ist nur für den Besitzer lesbar",
          stat.S_IMODE(dcmod.TOKEN_FILE.stat().st_mode) == 0o600,
          oct(stat.S_IMODE(dcmod.TOKEN_FILE.stat().st_mode)))
    check("eine fremde Application-ID gilt nicht", dcmod._load_token("999") is None)

    lege_ab(access_token="alt")
    alt = dcmod._load_token("123")
    check("eine alte Datei ohne refresh_token wird gelesen",
          alt == {"access_token": "alt", "refresh_token": "", "expires_at": 0.0}, str(alt))

    print("\n== Erneuerung ==")
    discord = Discord()
    dcmod.refresh_token = discord.erneuere

    dcmod._store_token("123", {"access_token": "a1", "refresh_token": "r1", "expires_in": TAG})
    frisch = await plugin._fresh_token("123")
    check("weit vor Ablauf wird nicht erneuert",
          frisch["access_token"] == "a1" and discord.aufrufe == 0)

    lege_ab(access_token="a1", refresh_token="r1", expires_at=time.time() + 3600)
    frisch = await plugin._fresh_token("123")
    check("eine Stunde vor Ablauf wird erneuert", frisch["access_token"] == "a2", str(frisch))
    check("das neue refresh_token steht sofort in der Datei",
          dcmod._load_token("123")["refresh_token"] == "r2")

    lege_ab(access_token="a2", refresh_token="r2", expires_at=time.time() + 60)
    discord.aufrufe = 0
    ergebnisse = await asyncio.gather(*(plugin._fresh_token("123") for _ in range(4)))
    check("vier gleichzeitige Anfragen erneuern nur einmal", discord.aufrufe == 1,
          f"{discord.aufrufe} Aufrufe")
    check("und alle bekommen dasselbe gültige Token",
          {e["access_token"] for e in ergebnisse} == {"a3"},
          str({e["access_token"] for e in ergebnisse}))

    lege_ab(access_token="a3", refresh_token="verbraucht", expires_at=time.time() + 60)
    frisch = await plugin._fresh_token("123")
    check("lehnt Discord ab, bleibt das alte Token stehen",
          frisch is not None and frisch["access_token"] == "a3")
    check("erzwungen gibt es dann keines", await plugin._fresh_token("123", force=True) is None)

    lege_ab(access_token="alt")
    discord.aufrufe = 0
    frisch = await plugin._fresh_token("123", force=True)
    check("ohne refresh_token wird nichts versucht",
          frisch["access_token"] == "alt" and discord.aufrufe == 0)

    config.plugin_settings["discord"]["client_secret"] = ""
    lege_ab(access_token="a3", refresh_token=sorted(discord.gueltig)[0], expires_at=time.time() + 60)
    frisch = await plugin._fresh_token("123")
    check("ohne Client-Secret bleibt es beim gespeicherten Token",
          frisch["access_token"] == "a3" and discord.aufrufe == 0)


asyncio.run(main())
print()
if FAILS:
    print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS)); sys.exit(1)
print("Alle Prüfungen bestanden.")
