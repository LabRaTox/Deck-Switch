#!/usr/bin/env python3
"""Nimmt ``streamdeck://``-Adressen entgegen und reicht sie ans Backend.

Wird vom Desktop aufgerufen, wenn im Browser ein ``streamdeck://``-Link
angeklickt wird. Der Handler installiert selbst nichts — er meldet die
Anfrage nur beim laufenden Backend an, das sie zur Bestätigung in der GUI
anzeigt. Ohne diesen Zwischenschritt könnte ein beliebiger Link auf einer
beliebigen Webseite Code auf dem Rechner installieren.

Unterstützte Adressen:

    streamdeck://install?url=https://example.com/mein-plugin.zip
    streamdeck://install?url=https://…/weather-1.0.0.zip&sha256=a1b2c3…

Die Prüfsumme ist freiwillig, aber dringend zu empfehlen: Ohne sie
installiert die App, was auch immer unter der Adresse liegt.

Installation siehe scripts/install-url-handler.sh
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BACKEND = "http://127.0.0.1:8770"
TIMEOUT_S = 10


def backend_url() -> str:
    """Adresse des Backends — notfalls aus der Config des Nutzers."""
    if os.environ.get("STREAMDECK_BACKEND"):
        return os.environ["STREAMDECK_BACKEND"].rstrip("/")

    config = (
        os.environ.get("XDG_CONFIG_HOME")
        or os.path.join(os.path.expanduser("~"), ".config")
    )
    path = os.path.join(config, "deckswitch", "config.json")
    try:
        with open(path, encoding="utf-8") as handle:
            app = json.load(handle).get("app", {})
        return f"http://{app.get('host', '127.0.0.1')}:{app.get('port', 8770)}"
    except (OSError, ValueError, KeyError):
        return DEFAULT_BACKEND


def notify(summary: str, body: str, urgency: str = "normal") -> None:
    """Rückmeldung auf den Desktop — der Handler hat kein eigenes Fenster."""
    try:
        subprocess.run(
            ["notify-send", "-a", "Stream Deck", "-u", urgency, summary, body],
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        print(f"{summary}: {body}", file=sys.stderr)


def post(path: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        backend_url() + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    parsed = urllib.parse.urlparse(argv[1])
    if parsed.scheme != "streamdeck":
        notify("Stream Deck", f"Unbekanntes Schema: {parsed.scheme}", "critical")
        return 2

    action = (parsed.netloc or parsed.path.lstrip("/")).strip("/")
    params = urllib.parse.parse_qs(parsed.query)

    if action != "install":
        notify("Stream Deck", f"Unbekannte Aktion: {action or '—'}", "critical")
        return 2

    target = (params.get("url") or [""])[0]
    if not target:
        notify("Stream Deck", "In der Adresse fehlt der Parameter 'url'", "critical")
        return 2
    if not target.lower().startswith(("http://", "https://")):
        notify("Stream Deck", "Nur http(s)-Adressen werden angenommen", "critical")
        return 2

    try:
        status, body = post(
            "/api/plugins/install-request",
            {
                "url": target,
                "origin": (params.get("origin") or [""])[0],
                # Der Store hängt die erwartete Prüfsumme an den Link. Wir
                # geben sie unverändert weiter — geprüft wird sie erst
                # dort, wo auch heruntergeladen wird.
                "sha256": (params.get("sha256") or [""])[0],
            },
        )
    except urllib.error.URLError:
        notify(
            "Stream Deck",
            "Das Backend läuft nicht — bitte starten und den Link erneut anklicken.",
            "critical",
        )
        return 1

    if status >= 400:
        notify("Stream Deck", body.get("detail", "Anfrage abgelehnt"), "critical")
        return 1

    host = urllib.parse.urlparse(target).netloc
    notify(
        "Plugin-Installation angefragt",
        f"Von {host} — in der Stream-Deck-Oberfläche bestätigen.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
