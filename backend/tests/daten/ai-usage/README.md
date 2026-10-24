# Testdaten für das Plugin „KI-Nutzung“

Die `snapshot-*.json` haben das Format von `GET /dashboard/v1/snapshot`
(schemaVersion 1), so wie es CodexBar in `docs/dashboard-api.md`
beschreibt. Die Zahlen sind Prüfeingaben und keine Messwerte. Sie sind so
gewählt, dass jede Schwelle einmal getroffen wird.

| Datei | Fall |
| --- | --- |
| `snapshot-ok.json` | drei Anbieter mit vollständigen Daten, je eine Schwelle normal, Warnung, kritisch |
| `snapshot-teilfehler.json` | ein Anbieter mit Fehler, einer mit abgelaufenem Login, einer ohne Fehler |
| `snapshot-veraltet.json` | `generatedAt` liegt eine Stunde zurück |
| `snapshot-leer.json` | gültiger Snapshot ohne aktivierten Anbieter |
| `snapshot-schema2.json` | `schemaVersion` 2, ergibt eine Warnung und keinen Abbruch |
| `usage-pace.json` | Antworten von `GET /usage?provider=<id>` mit `pace` je Anbieter |

Echte Antworten von CodexBar 0.80.0 unter Linux, ohne E-Mail-Adressen und
mit `~` statt Heimatverzeichnis:

| Datei | Inhalt |
| --- | --- |
| `snapshot-echt.json` | Snapshot mit Claude (Werte) und Codex (nicht eingerichtet) |
| `usage-echt.json` | `/usage` für Claude (mit Pace) und Codex (Fehler) |
| `cost-echt.json` | `/cost` für Claude, gekürzt auf Herkunft und Summen: `provenance` ist `listPriceEstimate` |
| `fehlertexte-echt.json` | 18 verschiedene Fehlermeldungen, je mit der Einordnung, die die Taste zeigen soll (`login_missing` wenn Anmelden, Schlüssel oder Cookie hilft, sonst `error`) |

`claude-oauth-usage.json` ist eine echte Antwort von
`https://api.anthropic.com/api/oauth/usage`. Diesen Endpoint fragt das
Plugin ab, wenn CodexBar nicht läuft. Die Datei enthält weder eine
E-Mail-Adresse noch einen Token.
