'use client';
import { useMemo } from 'react';
import { DIM } from '../params';
import { getMaterials } from '../materials';
import { archGeometry, domeGeometry, merlonRingGeometry } from '../geometry';

export interface RoundTowerProps {
  /** Nom du groupe, `tower_<id>`. */
  name: string;
  position: readonly [number, number];
  scale?: number;
  /** Directions (x, z) des faces donnant sur les douves, pour placer les fenêtres. */
  windowDirs: readonly (readonly [number, number])[];
}

/** Tour ronde à couronne machicoulée et dôme d'ardoise. */
export function RoundTower({ name, position, scale = 1, windowDirs }: RoundTowerProps) {
  const M = useMemo(getMaterials, []);
  const T = DIM.tower;
  const shaftH = T.shaftTop - T.bottom;
  const merlons = useMemo(() => merlonRingGeometry(T.crownRadius, T.merlonCount, T.merlonWidth, T.merlonHeight, T.crownWall), [T]);
  const dome = useMemo(() => domeGeometry(T.domeRadius, T.domeHeight, T.segments), [T]);
  const win = useMemo(() => archGeometry(1.2, 2.6, 0.3), []);
  const finialY = T.crownTop + T.domeHeight;
  const half = Math.PI / T.segments; // les facettes du fût font face aux directions cardinales

  return (
    <group name={name} position={[position[0], 0, position[1]]} scale={[scale, scale, scale]}>
      <mesh position={[0, (T.shaftTop + T.bottom) / 2, 0]} rotation-y={half} material={M.stone(2 * Math.PI * T.radius, shaftH)} castShadow receiveShadow>
        <cylinderGeometry args={[T.radius, T.radius, shaftH, T.segments]} />
      </mesh>
      <mesh position={[0, (T.plinthTop + T.bottom) / 2, 0]} rotation-y={half} material={M.plinth}>
        <cylinderGeometry args={[T.radius + 0.15, T.radius + 0.15, T.plinthTop - T.bottom, T.segments]} />
      </mesh>
      <mesh position={[0, T.shaftTop + T.corbelHeight / 2, 0]} rotation-y={half} material={M.dark}>
        <cylinderGeometry args={[T.radius + 0.5, T.radius + 0.2, T.corbelHeight, T.segments]} />
      </mesh>
      <mesh position={[0, (T.flareTop + T.shaftTop + T.corbelHeight) / 2, 0]} rotation-y={half} material={M.stonePlain} castShadow>
        <cylinderGeometry args={[T.crownRadius, T.radius + 0.5, T.flareTop - T.shaftTop - T.corbelHeight, T.segments]} />
      </mesh>
      <mesh
        position={[0, (T.crownTop + T.flareTop) / 2, 0]}
        rotation-y={half}
        material={M.stone(2 * Math.PI * T.crownRadius, T.crownTop - T.flareTop)}
        castShadow
      >
        <cylinderGeometry args={[T.crownRadius, T.crownRadius, T.crownTop - T.flareTop, T.segments]} />
      </mesh>
      <mesh geometry={merlons} position={[0, T.crownTop, 0]} material={M.stonePlain} castShadow />
      <mesh name={`${name}_dome`} geometry={dome} position={[0, T.crownTop, 0]} material={M.slatePlain} castShadow />
      <mesh position={[0, finialY + T.finial.drumHeight / 2, 0]} material={M.slatePlain}>
        <cylinderGeometry args={[T.finial.drumRadius, T.finial.drumRadius, T.finial.drumHeight, 8]} />
      </mesh>
      <mesh position={[0, finialY + T.finial.drumHeight + T.finial.ballRadius * 0.9, 0]} material={M.slatePlain}>
        <sphereGeometry args={[T.finial.ballRadius, 8, 6]} />
      </mesh>
      {windowDirs.map(([dx, dz], i) => {
        const a = Math.atan2(dx, dz);
        return T.windowHeights.map((h, j) => (
          <mesh
            key={`${i}-${j}`}
            geometry={win}
            material={M.dark}
            position={[(T.radius + 0.05) * Math.sin(a), h, (T.radius + 0.05) * Math.cos(a)]}
            rotation-y={a}
          />
        ));
      })}
    </group>
  );
}
