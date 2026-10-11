'use client';
import { useMemo } from 'react';
import { DIM } from './params';
import { Ground } from './parts/Ground';
import { CurtainWalls } from './parts/Walls';
import { RoundTower, type RoundTowerProps } from './parts/RoundTower';
import { Keep } from './parts/Keep';
import { Gatehouse } from './parts/Gatehouse';
import { MidTower } from './parts/MidTower';
import { Armory, Building, GreatHall, QuarantinePen } from './parts/Buildings';

export interface CastleProps {
  /** Un identifiant par serveur MCP : les 4 premiers occupent les angles, les suivants les emplacements `extraSlots`. */
  towerIds?: readonly string[];
}

export const DEFAULT_TOWER_IDS: readonly string[] = DIM.tower.corners.map((c) => c.id);

/** Calcule les tours rondes à afficher pour une liste d'identifiants. */
export function towerLayout(towerIds: readonly string[]): RoundTowerProps[] {
  const towers: RoundTowerProps[] = DIM.tower.corners.map((c, i) => ({
    name: `tower_${towerIds[i] ?? `unassigned_${c.id}`}`,
    position: c.pos,
    scale: 1,
    windowDirs: [
      [Math.sign(c.pos[0]), 0],
      [0, Math.sign(c.pos[1])],
    ],
  }));
  towerIds.slice(DIM.tower.corners.length).forEach((id, i) => {
    const slot = DIM.tower.extraSlots[i];
    if (!slot) return;
    const dir: [number, number] = Math.abs(slot[0]) > Math.abs(slot[1]) ? [Math.sign(slot[0]), 0] : [0, Math.sign(slot[1])];
    towers.push({ name: `tower_${id}`, position: slot, scale: DIM.tower.extra.scale, windowDirs: [dir] });
  });
  return towers;
}

/** Le château complet, segmenté en groupes nommés adressables par le code d'animation. */
export function Castle({ towerIds = DEFAULT_TOWER_IDS }: CastleProps) {
  const towers = useMemo(() => towerLayout(towerIds), [towerIds]);
  return (
    <group name="castle">
      <Ground />
      <CurtainWalls />
      {towers.map((t) => (
        <RoundTower key={t.name} {...t} />
      ))}
      <Keep />
      <Gatehouse />
      <MidTower variant="watchtower" />
      <MidTower variant="mail_post" />
      <GreatHall />
      <Building name="treasury" {...DIM.treasury} doorDir={[1, 0]} />
      <Building name="library" {...DIM.library} doorDir={[1, 0]} />
      <Building name="barracks" {...DIM.barracks} doorDir={[-1, 0]} />
      <Building name="stables" {...DIM.stables} doorDir={[0, 1]} door={[4, 4.5]} />
      <Armory />
      <QuarantinePen />
    </group>
  );
}

/** Éclairage commun : soleil principal au sud-est (faces avant éclairées), contre-jour doux au nord-ouest. */
export function CastleLights() {
  const S = DIM.sun;
  // three ≥ r155 : unités physiques, une face blanche éclairée à intensité π rend 1.0.
  const k = Math.PI;
  return (
    <>
      <ambientLight intensity={S.ambient * k} />
      <hemisphereLight args={['#e3ebf2', '#6d7a57', S.hemisphere * k]} />
      <directionalLight position={[S.fill.position[0], S.fill.position[1], S.fill.position[2]]} intensity={S.fill.intensity * k} />
      <directionalLight
        position={[S.position[0], S.position[1], S.position[2]]}
        intensity={S.intensity * k}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-80}
        shadow-camera-right={80}
        shadow-camera-top={80}
        shadow-camera-bottom={-80}
        shadow-camera-near={10}
        shadow-camera-far={320}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
      />
    </>
  );
}
