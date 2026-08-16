import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { Appearance } from "../types";
import { Modal } from "./Modal";

/** Kantenlänge des erzeugten Bildes. */
const CANVAS = 288;

interface Props {
  appearance: Appearance;
  onClose: () => void;
  onApply: (filename: string, mode: "background" | "icon") => void;
}

interface Design {
  background: "solid" | "gradient" | "transparent";
  color: string;
  color2: string;
  imageUrl: string;
  imageName: string;
  scale: number;
  offsetX: number;
  offsetY: number;
  rotation: number;
  text: string;
  font: string;
  size: number;
  textColor: string;
  bold: boolean;
  italic: boolean;
  position: "top" | "center" | "bottom";
  outline: boolean;
}

const START: Design = {
  background: "solid",
  color: "#111114",
  color2: "#2b2b31",
  imageUrl: "",
  imageName: "",
  scale: 60,
  offsetX: 0,
  offsetY: 0,
  rotation: 0,
  text: "",
  font: "",
  size: 44,
  textColor: "#ffffff",
  bold: true,
  italic: false,
  position: "bottom",
  outline: true,
};

/**
 * Tastenbilder selbst gestalten — Elgatos „Key Creator“ in klein.
 *
 * Erzeugt wird ein fertiges PNG, das anschließend wie jedes hochgeladene
 * Bild verwendet wird. Bewusst *nicht* als weiterer Zeichenschritt im
 * Backend: Was hier entsteht, soll man auch woanders einsetzen und
 * weitergeben können — eine Datei kann das, ein Satz Einstellungen nicht.
 *
 * Gezeichnet wird im Browser auf einer Leinwand. Schriftfamilien kommen aus
 * derselben Liste, die auch die Beschriftung anbietet: Das System hat sie,
 * also kennt sie auch die Leinwand.
 */
