// Prüf-Plugin nach Elgato-Bauart: anmelden, zählen, zurückmelden.
// Nutzt den in Node eingebauten WebSocket-Client, damit kein Paket nötig ist.
const args = {};
for (let i = 2; i < process.argv.length; i += 2) args[process.argv[i]] = process.argv[i + 1];

const ws = new WebSocket("ws://127.0.0.1:" + args["-port"]);
const zaehler = {};

// Ein winziges PNG, damit setImage etwas Echtes überträgt.
const PNG = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8Dwn4GBgYEJRIAAAA8AAyEB3TgAAAAASUVORK5CYII=";

const sende = (o) => ws.send(JSON.stringify(o));

ws.addEventListener("open", () => {
  sende({ event: args["-registerEvent"], uuid: args["-pluginUUID"] });
  console.log("angemeldet als " + args["-pluginUUID"]);
});

ws.addEventListener("message", (ereignis) => {
  const n = JSON.parse(ereignis.data);
  const ctx = n.context;
  console.log("empfangen: " + n.event);

  if (n.event === "willAppear") {
    sende({ event: "setTitle", context: ctx, payload: { title: "bereit" } });
  }
  if (n.event === "keyDown") {
    zaehler[ctx] = (zaehler[ctx] || 0) + 1;
    sende({ event: "setTitle", context: ctx, payload: { title: String(zaehler[ctx]) } });
    sende({ event: "setImage", context: ctx, payload: { image: "data:image/png;base64," + PNG } });
    sende({ event: "setState", context: ctx, payload: { state: zaehler[ctx] % 2 } });
    sende({ event: "setSettings", context: ctx, payload: { drucke: zaehler[ctx] } });
    sende({ event: "showOk", context: ctx });
  }
  if (n.event === "propertyInspectorDidAppear") {
    sende({ event: "setTitle", context: ctx, payload: { title: "PI offen" } });
  }
  if (n.event === "sendToPlugin") {
    // Zurück an die Seite — so lässt sich der ganze Weg prüfen.
    sende({ event: "sendToPropertyInspector", context: ctx,
            payload: { echo: n.payload } });
  }
  if (n.event === "didReceiveSettings") {
    sende({ event: "setTitle", context: ctx,
            payload: { title: "S:" + JSON.stringify(n.payload.settings) } });
  }
  if (n.event === "dialRotate") {
    zaehler[ctx] = (zaehler[ctx] || 0) + n.payload.ticks;
    sende({ event: "setTitle", context: ctx, payload: { title: "Dial " + zaehler[ctx] } });
    // Und die Anzeige über dem Dial, wie es ein Encoder-Plugin tut.
    sende({ event: "setFeedback", context: ctx, payload: {
      title: "Zähler", value: String(zaehler[ctx]),
      indicator: { value: Math.min(100, zaehler[ctx] * 10) } } });
  }
});
