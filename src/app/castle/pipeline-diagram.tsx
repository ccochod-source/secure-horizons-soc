'use client';
import { blockStates, type BlockId, type TraceStep } from '@/castle/animation/pipeline-trace';

/**
 * Schéma « Copilote SOC — Architecture en six blocs » (design/architecture_six_blocs_court.svg),
 * animé par le déroulé réel d'un test (événements Supabase) : chaque bloc s'allume quand son étape est faite,
 * pulse quand elle est en cours, passe en rouge en cas d'échec.
 */

type State = TraceStep['state'] | 'idle';

interface Block {
  id: BlockId;
  x: number; y: number; w: number; h: number;
  title: string; lines: string[];
  fill: string; stroke: string;
}

const BLOCKS: Block[] = [
  { id: 'env', x: 100, y: 70, w: 480, h: 56, title: 'ENVIRONNEMENT ATTAQUÉ', lines: ['Agent victime • MCP piégé • e-mail'], fill: '#E8ECF2', stroke: '#5E6B7A' },
  { id: 'gateway', x: 100, y: 146, w: 480, h: 56, title: 'PASSERELLE + COFFRE', lines: ['Trace tout, masque les secrets'], fill: '#E8ECF2', stroke: '#5E6B7A' },
  { id: 'decoys', x: 24, y: 244, w: 312, h: 56, title: 'COUCHE DE LEURRES', lines: ['Semeur • détecteur • bac à sable'], fill: '#DCEBFF', stroke: '#2F6FDB' },
  { id: 'packages', x: 344, y: 244, w: 312, h: 56, title: 'CONTRÔLE DES PACKAGES', lines: ['Suspect → décision humaine'], fill: '#ECE4FF', stroke: '#8B3FD9' },
  { id: 'inventory', x: 100, y: 344, w: 480, h: 56, title: 'INVENTAIRE + SUPABASE', lines: ['Droits, traces, alertes, actions'], fill: '#E8ECF2', stroke: '#5E6B7A' },
  { id: 'defenders', x: 100, y: 420, w: 480, h: 76, title: 'AGENTS DÉFENSEURS', lines: ['Sentinelle • Enquêteur • Vérificateur', 'Confineur • Rapporteur'], fill: '#FFE8D1', stroke: '#E8640F' },
];

const STATE_STYLE: Record<State, { stroke?: string; fill?: string; width: number; glow?: string }> = {
  idle: { width: 1.2 },
  done: { stroke: '#1f9d55', fill: '#dff7e8', width: 2.2, glow: 'rgba(31,157,85,.35)' },
  active: { stroke: '#e8a20f', fill: '#fff3d6', width: 2.4, glow: 'rgba(232,162,15,.45)' },
  error: { stroke: '#d9372b', fill: '#ffe1de', width: 2.4, glow: 'rgba(217,55,43,.4)' },
  skip: { stroke: '#e8a20f', fill: '#fff6e5', width: 2, glow: undefined },
};

const DEFENDER_ORDER = ['sentinelle', 'enqueteur', 'verificateur', 'confineur', 'rapporteur'] as const;
const DEFENDER_LABEL: Record<(typeof DEFENDER_ORDER)[number], string> = { sentinelle: 'Sentinelle', enqueteur: 'Enquêteur', verificateur: 'Vérificateur', confineur: 'Confineur', rapporteur: 'Rapporteur' };