export function KeyCreator({ appearance, onClose, onApply }: Props) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [design, setDesign] = useState<Design>(() => ({
    ...START,
    text: appearance.label_text,
    font: appearance.label_font,
    textColor: appearance.label_color,
  }));
  const [fonts, setFonts] = useState<string[]>([]);
  const [uploads, setUploads] = useState<{ filename: string; url: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const patch = (changes: Partial<Design>) => setDesign((old) => ({ ...old, ...changes }));

  useEffect(() => {
    api.fonts().then(setFonts).catch(() => undefined);
    api.uploads().then(setUploads).catch(() => undefined);
  }, []);

  // Bild laden, sobald sich die Quelle ändert.
  useEffect(() => {
    if (!design.imageUrl) {
      imageRef.current = null;
      draw();
      return;
    }
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      imageRef.current = image;
      draw();
    };
    image.onerror = () => {
      imageRef.current = null;
      setError(t("creator.imageError"));
    };
    image.src = design.imageUrl;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [design.imageUrl]);

  useEffect(draw, [design, fonts]);

  function draw() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const pen = canvas.getContext("2d");
    if (!pen) return;

    pen.clearRect(0, 0, CANVAS, CANVAS);

    if (design.background === "solid") {
      pen.fillStyle = design.color;
      pen.fillRect(0, 0, CANVAS, CANVAS);
    } else if (design.background === "gradient") {
      const gradient = pen.createLinearGradient(0, 0, 0, CANVAS);
      gradient.addColorStop(0, design.color);
      gradient.addColorStop(1, design.color2);
      pen.fillStyle = gradient;
      pen.fillRect(0, 0, CANVAS, CANVAS);
    }

    const image = imageRef.current;
    if (image) {
      const box = (CANVAS * design.scale) / 100;
      const ratio = Math.min(box / image.width, box / image.height);
      const width = image.width * ratio;
      const height = image.height * ratio;
      pen.save();
      pen.translate(CANVAS / 2 + design.offsetX, CANVAS / 2 + design.offsetY);
      pen.rotate((design.rotation * Math.PI) / 180);
      pen.drawImage(image, -width / 2, -height / 2, width, height);
      pen.restore();
    }

    if (design.text) {
      const style = `${design.italic ? "italic " : ""}${design.bold ? "700 " : "400 "}`;
      pen.font = `${style}${design.size}px ${design.font ? `"${design.font}", ` : ""}sans-serif`;
      pen.textAlign = "center";
      pen.textBaseline = "middle";
      const y =
        design.position === "top"
          ? design.size * 0.8
          : design.position === "center"
            ? CANVAS / 2
            : CANVAS - design.size * 0.7;

      if (design.outline) {
        // Der dunkle Rand hält den Text auch auf hellen Bildern lesbar —
        // dieselbe Entscheidung wie beim Zeichnen im Backend.
        pen.lineWidth = Math.max(2, design.size / 10);
        pen.strokeStyle = "rgba(0,0,0,0.75)";
        pen.lineJoin = "round";
        pen.strokeText(design.text, CANVAS / 2, y);
      }
      pen.fillStyle = design.textColor;
      pen.fillText(design.text, CANVAS / 2, y);
    }
  }

  async function apply(mode: "background" | "icon") {
    const canvas = canvasRef.current;
    if (!canvas) return;
    setBusy(true);
    setError("");
    try {
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/png"),
      );
      if (!blob) throw new Error("PNG konnte nicht erzeugt werden");
      const file = new File([blob], `tastenbild-${Date.now()}.png`, {
        type: "image/png",
      });
      const { filename } = await api.upload(file, "icon");
      onApply(filename, mode);
      onClose();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={t("creator.title")} onClose={onClose} width={900}>
      <div className="creator">
        <div className="creator-preview">
          <canvas
            ref={canvasRef}
            width={CANVAS}
            height={CANVAS}
            className={design.background === "transparent" ? "checker" : ""}
          />
          <small>{t("creator.previewHint")}</small>
        </div>

        <div className="creator-controls">
          <section>
            <h4>{t("creator.image")}</h4>
            <div className="field">
              <input
                type="file"
                accept="image/*"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (!file) return;
                  patch({ imageUrl: URL.createObjectURL(file), imageName: file.name });
                }}
              />
            </div>
            {uploads.length > 0 && (
              <div className="field">
                <label>{t("creator.fromUploads")}</label>
                <select
                  value={design.imageName}
                  onChange={(event) => {
                    const entry = uploads.find((u) => u.filename === event.target.value);
                    patch({
                      imageName: entry?.filename ?? "",
                      imageUrl: entry ? api.uploadUrl(entry.filename) : "",
                    });
                  }}
                >
                  <option value="">—</option>
                  {uploads.map((entry) => (
                    <option key={entry.filename} value={entry.filename}>
                      {entry.filename}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="field">
              <label>
                {t("creator.scale")} ({design.scale}%)
              </label>
              <input
                type="range"
                min={10}
                max={140}
                value={design.scale}
                onChange={(event) => patch({ scale: Number(event.target.value) })}
              />
            </div>
            <div className="field-row">
              <div className="field">
                <label>{t("creator.offsetX")}</label>
                <input
                  type="range"
                  min={-120}
                  max={120}
                  value={design.offsetX}
                  onChange={(event) => patch({ offsetX: Number(event.target.value) })}
                />
              </div>
              <div className="field">
                <label>{t("creator.offsetY")}</label>
                <input
                  type="range"
                  min={-120}
                  max={120}
                  value={design.offsetY}
                  onChange={(event) => patch({ offsetY: Number(event.target.value) })}
                />
              </div>
              <div className="field">
                <label>{t("creator.rotation")}</label>
                <input
                  type="range"
                  min={-180}
                  max={180}
                  value={design.rotation}
                  onChange={(event) => patch({ rotation: Number(event.target.value) })}
                />
              </div>
            </div>
          </section>

          <section>
            <h4>{t("creator.background")}</h4>
            <div className="field-row">
              <div className="field">
                <select
                  value={design.background}
                  onChange={(event) =>
                    patch({ background: event.target.value as Design["background"] })
                  }
                >
                  <option value="solid">{t("background.kinds.solid")}</option>
                  <option value="gradient">{t("background.kinds.gradient")}</option>
                  <option value="transparent">{t("background.kinds.transparent")}</option>
                </select>
              </div>
              {design.background !== "transparent" && (
                <div className="field">
                  <input
                    type="color"
                    value={design.color}
                    onChange={(event) => patch({ color: event.target.value })}
                  />
                </div>
              )}
              {design.background === "gradient" && (
                <div className="field">
                  <input
                    type="color"
                    value={design.color2}
                    onChange={(event) => patch({ color2: event.target.value })}
                  />
                </div>
              )}
            </div>
          </section>

          <section>
            <h4>{t("creator.text")}</h4>
            <div className="field">
              <input
                type="text"
                value={design.text}
                placeholder={t("creator.textPlaceholder")}
                onChange={(event) => patch({ text: event.target.value })}
              />
            </div>
            <div className="field">
              <select
                value={design.font}
                onChange={(event) => patch({ font: event.target.value })}
              >
                <option value="">{t("inspector.labelFontDefault")}</option>
                {fonts.map((family) => (
                  <option key={family} value={family}>
                    {family}
                  </option>
                ))}
              </select>
            </div>
            <div className="field-row">
              <div className="field">
                <label>{t("inspector.labelSize")}</label>
                <input
                  type="number"
                  min={8}
                  max={140}
                  value={design.size}
                  onChange={(event) => patch({ size: Number(event.target.value) })}
                />
              </div>
              <div className="field">
                <label>{t("inspector.labelColor")}</label>
                <input
                  type="color"
                  value={design.textColor}
                  onChange={(event) => patch({ textColor: event.target.value })}
                />
              </div>
              <div className="field">
                <label>{t("inspector.labelPosition")}</label>
                <select
                  value={design.position}
                  onChange={(event) =>
                    patch({ position: event.target.value as Design["position"] })
                  }
                >
                  <option value="bottom">{t("inspector.labelPositions.bottom")}</option>
                  <option value="center">{t("inspector.labelPositions.center")}</option>
                  <option value="top">{t("inspector.labelPositions.top")}</option>
                </select>
              </div>
            </div>
            <div className="field-row">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={design.bold}
                  onChange={(event) => patch({ bold: event.target.checked })}
                />
                <span>{t("inspector.labelStyles.bold")}</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={design.italic}
                  onChange={(event) => patch({ italic: event.target.checked })}
                />
                <span>{t("inspector.labelStyles.italic")}</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={design.outline}
                  onChange={(event) => patch({ outline: event.target.checked })}
                />
                <span>{t("creator.outline")}</span>
              </label>
            </div>
          </section>

          {error && <p className="error-text">{error}</p>}

          <div className="creator-actions">
            <button
              type="button"
              className="btn primary"
              disabled={busy}
              onClick={() => void apply("background")}
            >
              {t("creator.applyAsKey")}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => void apply("icon")}
            >
              {t("creator.applyAsIcon")}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
