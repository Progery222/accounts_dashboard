import { useEffect, useRef } from "react";
import styles from "./MetricChart.module.css";

export interface ChartSeries {
  name?: string;
  data: number[];
  color?: string;
}

export interface MetricChartOption {
  type: "line" | "area" | "bar" | "donut" | "gauge" | "sparkline";
  series: ChartSeries[];
  labels?: string[];
  value?: number;
  unit?: string;
  height?: number;
}

interface Props {
  option: MetricChartOption;
  className?: string;
}

const NEON_COLORS = ["#00D2FF", "#FF0080", "#00d4aa", "#FBBF24", "#a78bfa"];

/** Canvas не понимает var(--token); разрешаем через computed style. */
function resolveCanvasColor(color: string): string {
  if (!color || !color.includes("var(")) return color;
  const probe = document.createElement("span");
  probe.style.color = color;
  probe.style.display = "none";
  document.body.appendChild(probe);
  const resolved = getComputedStyle(probe).color;
  document.body.removeChild(probe);
  return resolved && resolved !== "rgba(0, 0, 0, 0)" ? resolved : NEON_COLORS[0];
}

function colorWithAlpha(color: string, alphaHex = "44"): string {
  const c = resolveCanvasColor(color);
  const m = c.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (m) {
    const a = parseInt(alphaHex, 16) / 255;
    return `rgba(${m[1]}, ${m[2]}, ${m[3]}, ${a.toFixed(3)})`;
  }
  if (/^#[0-9a-fA-F]{6}$/.test(c)) return `${c}${alphaHex}`;
  return c;
}

function drawChart(canvas: HTMLCanvasElement, option: MetricChartOption) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  try {
    const { type, series, labels, value, unit } = option;

    if (type === "sparkline") {
      const data = series[0]?.data ?? [];
      if (data.length < 2) return;
      const min = Math.min(...data);
      const max = Math.max(...data);
      const range = max - min || 1;
      const pad = 4;
      const color = resolveCanvasColor(series[0]?.color ?? NEON_COLORS[0]);
      ctx.beginPath();
      data.forEach((v, i) => {
        const x = pad + (i / (data.length - 1)) * (w - pad * 2);
        const y = h - pad - ((v - min) / range) * (h - pad * 2);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      return;
    }

    if (type === "gauge") {
      const val = value ?? 0;
      const cx = w / 2;
      const cy = h * 0.62;
      const r = Math.min(w, h) * 0.38;
      ctx.beginPath();
      ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI);
      ctx.strokeStyle = "rgba(255,255,255,0.06)";
      ctx.lineWidth = 10;
      ctx.stroke();
      const angle = Math.PI + (val / 100) * Math.PI;
      ctx.beginPath();
      ctx.arc(cx, cy, r, Math.PI, angle);
      const color = val >= 80 ? "#00d4aa" : val >= 50 ? "#FBBF24" : "#EF4444";
      ctx.strokeStyle = color;
      ctx.lineWidth = 10;
      ctx.lineCap = "round";
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = `bold ${Math.round(h * 0.22)}px Inter, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(`${Math.round(val)}${unit ?? "%"}`, cx, cy - r * 0.1);
      return;
    }

    if (type === "donut") {
      const total = series.reduce((s, ser) => s + (ser.data[0] ?? 0), 0) || 1;
      const cx = w / 2;
      const cy = h / 2;
      const r = Math.min(w, h) * 0.38;
      let startAngle = -Math.PI / 2;
      series.forEach((ser, i) => {
        const slice = ((ser.data[0] ?? 0) / total) * 2 * Math.PI;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, r, startAngle, startAngle + slice);
        ctx.closePath();
        ctx.fillStyle = resolveCanvasColor(ser.color ?? NEON_COLORS[i % NEON_COLORS.length]);
        ctx.fill();
        startAngle += slice;
      });
      ctx.beginPath();
      ctx.arc(cx, cy, r * 0.58, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(10,10,10,0.9)";
      ctx.fill();
      return;
    }

    const padL = 24,
      padR = 8,
      padT = 8,
      padB = 24;
    const chartW = w - padL - padR;
    const chartH = h - padT - padB;

    const gridLines = 4;
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= gridLines; i++) {
      const y = padT + (i / gridLines) * chartH;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + chartW, y);
      ctx.stroke();
    }

    if (labels && labels.length > 0) {
      ctx.fillStyle = "#8899AA";
      ctx.font = "10px Inter, sans-serif";
      ctx.textAlign = "center";
      const step = Math.max(1, Math.floor(labels.length / 5));
      labels.forEach((lbl, i) => {
        if (i % step !== 0 && i !== labels.length - 1) return;
        const x = padL + (i / (labels.length - 1)) * chartW;
        ctx.fillText(lbl, x, h - 4);
      });
    }

    const allVals = series.flatMap((s) => s.data);
    if (allVals.length === 0) return;
    const min = 0;
    const max = Math.max(...allVals, 1);

    series.forEach((ser, si) => {
      const data = ser.data;
      if (data.length === 0) return;
      const color = resolveCanvasColor(ser.color ?? NEON_COLORS[si % NEON_COLORS.length]);

      if (type === "bar") {
        const bw = (chartW / data.length) * 0.6;
        data.forEach((v, i) => {
          const x = padL + (i / data.length) * chartW + (chartW / data.length) * 0.2;
          const barH = ((v - min) / (max - min)) * chartH;
          ctx.fillStyle = color;
          ctx.globalAlpha = 0.8;
          ctx.fillRect(x, padT + chartH - barH, bw, barH);
          ctx.globalAlpha = 1;
        });
        return;
      }

      ctx.beginPath();
      data.forEach((v, i) => {
        const x = padL + (i / (data.length - 1)) * chartW;
        const y = padT + chartH - ((v - min) / (max - min)) * chartH;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      });

      if (type === "area") {
        const lastX = padL + chartW;
        const lastY = padT + chartH - ((data[data.length - 1] - min) / (max - min)) * chartH;
        ctx.lineTo(lastX, padT + chartH);
        ctx.lineTo(padL, padT + chartH);
        const grad = ctx.createLinearGradient(0, padT, 0, padT + chartH);
        grad.addColorStop(0, colorWithAlpha(color));
        grad.addColorStop(1, "transparent");
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.beginPath();
        data.forEach((v, i) => {
          const x = padL + (i / (data.length - 1)) * chartW;
          const y = padT + chartH - ((v - min) / (max - min)) * chartH;
          i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        void lastX;
        void lastY;
      }

      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.stroke();
    });
  } catch (err) {
    console.error("Error drawing MetricChart:", err);
  }
}

export function MetricChart({ option, className }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const height = option.height ?? (option.type === "sparkline" ? 40 : 160);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    drawChart(canvas, option);
    const ro = new ResizeObserver(() => drawChart(canvas, option));
    ro.observe(canvas);
    return () => ro.disconnect();
  }, [option]);

  return (
    <canvas
      ref={canvasRef}
      className={`${styles.canvas} ${className ?? ""}`}
      style={{ height }}
    />
  );
}