export function PipelineDiagram({ steps }: { steps: TraceStep[] }) {
  const states = blockStates(steps);
  const shown = steps;
  const shownBlocks = new Set(shown.map((s) => s.block));
  const shownSubs = new Map(shown.filter((s) => s.sub).map((s) => [s.sub!, s.state]));
  const stateOf = (b: BlockId): State => (shownBlocks.has(b) ? states[b] ?? 'idle' : 'idle');
  const edgeOn = (a: BlockId, b: BlockId) => shownBlocks.has(a) && shownBlocks.has(b);
  const edge = (on: boolean, base: string) => ({ stroke: on ? '#1f9d55' : base, strokeWidth: on ? 2.4 : 1.5, opacity: on ? 1 : 0.55 });

  return (
    <div>
      <svg viewBox="0 0 680 500" role="img" aria-label="Architecture en six blocs, animée par le backend" style={{ width: '100%', display: 'block', background: 'var(--surface-2)', borderRadius: 'var(--r-md)' }}>
        <defs>
          <marker id="pd-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </marker>
          <style>{`@keyframes pd-pulse { 0%,100% { opacity: .55 } 50% { opacity: 1 } } .pd-active { animation: pd-pulse 1.1s ease-in-out infinite }`}</style>
        </defs>
        <text x="340" y="30" textAnchor="middle" dominantBaseline="central" fontSize="18" fontWeight="500" fill="#1A1D23">Copilote SOC — Architecture</text>
        <text x="340" y="52" textAnchor="middle" dominantBaseline="central" fontSize="12" fill="#6B7280">Tout passe par la passerelle, l’humain valide l’irréversible.</text>

        {/* flèches, dans l'ordre du schéma d'origine */}
        <line x1="340" y1="126" x2="340" y2="144" markerEnd="url(#pd-arrow)" {...edge(edgeOn('env', 'gateway'), '#5E6B7A')} />
        <path d="M340 202 V224 H180 V242" fill="none" markerEnd="url(#pd-arrow)" {...edge(edgeOn('gateway', 'decoys'), '#2F6FDB')} />
        <path d="M340 202 V224 H500 V242" fill="none" markerEnd="url(#pd-arrow)" {...edge(edgeOn('gateway', 'packages'), '#8B3FD9')} />
        <path d="M180 300 V324 H340" fill="none" {...edge(edgeOn('decoys', 'inventory'), '#2F6FDB')} />
        <path d="M500 300 V324 H340" fill="none" {...edge(edgeOn('packages', 'inventory'), '#8B3FD9')} />
        <line x1="340" y1="324" x2="340" y2="342" markerEnd="url(#pd-arrow)" {...edge(shownBlocks.has('inventory'), '#5E6B7A')} />
        <line x1="340" y1="400" x2="340" y2="418" markerEnd="url(#pd-arrow)" {...edge(edgeOn('inventory', 'defenders'), '#5E6B7A')} />

        {BLOCKS.map((b) => {
          const st = stateOf(b.id);
          const style = STATE_STYLE[st];
          const isDef = b.id === 'defenders';
          return (
            <g key={b.id} className={st === 'active' ? 'pd-active' : undefined} style={{ transition: 'all .4s' }}>
              {style.glow && <rect x={b.x - 3} y={b.y - 3} width={b.w + 6} height={b.h + 6} rx="13" fill="none" stroke={style.glow} strokeWidth="6" />}
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx="10" fill={style.fill ?? b.fill} stroke={style.stroke ?? b.stroke} strokeWidth={style.width} />
              <text x={b.x + b.w / 2} y={b.y + 18} textAnchor="middle" dominantBaseline="central" fontSize="14" fontWeight="500" fill="#1A1D23">{b.title}</text>
              {!isDef && b.lines.map((l, i) => (
                <text key={i} x={b.x + b.w / 2} y={b.y + 38 + i * 18} textAnchor="middle" dominantBaseline="central" fontSize="12" fill="#1A1D23">{l}</text>
              ))}
              {isDef && DEFENDER_ORDER.map((sub, i) => {
                const s = shownSubs.get(sub);
                const col = s === 'done' ? '#1f9d55' : s === 'active' || s === 'skip' ? '#c47d00' : s === 'error' ? '#d9372b' : '#1A1D23';
                const cx = b.x + 48 + i * 96;
                return (
                  <g key={sub} className={s === 'active' ? 'pd-active' : undefined}>
                    <circle cx={cx} cy={b.y + 44} r="5" fill={s ? col : '#c9ced6'} />
                    <text x={cx} y={b.y + 62} textAnchor="middle" dominantBaseline="central" fontSize="11" fontWeight={s ? 600 : 400} fill={col}>{DEFENDER_LABEL[sub]}</text>
                  </g>
                );
              })}
              {st !== 'idle' && <circle cx={b.x + b.w - 12} cy={b.y + 12} r="5" fill={style.stroke} />}
            </g>
          );
        })}
      </svg>

      <ol style={{ listStyle: 'none', padding: 0, margin: '8px 0 0', fontSize: 12, lineHeight: 1.35, maxHeight: 'calc(100vh - 520px)', minHeight: 160, overflow: 'auto' }}>
        {!steps.length && <li style={{ color: '#888' }}>Lancez un test : chaque étape réelle s’affichera ici.</li>}
        {shown.map((s) => (
          <li key={s.id} style={{ display: 'grid', gridTemplateColumns: '14px 1fr', gap: 6, padding: '3px 0', borderTop: '1px solid #eee' }}>
            <span style={{ color: s.state === 'done' ? '#1f9d55' : s.state === 'error' ? '#d9372b' : '#c47d00', fontWeight: 700 }}>{s.state === 'done' ? '✓' : s.state === 'active' ? '…' : s.state === 'skip' ? '–' : '✗'}</span>
            <span>
              <strong>{s.label}</strong>
              {s.detail && <span style={{ color: '#666', display: 'block', overflowWrap: 'anywhere' }}>{s.detail}</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
