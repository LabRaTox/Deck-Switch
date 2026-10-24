/**
 * Versionsnummern vergleichen, wie App-Backend und Store es tun.
 *
 * `1.10` ist größer als `1.9`, was keine Zahl ist zählt als 0
 * (`1.0.0-beta` gleich `1.0.0`), und `1.1` ist dasselbe wie `1.1.0`.
 * Gleich gezählt wie `als_zahlen` in `services/store.py` und `alsZahlen`
 * im Store, damit überall dieselbe Fassung die neueste ist.
 */
export function alsZahlen(version: string): number[] {
  const teile = String(version || "")
    .split(".")
    .map((stueck) => {
      const ziffern = /^\d+/.exec(stueck);
      return ziffern ? Number(ziffern[0]) : 0;
    });
  return teile.length > 0 ? teile : [0];
}

/** Negativ, wenn `a` älter ist als `b`, positiv, wenn neuer, 0 bei gleicher Nummer. */
export function vergleicheVersionen(a: string, b: string): number {
  const x = alsZahlen(a);
  const y = alsZahlen(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const unterschied = (x[i] ?? 0) - (y[i] ?? 0);
    if (unterschied !== 0) return unterschied;
  }
  return 0;
}
