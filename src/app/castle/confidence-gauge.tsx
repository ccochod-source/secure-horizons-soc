'use client';

/** Seuil du backend de défense (SEUIL_CONFIANCE dans backend/pipeline.py) : en dessous, l'incident reste « En enquête ». */
const THRESHOLD = 0.7;

/**
 * Certitude de la conclusion des agents : part des conclusions de l'IA que le vérificateur a pu prouver
 * sur les événements tracés. Ce n'est PAS un score de sécurité : 100 % sur « package suspect » veut dire
 * « les agents sont sûrs que le package est suspect ». Couleurs neutres (bleu = solide, orange = fragile)
 * pour ne jamais suggérer « tout va bien ».
 */
export function ConfidenceGauge({ confidence, proven, total, size = 'large', caption, threshold = THRESHOLD, conclusion }: {
  confidence: number; proven: number; total: number; size?: 'large' | 'compact'; caption?: string; threshold?: number;
  /** Ce que les agents concluent (ex. « Package suspect ») : la certitude porte sur cette phrase. */
  conclusion?: string;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, confidence)) * 100);
  const ok = confidence >= threshold;
  const color = ok ? '#285cc4' : confidence >= 0.4 ? '#d98b00' : '#c2362b';
  const bg = ok ? '#eef3fc' : confidence >= 0.4 ? '#fff4dc' : '#ffe8e5';
  const d = size === 'large' ? 92 : 64;
  const stroke = size === 'large' ? 10 : 7;
  const r = (d - stroke) / 2;
  const c = 2 * Math.PI * r;
  // marque du seuil sur l'anneau (départ en haut, sens horaire)
  const a = threshold * 2 * Math.PI - Math.PI / 2;
  const tick = (k: number) => [d / 2 + Math.cos(a) * (r + k), d / 2 + Math.sin(a) * (r + k)];
  const [x1, y1] = tick(-stroke / 2 - 2);
  const [x2, y2] = tick(stroke / 2 + 2);
  return (
    <div role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Certitude de la conclusion des agents"
      style={{ display: 'flex', alignItems: 'center', gap: 12, background: bg, border: `1px solid ${color}55`, borderRadius: 10, padding: size === 'large' ? '10px 12px' : '6px 10px' }}>
      <svg width={d} height={d} viewBox={`0 0 ${d} ${d}`} style={{ flex: 'none' }}>
        <circle cx={d / 2} cy={d / 2} r={r} fill="#fff" stroke="#e4e8ed" strokeWidth={stroke} />
        <circle cx={d / 2} cy={d / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${(c * pct) / 100} ${c}`} transform={`rotate(-90 ${d / 2} ${d / 2})`} style={{ transition: 'stroke-dasharray .8s ease' }} />
        <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#202733" strokeWidth={2} />
        <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fontSize={size === 'large' ? (pct === 100 ? 22 : 24) : (pct === 100 ? 13 : 15)} fontWeight={700} fill={color}>{pct}%</text>
      </svg>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, letterSpacing: 0.4, textTransform: 'uppercase', color: '#555', fontWeight: 600 }}>Certitude de la conclusion</div>
        {conclusion && (
          <div style={{ fontSize: size === 'large' ? 15 : 13, fontWeight: 700, color: '#202733' }}>
            Conclusion des agents : <span style={{ color: '#a12a20' }}>{conclusion}</span>
          </div>
        )}
        <div style={{ fontSize: size === 'large' ? 14 : 12, fontWeight: 700, color }}>
          {ok ? `Preuves solides : les agents sont sûrs à ${pct} % de cette conclusion` : `Preuves fragiles : conclusion sûre à ${pct} % seulement`}
        </div>
        <div style={{ fontSize: 12, color: '#444', marginTop: 2 }}>
          {caption ?? `${proven}/${total} conclusion(s) de l’IA prouvée(s) par les événements tracés.`}
        </div>
        {size === 'large' && (
          <div style={{ fontSize: 11, color: '#666', marginTop: 2 }}>
            Ce score mesure la solidité des preuves, pas la sécurité du package. Seuil : {Math.round(threshold * 100)} % (trait noir).
          </div>
        )}
      </div>
    </div>
  );
}
