'use client';
import { useId, useState } from 'react';

/** Graphiques du tableau de bord, en SVG : palette data-viz du design.md (violet = série principale, orange = menaces). */

const EASE = 'cubic-bezier(.2,.8,.2,1)';

export function BarsChart({ data, height = 220 }: { data: { label: string; sessions: number; threats: number }[]; height?: number }) {
  const uid = useId();
  const [hover, setHover] = useState<number | null>(null);
  const width = 720;
  const padL = 8, padR = 8, padT = 16, padB = 28;
  const n = Math.max(1, data.length);
  const slot = (width - padL - padR) / n;
  const barW = Math.max(10, Math.min(28, slot - 12));
  const max = Math.max(1, ...data.map((d) => d.sessions));
  const scaleY = (v: number) => (height - padT - padB) * (v / max);
  const ticks = [0, Math.ceil(max / 2), max];
  const everyLabel = n > 12 ? 3 : 1;
  const h = hover !== null ? data[hover] : null;
  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} role="img" aria-label="Sessions et menaces neutralisées par période" style={{ display: 'block', overflow: 'visible' }}>
        <defs>
          <linearGradient id={`${uid}-s`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--viz-1)" /><stop offset="1" stopColor="var(--viz-1)" stopOpacity=".4" /></linearGradient>
          <linearGradient id={`${uid}-t`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="var(--viz-2)" /><stop offset="1" stopColor="var(--viz-2)" stopOpacity=".4" /></linearGradient>
        </defs>
        {ticks.map((t) => {
          const y = height - padB - scaleY(t);
          return <g key={t}><line x1={padL} x2={width - padR} y1={y} y2={y} stroke="var(--border)" strokeDasharray="2 4" /><text x={width - padR} y={y - 4} textAnchor="end" fontSize="12" fontWeight="500" fill="var(--text-3)">{t}</text></g>;
        })}
        {data.map((d, i) => {
          const x = padL + i * slot + (slot - barW) / 2;
          const hs = scaleY(d.sessions), ht = scaleY(d.threats);
          const y0 = height - padB;
          const r = Math.min(12, barW / 2);
          const active = hover === i;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} style={{ cursor: 'default' }}>
              <rect x={padL + i * slot} y={padT} width={slot} height={height - padT - padB} fill="transparent" />
              {d.sessions > 0 && <path d={`M${x},${y0} v${-(hs - r)} a${r},${r} 0 0 1 ${r},${-r} h${barW - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${hs - r} z`} fill={active ? 'var(--accent-lime)' : `url(#${uid}-s)`} style={{ transition: `fill 200ms ${EASE}` }} />}
              {d.threats > 0 && <path d={`M${x + 2},${y0} v${-Math.max(0, ht - r)} a${r},${r} 0 0 1 ${r},${-r} h${Math.max(0, barW - 4 - 2 * r)} a${r},${r} 0 0 1 ${r},${r} v${Math.max(0, ht - r)} z`} fill={`url(#${uid}-t)`} stroke="var(--surface)" strokeWidth="2" />}
              {i % everyLabel === 0 && <text x={x + barW / 2} y={height - 8} textAnchor="middle" fontSize="12" fontWeight="500" fill="var(--text-3)">{d.label}</text>}
            </g>
          );
        })}
      </svg>
      {h && hover !== null && (
        <div className="chart-tip" style={{ left: `${((padL + hover * slot + slot / 2) / width) * 100}%`, top: 4 }}>
          {h.label} · {h.sessions} session{h.sessions > 1 ? 's' : ''} · {h.threats} neutralisée{h.threats > 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
}

/** Mini-graphique en barres (tuile KPI), une seule série. */
export function Spark({ values, color = 'var(--viz-1)', height = 80 }: { values: number[]; color?: string; height?: number }) {
  const uid = useId();
  const n = Math.max(1, values.length);
  const width = 240;
  const slot = width / n;
  const barW = Math.max(4, Math.min(14, slot - 4));
  const max = Math.max(1, ...values);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} aria-hidden="true" style={{ display: 'block' }}>
      <defs><linearGradient id={`${uid}-g`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} /><stop offset="1" stopColor={color} stopOpacity=".4" /></linearGradient></defs>
      {values.map((v, i) => {
        const hgt = Math.max(v > 0 ? 4 : 2, (height - 4) * (v / max));
        const r = Math.min(barW / 2, 6);
        return <rect key={i} x={i * slot + (slot - barW) / 2} y={height - hgt} width={barW} height={hgt} rx={r} fill={v > 0 ? `url(#${uid}-g)` : 'var(--surface-3)'} />;
      })}
    </svg>
  );
}

/** Donut 28 px, segments séparés par un espace de 4 px ; « en attente » en gris hachuré. */
export function Donut({ parts, size = 168 }: { parts: { label: string; value: number; color: string; hatched?: boolean }[]; size?: number }) {
  const uid = useId();
  const total = parts.reduce((s, p) => s + p.value, 0);
  const stroke = 28;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const gap = 4;
  let offset = 0;
  const [hover, setHover] = useState<number | null>(null);
  return (
    <div style={{ position: 'relative', width: size, height: size, flex: 'none' }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label="Répartition des sessions">
        <defs>
          <pattern id={`${uid}-h`} patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--viz-7)" fillOpacity=".35" /><rect width="2" height="6" fill="var(--viz-7)" /></pattern>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-2)" strokeWidth={stroke} />
        {total > 0 && parts.map((p, i) => {
          if (p.value <= 0) return null;
          const len = Math.max(0, (c * p.value) / total - gap);
          const el = <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={p.hatched ? `url(#${uid}-h)` : p.color} strokeWidth={hover === i ? stroke + 4 : stroke} strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} transform={`rotate(-90 ${size / 2} ${size / 2})`} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} style={{ transition: `stroke-width 200ms ${EASE}` }} />;
          offset += len + gap;
          return el;
        })}
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', textAlign: 'center', pointerEvents: 'none' }}>
        <div>
          <div className="kpi" style={{ fontSize: 32, lineHeight: '36px' }}>{hover !== null ? parts[hover].value : total}</div>
          <div className="caption faint">{hover !== null ? parts[hover].label : 'sessions'}</div>
        </div>
      </div>
    </div>
  );
}

/** Jauge pill 16 px avec curseur, pour un score 0–100. */
export function ScoreBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div style={{ position: 'relative', height: 16, borderRadius: 999, background: 'linear-gradient(90deg,#FF5A5F,#FFD166,#9DFF3A)' }} role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div style={{ position: 'absolute', left: `calc(${pct}% - 6px)`, top: -8, width: 0, height: 0, borderLeft: '6px solid transparent', borderRight: '6px solid transparent', borderTop: '8px solid var(--text)' }} />
    </div>
  );
}
