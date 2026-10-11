'use client';
import { useMemo } from 'react';
import { DIM, type Vec2 } from '../params';
import { getMaterials } from '../materials';
import { archGeometry, gableGeometry, pyramidGeometry, rectParapetGeometry } from '../geometry';

type RoofKind = 'slate' | 'tile';

interface GableRoofProps {
  width: number;
  length: number;
  eaves: number;
  ridge: number;
  roof: RoofKind;
}

/** Toit à deux pans, faîtage le long de z local, pignons en pierre. */
function GableRoof({ width, length, eaves, ridge, roof }: GableRoofProps) {
  const M = useMemo(getMaterials, []);
  const ov = 0.6;
  const endOv = 0.5;
  const rise = ridge - eaves;
  const halfW = width / 2 + ov;
  const eaveY = eaves - (rise * ov) / (width / 2);
  const slopeLen = Math.hypot(halfW, ridge - eaveY);
  const angle = Math.atan2(ridge - eaveY, halfW);
  const len = length + 2 * endOv;
  const mat = roof === 'slate' ? M.slate(len, slopeLen) : M.tile(len, slopeLen);
  const gable = useMemo(() => gableGeometry(width, rise, 0.4), [width, rise]);
  return (
    <group>
      {[-1, 1].map((sx) => (
        <mesh key={sx} position={[(sx * halfW) / 2, (ridge + eaveY) / 2, 0]} rotation-z={-sx * angle} material={mat} castShadow receiveShadow>
          <boxGeometry args={[slopeLen, 0.45, len]} />
        </mesh>
      ))}
      <mesh geometry={gable} position={[0, eaves, length / 2]} material={M.stoneWorld} castShadow />
      <mesh geometry={gable} position={[0, eaves, -length / 2]} material={M.stoneWorld} castShadow />
      <mesh position={[0, ridge + 0.05, 0]} material={roof === 'slate' ? M.iron : M.woodDark}>
        <boxGeometry args={[0.6, 0.5, len]} />
      </mesh>
    </group>
  );
}

export interface BuildingProps {
  name: string;
  center: Vec2;
  size: Vec2;
  eaves: number;
  ridge: number;
  ridgeAxis: 'x' | 'z';
  roof?: RoofKind;
  /** Direction (x, z) de la face portant la porte et les fenêtres. */
  doorDir?: readonly [number, number];
  door?: readonly [number, number];
  windows?: boolean;
}

/** Bâtiment rectangulaire en pierre à toit à deux pans. */
export function Building({ name, center, size, eaves, ridge, ridgeAxis, roof = 'slate', doorDir, door = [2, 3.4], windows = true }: BuildingProps) {
  const M = useMemo(getMaterials, []);
  const [cx, cz] = center;
  const [w, d] = size;
  const alongZ = ridgeAxis === 'z';
  const doorGeo = useMemo(() => archGeometry(door[0], door[1], 0.3), [door]);
  const winGeo = useMemo(() => archGeometry(1, 1.8, 0.3), []);
  const sideX = M.stone(d, eaves);
  const sideZ = M.stone(w, eaves);
  const openings: { pos: [number, number, number]; rot: number; geo: 'door' | 'win' }[] = [];
  if (doorDir) {
    const [dx, dz] = doorDir;
    const rot = Math.atan2(dx, dz);
    const off = dx ? w / 2 + 0.05 : d / 2 + 0.05;
    const faceLen = dx ? d : w;
    openings.push({ pos: [cx + dx * off, 0, cz + dz * off], rot, geo: 'door' });
    if (windows && faceLen > 6) {
      for (const t of [-0.3, 0.3]) {
        const along = t * faceLen;
        openings.push({ pos: [cx + dx * off + (dx ? 0 : along), eaves * 0.55, cz + dz * off + (dz ? 0 : along)], rot, geo: 'win' });
      }
    }
  }
  return (
    <group name={name}>
      <mesh position={[cx, eaves / 2, cz]} material={[sideX, sideX, M.stonePlain, M.stonePlain, sideZ, sideZ]} castShadow receiveShadow>
        <boxGeometry args={[w, eaves, d]} />
      </mesh>
      <group position={[cx, 0, cz]} rotation-y={alongZ ? 0 : Math.PI / 2}>
        <GableRoof width={alongZ ? w : d} length={alongZ ? d : w} eaves={eaves} ridge={ridge} roof={roof} />
      </group>
      {openings.map((o, i) => (
        <mesh key={i} geometry={o.geo === 'door' ? doorGeo : winGeo} material={M.dark} position={o.pos} rotation-y={o.rot} />
      ))}
    </group>
  );
}

