'use client';
import { useMemo } from 'react';
import { DIM } from '../params';
import { getMaterials } from '../materials';
import { portcullisGeometry, pyramidGeometry, rectMerlonsGeometry, rectParapetGeometry, spandrelGeometry } from '../geometry';

/** Porte sud : tour-porche à toit rouge, passage voûté, herse (portcullis) et pont-levis (drawbridge). */
export function Gatehouse() {
  const M = useMemo(getMaterials, []);
  const G = DIM.gate;
  const D = DIM.drawbridge;
  const [cx, cz] = G.center;
  const s = G.size;
  const pierW = (s - G.arch.width) / 2;
  const bodyH = G.bodyTop - G.bottom;
  const spandrel = useMemo(() => spandrelGeometry(G.arch.width, G.arch.height, G.bodyTop, s), [G, s]);
  const parapet = useMemo(() => rectParapetGeometry(s, s, G.parapetThickness, G.parapetTop - G.bodyTop), [G, s]);
  const merlons = useMemo(() => rectMerlonsGeometry(s, s, G.merlon, G.parapetThickness), [G, s]);
  const roof = useMemo(() => pyramidGeometry(G.roofSide, G.roofHeight), [G]);
  const grille = useMemo(() => portcullisGeometry(G.arch.width - 0.4, G.arch.height - 0.6), [G]);
  const chainTop = 14;
  const chainLen = Math.hypot(chainTop - D.hingeY, D.length);
  const sideMat = M.stone(s, bodyH);
  const endMat = M.stone(pierW, bodyH);

  return (
    <group name="gate" position={[cx, 0, cz]}>
      {[-1, 1].map((sx) => (
        <mesh
          key={sx}
          position={[sx * (s / 2 - pierW / 2), (G.bodyTop + G.bottom) / 2, 0]}
          material={[sideMat, sideMat, M.stonePlain, M.stonePlain, endMat, endMat]}
          castShadow
          receiveShadow
        >
          <boxGeometry args={[pierW, bodyH, s]} />
        </mesh>
      ))}
      <mesh geometry={spandrel} material={M.stoneWorld} castShadow receiveShadow />
      <mesh position={[0, G.bottom / 2, 0]} material={M.plinth}>
        <boxGeometry args={[G.arch.width, -G.bottom, s]} />
      </mesh>
      {[-1, 1].map((sx) => (
        <mesh key={`p${sx}`} position={[sx * (s / 2 - pierW / 2), (G.plinthTop + G.bottom) / 2, 0]} material={M.plinth}>
          <boxGeometry args={[pierW + 0.3, G.plinthTop - G.bottom, s + 0.3]} />
        </mesh>
      ))}
      <mesh geometry={parapet} position={[0, G.bodyTop, 0]} material={M.stonePlain} castShadow />
      <mesh geometry={merlons} position={[0, G.parapetTop, 0]} material={M.stonePlain} castShadow />
      <mesh geometry={roof} position={[0, G.roofBase, 0]} material={M.tilePlain} castShadow />
      <mesh position={[0, G.roofBase + G.roofHeight + 0.4, 0]} material={M.iron}>
        <coneGeometry args={[0.35, 1, 6]} />
      </mesh>

      {/* porte de bois à deux vantaux, en retrait dans le passage voûté (fixe) */}
      <group name="gate_doors" position={[0, 0.1, -s / 2 + 0.4]}>
        {[-1, 1].map((sx) => (
          <mesh key={sx} material={M.wood(G.arch.width / 2, G.arch.height)} castShadow position={[sx * (G.arch.width / 2 - 0.9) / 2, (G.arch.height - 1) / 2, 0]}>
            <boxGeometry args={[G.arch.width / 2 - 0.3, G.arch.height - 1, 0.4]} />
          </mesh>
        ))}
        {[2, 5, 8].map((y) => (
          <mesh key={`b${y}`} material={M.iron} position={[0, y, 0.22]}>
            <boxGeometry args={[G.arch.width - 0.6, 0.35, 0.12]} />
          </mesh>
        ))}
        {[-1, 1].map((sx) => (
          <mesh key={`k${sx}`} material={M.iron} position={[sx * 0.6, 4.5, 0.26]}>
            <sphereGeometry args={[0.28, 8, 6]} />
          </mesh>
        ))}
      </group>
      {/* herse relevée au repos (position haute) ; l'animateur l'abaisse pour fermer */}
      <mesh name="portcullis" geometry={grille} position={[0, G.arch.height - 0.7, G.portcullisZ]} material={M.iron} castShadow />

      <group name="drawbridge" position={[0, D.hingeY, s / 2]}>
        <mesh position={[0, 0, D.length / 2]} material={M.wood(D.width, D.length)} castShadow receiveShadow>
          <boxGeometry args={[D.width, D.thickness, D.length]} />
        </mesh>
        {[-1, 1].map((sx) => (
          <mesh key={sx} position={[sx * (D.width / 2 - 0.25), 0.4, D.length / 2]} material={M.woodDark} castShadow>
            <boxGeometry args={[0.3, 0.5, D.length]} />
          </mesh>
        ))}
      </group>
      {[-1, 1].map((sx) => (
        <mesh
          key={`c${sx}`}
          name={sx < 0 ? 'drawbridge_chain_l' : 'drawbridge_chain_r'}
          position={[sx * (D.width / 2 - 0.3), (chainTop + D.hingeY) / 2, s / 2 + D.length / 2]}
          rotation-x={Math.atan2(D.length, -(chainTop - D.hingeY))}
          material={M.iron}
        >
          <cylinderGeometry args={[0.1, 0.1, chainLen, 5]} />
        </mesh>
      ))}
    </group>
  );
}
