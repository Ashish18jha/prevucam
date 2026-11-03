import { useEffect, useRef, useState } from "react";

/**
 * Draw a polygon (click points, double-click / Finish to close) or a rectangle (drag)
 * over a camera frame. Emits normalised [[x,y],...] coordinates (0..1).
 */
export default function ZoneEditor({ background, zones = [], highlightId, mode, points, onPoints, onComplete }) {
  const canvasRef = useRef(null);
  const [drag, setDrag] = useState(null);
  const [hover, setHover] = useState(null);

  const toNorm = (e) => {
    const r = canvasRef.current.getBoundingClientRect();
    const clamp = (v) => Math.min(1, Math.max(0, v));
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)];
  };

  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const { width, height } = c.getBoundingClientRect();
    c.width = width * devicePixelRatio;
    c.height = height * devicePixelRatio;
    const ctx = c.getContext("2d");
    ctx.scale(devicePixelRatio, devicePixelRatio);
    const P = ([x, y]) => [x * width, y * height];

    const poly = (pts, color, fill, dashed) => {
      if (!pts.length) return;
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(...P(p)) : ctx.moveTo(...P(p))));
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.setLineDash(dashed ? [6, 4] : []);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.setLineDash([]);
    };

    zones.forEach((z) => {
      const hi = z.id === highlightId;
      poly(z.points, z.color, `${z.color}${hi ? "40" : "22"}`, !z.active);
      const [x, y] = P(z.points[0]);
      ctx.font = "600 12px system-ui";
      ctx.fillStyle = z.color;
      ctx.fillText(z.name, x + 4, y + 15);
    });

    let draft = points;
    if (mode === "rect" && drag) {
      const [a, b] = drag;
      draft = [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
    }
    if (draft.length) {
      const preview = mode === "polygon" && hover ? [...draft, hover] : draft;
      ctx.beginPath();
      preview.forEach((p, i) => (i ? ctx.lineTo(...P(p)) : ctx.moveTo(...P(p))));
      if (mode === "rect" || preview.length > 2) ctx.closePath();
      ctx.fillStyle = "rgba(34,211,238,0.15)";
      ctx.fill();
      ctx.strokeStyle = "#22d3ee";
      ctx.lineWidth = 2;
      ctx.stroke();
      draft.forEach((p) => {
        ctx.beginPath();
        ctx.arc(...P(p), 4, 0, Math.PI * 2);
        ctx.fillStyle = "#22d3ee";
        ctx.fill();
      });
    }
  }, [zones, points, drag, hover, mode, highlightId]);

  const handlers = mode === "rect"
    ? {
        onMouseDown: (e) => { const p = toNorm(e); setDrag([p, p]); },
        onMouseMove: (e) => drag && setDrag([drag[0], toNorm(e)]),
        onMouseUp: () => {
          if (!drag) return;
          const [a, b] = drag;
          setDrag(null);
          if (Math.abs(a[0] - b[0]) < 0.02 || Math.abs(a[1] - b[1]) < 0.02) return;
          const x1 = Math.min(a[0], b[0]), x2 = Math.max(a[0], b[0]), y1 = Math.min(a[1], b[1]), y2 = Math.max(a[1], b[1]);
          const rect = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]];
          onPoints(rect);
          onComplete?.(rect);
        },
      }
    : mode === "polygon"
    ? {
        onClick: (e) => onPoints([...points, toNorm(e)]),
        onMouseMove: (e) => setHover(toNorm(e)),
        onMouseLeave: () => setHover(null),
        onDoubleClick: (e) => { e.preventDefault(); if (points.length >= 3) onComplete?.(points); },
      }
    : {};

  return (
    <div className="zone-canvas" style={{ cursor: mode ? "crosshair" : "default" }}>
      {background && <img src={background} alt="Camera frame" draggable={false} />}
      <canvas ref={canvasRef} {...handlers} />
    </div>
  );
}