/** Grand hall en L : aile est, aile ouest à loggia de bois, porche sud, et trône. */
export function GreatHall() {
  const M = useMemo(getMaterials, []);
  const H = DIM.greatHall;
  const L = H.loggia;
  const [wx, wz] = H.west.center;
  const [ww, wd] = H.west.size;
  const southZ = wz + wd / 2;
  const postH = H.west.eaves - 0.5;
  const posts = Array.from({ length: L.posts }, (_, i) => wx - ww / 2 + 0.8 + (i * (ww - 1.6)) / (L.posts - 1));
  const Th = DIM.throne;
  return (
    <group name="great_hall">
      <Building name="great_hall_east" {...H.east} doorDir={[-1, 0]} door={[2.6, 4.2]} />
      <Building name="great_hall_west" {...H.west} windows={false} />
      <Building name="great_hall_porch" {...H.porch} doorDir={[0, 1]} door={[2.4, 3.6]} windows={false} />
      <group name="loggia">
        {posts.map((x, i) => (
          <mesh key={i} position={[x, postH / 2, southZ + L.depth - 0.4]} material={M.woodDark} castShadow>
            <boxGeometry args={[0.6, postH, 0.6]} />
          </mesh>
        ))}
        <mesh position={[wx, L.floorY, southZ + L.depth / 2]} material={M.wood(ww, L.depth)} castShadow receiveShadow>
          <boxGeometry args={[ww, 0.4, L.depth]} />
        </mesh>
        {[L.railHeight, L.railHeight / 2].map((h, i) => (
          <mesh key={i} position={[wx, L.floorY + h, southZ + L.depth - 0.15]} material={M.woodDark}>
            <boxGeometry args={[ww, 0.15, 0.15]} />
          </mesh>
        ))}
        <mesh
          position={[wx, H.west.eaves - 0.9, southZ + L.depth / 2 - 0.1]}
          rotation-x={Math.atan2(0.9, L.depth)}
          material={M.slatePlain}
          castShadow
        >
          <boxGeometry args={[ww + 0.4, 0.35, L.depth + 0.6]} />
        </mesh>
      </group>
      <group name="throne" position={[wx, 0, southZ + 1.3]}>
        <mesh position={[0, Th.daisHeight / 2, 0]} material={M.carpet} receiveShadow>
          <boxGeometry args={[Th.daisSize[0], Th.daisHeight, Th.daisSize[1]]} />
        </mesh>
        <mesh position={[0, Th.daisHeight + 0.25, 0.2]} material={M.gold} castShadow>
          <boxGeometry args={[1.4, 0.5, 1.2]} />
        </mesh>
        <mesh position={[0, Th.daisHeight + 1.1, -0.45]} material={M.gold} castShadow>
          <boxGeometry args={[1.4, 2.2, 0.3]} />
        </mesh>
      </group>
    </group>
  );
}

