# Die Oberfläche

React mit TypeScript, gebaut mit Vite. Im Betrieb läuft das Ganze als
Tauri-Fenster, das den WebView des Systems benutzt.

## Entwickeln

Das Backend muss laufen, sonst zeigt die Oberfläche nur „Backend nicht
erreichbar":

```sh
../scripts/start-backend.sh   # in einem zweiten Terminal
npm install
npm run dev                   # http://127.0.0.1:5173
```

Der Dev-Server auf Port 5173 spricht mit dem Backend auf 8770. Läuft dein
Backend woanders, sag es über eine `.env.local`:

```
VITE_BACKEND_URL=http://127.0.0.1:8790
```

Das Backend lässt nur bekannte Herkünfte an seine API. Die Vite-Ports 5173,
5174 und 4173 stehen dort nur, wenn du es mit `--dev` startest.

## Bauen

```sh
npm run build     # nach dist/, von dort liefert das Backend die Oberfläche aus
```

## Wo was liegt

| | |
| --- | --- |
| `src/api/client.ts` | alle Aufrufe ans Backend |
| `src/store.ts` | der geteilte Zustand (zustand) |
| `src/components/` | die Ansichten |
| `src/i18n/` | Deutsch und Englisch |
| `src/lib/` | Kleinigkeiten, die mehrere Ansichten brauchen |

Gezeichnet wird nichts hier: Tastenbilder kommen fertig aus dem Backend. Die
Oberfläche zeigt genau das, was auch auf dem Gerät steht.
