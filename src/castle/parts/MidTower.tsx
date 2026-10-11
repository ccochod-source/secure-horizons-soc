'use client';
import { useMemo } from 'react';
import { DIM } from '../params';
import { getMaterials } from '../materials';
import { pyramidGeometry, rectMerlonsGeometry, rectParapetGeometry } from '../geometry';

/** Tour carrée à toit rouge au milieu des murs est/ouest : guet (watchtower, avec feu d'alarme) ou pigeonnier (mail_post). */
export function MidTower({ variant }: { variant: 'watchtower' | 'mail_post' }) {
  const M = useMemo(getMaterials, []);
  const T = DIM.midTower;
  const spec = variant === 'watchtower' ? T.west : T.east;
  const [cx, cz] = spec.pos;
  const s = T.size;
  const bodyH = T.bodyTop - T.bottom;
  const parapet = useMemo(() => rectParapetGeometry(s, s, T.parapetThickness, T.parapetTop - T.bodyTop), [T, s]);
  const merlons = useMemo(() => rectMerlonsGeometry(s, s, T.merlon, T.parapetThickness), [T, s]);
  const roof = useMemo(() => pyramidGeometry(T.roofSide, T.roofHeight), [T]);
  const core = s - 2 * T.belvedereInset;
  const belvH = T.belvedereTop - T.parapetTop;
  const mat = M.stone(s, bodyH);
  const holes = [-1.2, -0.4, 0.4, 1.2];

  return (
    <group name={spec.id} position={[cx, 0, cz]}>
      <mesh position={[0, (T.bodyTop + T.bottom) / 2, 0]} material={[mat, mat, M.stonePlain, M.stonePlain, mat, mat]} castShadow receiveShadow>
        <boxGeometry args={[s, bodyH, s]} />
      </mesh>
      <mesh position={[0, (T.plinthTop + T.bottom) / 2, 0]} material={M.plinth}>
        <boxGeometry args={[s + 0.3, T.plinthTop - T.bottom, s + 0.3]} />
      </mesh>
      <mesh geometry={parapet} position={[0, T.bodyTop, 0]} material={M.stonePlain} castShadow />
      <mesh geometry={merlons} position={[0, T.parapetTop, 0]} material={M.stonePlain} castShadow />
      <mesh position={[0, T.parapetTop + belvH / 2, 0]} material={M.dark} castShadow>
        <boxGeometry args={[core, belvH, core]} />
      </mesh>
      {[-1, 1].map((sx) =>
        [-1, 1].map((sz) => (
          <mesh key={`${sx}${sz}`} position={[sx * core / 2, T.parapetTop + (belvH + 0.4) / 2, sz * core / 2]} material={M.woodDark} castShadow>
            <boxGeometry args={[0.9, belvH + 0.4, 0.9]} />
          </mesh>
        )),
      )}
      <mesh geometry={roof} position={[0, T.belvedereTop, 0]} material={M.tilePlain} castShadow />
      <mesh position={[0, T.belvedereTop + T.roofHeight + 0.4, 0]} material={M.iron}>
        <coneGeometry args={[0.35, 1, 6]} />
      </mesh>

      {variant === 'watchtower' && (
        <group name="alarm_fire" position={[-(s / 2 + 1.2), T.parapetTop - 0.5, s / 2 + 1.2]}>
          <mesh position={[0, 0.5, 0]} material={M.iron} castShadow>
            <cylinderGeometry args={[0.9, 0.6, 1, 8]} />
          </mesh>
          <mesh name="alarm_ember" position={[0, 1, 0]} material={M.ember}>
            <sphereGeometry args={[0.5, 8, 6]} />
          </mesh>
          {/* colonne de fumée : trois volutes sombres, animées par l'animateur (scale 0 au repos) */}
          {[0, 1, 2, 3].map((i) => (
            <mesh key={i} name={`alarm_smoke_${i}`} position={[0, 2.5 + i * 3.4, 0]} material={M.smoke}>
              <sphereGeometry args={[1.8 + i * 0.7, 7, 6]} />
            </mesh>
          ))}
        </group>
      )}

      {variant === 'mail_post' && (
        <group name="pigeon_loft">
          {[-1, 1].map((sx) =>
            [1.4, 2.5].map((dy) =>
              holes.map((h) => (
                <mesh key={`${sx}${dy}${h}`} position={[sx * (core / 2 + 0.08), T.parapetTop + dy, h * 1.6]} material={M.pigeon}>
                  <boxGeometry args={[0.15, 0.6, 0.6]} />
                </mesh>
              )),
            ),
          )}
          {[[-3.5, 4.2], [2.8, -4.3], [4.1, 1.5]].map(([x, z], i) => (
            <mesh key={i} name={`pigeon_${i}`} position={[x, T.parapetTop + 0.35, z]} material={M.pigeon}>
              <sphereGeometry args={[0.35, 6, 5]} />
            </mesh>
          ))}
        </group>
      )}
    </group>
  );
}