/** Petite tour carrée à toit rouge et belvédère ouvert, à l'ouest du donjon (armurerie). */
export function Armory() {
  const M = useMemo(getMaterials, []);
  const A = DIM.armory;
  const [cx, cz] = A.center;
  const bodyH = A.bodyTop - A.bottom;
  const roof = useMemo(() => pyramidGeometry(A.roofSide, A.roofHeight), [A]);
  const parapet = useMemo(() => rectParapetGeometry(A.size, A.size, 0.8, A.parapetTop - A.bodyTop), [A]);
  const slit = useMemo(() => archGeometry(0.9, 2.2, 0.3), []);
  const mat = M.stone(A.size, bodyH);
  const core = A.size - 2 * A.belvedereInset;
  const belvH = A.belvedereTop - A.parapetTop;
  return (
    <group name="armory" position={[cx, 0, cz]}>
      <mesh position={[0, (A.bodyTop + A.bottom) / 2, 0]} material={[mat, mat, M.stonePlain, M.stonePlain, mat, mat]} castShadow receiveShadow>
        <boxGeometry args={[A.size, bodyH, A.size]} />
      </mesh>
      <mesh position={[0, (1.6 + A.bottom) / 2, 0]} material={M.plinth}>
        <boxGeometry args={[A.size + 0.3, 1.6 - A.bottom, A.size + 0.3]} />
      </mesh>
      <mesh geometry={parapet} position={[0, A.bodyTop, 0]} material={M.stonePlain} castShadow />
      <mesh position={[0, A.parapetTop + belvH / 2, 0]} material={M.dark} castShadow>
        <boxGeometry args={[core, belvH, core]} />
      </mesh>
      {[-1, 1].map((sx) =>
        [-1, 1].map((sz) => (
          <mesh key={`${sx}${sz}`} position={[(sx * core) / 2, A.parapetTop + (belvH + 0.3) / 2, (sz * core) / 2]} material={M.woodDark} castShadow>
            <boxGeometry args={[0.8, belvH + 0.3, 0.8]} />
          </mesh>
        )),
      )}
      <mesh geometry={roof} position={[0, A.belvedereTop, 0]} material={M.tilePlain} castShadow />
      <mesh geometry={slit} material={M.dark} position={[0, 12, A.size / 2 + 0.05]} />
      <mesh geometry={slit} material={M.dark} position={[0, 18, A.size / 2 + 0.05]} />
      <mesh geometry={slit} material={M.dark} position={[0, 15, -A.size / 2 - 0.05]} rotation-y={Math.PI} />
    </group>
  );
}

/** Enclos de quarantaine en bois (ajout hors images) avec deux caisses. */
export function QuarantinePen() {
  const M = useMemo(getMaterials, []);
  const Q = DIM.quarantinePen;
  const [cx, cz] = Q.center;
  const [w, d] = Q.size;
  const posts: [number, number][] = [];
  const nx = Math.round(w / Q.postSpacing);
  const nz = Math.round(d / Q.postSpacing);
  for (let i = 0; i <= nx; i++) {
    const x = -w / 2 + (i * w) / nx;
    posts.push([x, -d / 2], [x, d / 2]);
  }
  for (let j = 1; j < nz; j++) {
    const z = -d / 2 + (j * d) / nz;
    posts.push([-w / 2, z], [w / 2, z]);
  }
  const rails: { pos: [number, number, number]; size: [number, number, number] }[] = [];
  for (const h of [Q.postHeight - 0.3, Q.postHeight / 2]) {
    rails.push({ pos: [0, h, -d / 2], size: [w, 0.18, 0.18] }, { pos: [0, h, d / 2], size: [w, 0.18, 0.18] });
    rails.push({ pos: [w / 2, h, 0], size: [0.18, 0.18, d] }, { pos: [-w / 2, h, 0], size: [0.18, 0.18, d] });
  }
  return (
    <group name="quarantine_pen" position={[cx, 0, cz]}>
      {posts.map(([x, z], i) => (
        <mesh key={i} position={[x, Q.postHeight / 2, z]} material={M.woodDark} castShadow>
          <boxGeometry args={[0.45, Q.postHeight, 0.45]} />
        </mesh>
      ))}
      {rails.map((r, i) => (
        <mesh key={`r${i}`} position={r.pos} material={M.woodDark} castShadow>
          <boxGeometry args={r.size} />
        </mesh>
      ))}
      <mesh name="quarantine_crate_0" position={[-2, 0.8, 1]} rotation-y={0.3} material={M.wood(1.6, 1.6)} castShadow>
        <boxGeometry args={[1.6, 1.6, 1.6]} />
      </mesh>
      <mesh name="quarantine_crate_1" position={[1.6, 0.7, -1.4]} rotation-y={-0.5} material={M.wood(1.4, 1.4)} castShadow>
        <boxGeometry args={[1.4, 1.4, 1.4]} />
      </mesh>
    </group>
  );
}
