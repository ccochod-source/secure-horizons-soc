'use client';
import { useMemo } from 'react';
import { DIM } from '../params';
import { getMaterials } from '../materials';
import { merlonRowGeometry } from '../geometry';

interface SegmentProps {
  name: string;
  length: number;
  position: [number, number, number];
  rotationY: number;
}

/** Tronçon de courtine : corps, soubassement, parapet et merlons côté extérieur (+z local). */
function Segment({ name, length, position, rotationY }: SegmentProps) {
  const M = useMemo(getMaterials, []);
  const w = DIM.wall;
  const height = w.top - w.bottom;
  const t = w.thickness;
  const merlons = useMemo(() => merlonRowGeometry(length, w.merlon, w.merlon.thickness), [length, w]);
  return (
    <group name={name} position={position} rotation-y={rotationY}>
      <mesh
        position={[0, (w.top + w.bottom) / 2, 0]}
        material={[M.stone(t, height), M.stone(t, height), M.stone(length, t), M.stonePlain, M.stone(length, height), M.stone(length, height)]}
        castShadow
        receiveShadow
      >
        <boxGeometry args={[length, height, t]} />
      </mesh>
      <mesh position={[0, (w.plinthTop + w.bottom) / 2, 0]} material={M.plinth}>
        <boxGeometry args={[length + 0.05, w.plinthTop - w.bottom, t + 0.3]} />
      </mesh>
      <mesh position={[0, w.top + w.parapet.lip / 2, t / 2 - w.parapet.thickness / 2]} material={M.stonePlain} castShadow>
        <boxGeometry args={[length, w.parapet.lip, w.parapet.thickness]} />
      </mesh>
      <mesh geometry={merlons} position={[0, w.top + w.parapet.lip, t / 2 - w.merlon.thickness / 2]} material={M.stonePlain} castShadow />
    </group>
  );
}

/** Les quatre courtines ; la sud est coupée pour la porte, la nord pour le donjon. */
export function CurtainWalls() {
  const w = DIM.wall;
  const t = w.thickness;
  const gateHalf = DIM.gate.size / 2;
  const keepHalf = DIM.keep.width / 2;
  const sLen = w.halfX - gateHalf;
  const nLen = w.halfX - keepHalf;
  const segs: SegmentProps[] = [
    { name: 'wall_south_west', length: sLen, position: [-(gateHalf + sLen / 2), 0, w.halfZ - t / 2], rotationY: 0 },
    { name: 'wall_south_east', length: sLen, position: [gateHalf + sLen / 2, 0, w.halfZ - t / 2], rotationY: 0 },
    { name: 'wall_north_west', length: nLen, position: [-(keepHalf + nLen / 2), 0, -(w.halfZ - t / 2)], rotationY: Math.PI },
    { name: 'wall_north_east', length: nLen, position: [keepHalf + nLen / 2, 0, -(w.halfZ - t / 2)], rotationY: Math.PI },
    { name: 'wall_west', length: 2 * w.halfZ, position: [-(w.halfX - t / 2), 0, 0], rotationY: -Math.PI / 2 },
    { name: 'wall_east', length: 2 * w.halfZ, position: [w.halfX - t / 2, 0, 0], rotationY: Math.PI / 2 },
  ];
  return (
    <group name="walls">
      {segs.map((s) => (
        <Segment key={s.name} {...s} />
      ))}
    </group>
  );
}
