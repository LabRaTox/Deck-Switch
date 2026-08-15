/**
 * Zeigt ein Iconset-SVG in beliebiger Farbe an.
 *
 * Die SVGs der Iconsets zeichnen mit `currentColor`; im Browser landet das
 * als Schwarz, was auf der dunklen Oberfläche unsichtbar wäre. Statt mit
 * `filter: invert()` zu tricksen (das bricht, sobald eine echte Farbe
 * gewünscht ist), wird das SVG als CSS-Maske über eine Farbfläche gelegt —
 * damit stimmt die Vorschau exakt mit der gewählten Farbe überein.
 *
 * Für hochgeladene Bilder (PNG/JPG, ggf. mehrfarbig) ist das falsch, dort
 * wird das Bild unverändert angezeigt.
 */
export function IconGlyph({
  src,
  color = "#ffffff",
  mask = true,
  size,
  className,
  alt = "",
}: {
  src: string;
  color?: string | null;
  mask?: boolean;
  size?: number;
  className?: string;
  alt?: string;
}) {
  if (!src) return <span className={className} />;

  if (!mask) {
    return (
      <img
        className={className}
        src={src}
        alt={alt}
        loading="lazy"
        draggable={false}
        style={size ? { width: size, height: size } : undefined}
      />
    );
  }

  return (
    <span
      className={className}
      role="img"
      aria-label={alt || undefined}
      style={{
        display: "block",
        width: size ?? "100%",
        height: size ?? "100%",
        backgroundColor: color ?? "#ffffff",
        maskImage: `url("${src}")`,
        WebkitMaskImage: `url("${src}")`,
        maskRepeat: "no-repeat",
        WebkitMaskRepeat: "no-repeat",
        maskPosition: "center",
        WebkitMaskPosition: "center",
        maskSize: "contain",
        WebkitMaskSize: "contain",
      }}
    />
  );
}
