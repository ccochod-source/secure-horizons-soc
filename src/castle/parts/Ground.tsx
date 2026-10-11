'use client';
import { useMemo } from 'react';
import { DIM } from '../params';
import { getMaterials } from '../materials';

type V3 = [number, number, number];

/** Plateforme herbeuse, douves, cour pavée, route arrière (supply_road) et route d'accès. */
export function Ground() {
  const M = useMemo(getMaterials, []);
  const { platform, moat, wall, supplyRoad, keep, road, drawbridge, gate } = DIM;
  const half = platform.size / 2;
  const h = platform.height;
  const bandX = half - moat.outerHalfX;
  const bandZ = half - moat.outerHalfZ;
  const innerLen = platform.size - 2 * bandZ;
  const bands: { name: string; size: V3; pos: V3 }[] = [
    { name: 'north', size: [platform.size, h, bandZ], pos: [0, -h / 2, -(half - bandZ / 2)] },
    { name: 'south', size: [platform.size, h, bandZ], pos: [0, -h / 2, half - bandZ / 2] },
    { name: 'west', size: [bandX, h, innerLen], pos: [-(half - bandX / 2), -h / 2, 0] },
    { name: 'east', size: [bandX, h, innerLen], pos: [half - bandX / 2, -h / 2, 0] },
  ];
  const keepNorthZ = keep.center[1] - keep.depth / 2;
  const supplyLen = half + keepNorthZ;
  const roadStart = gate.center[1] + gate.size / 2 + drawbridge.length;
  const roadLen = half - roadStart;

  return (
    <group name="ground">
      <group name="platform">
        {bands.map((b) => (
          <mesh
            key={b.name}
            name={`platform_${b.name}`}
            position={b.pos}
            material={[M.earth, M.earth, M.grass(b.size[0], b.size[2]), M.earth, M.earth, M.earth]}
            receiveShadow
          >
            <boxGeometry args={b.size} />
          </mesh>
        ))}
      </group>
      <mesh name="moat" position={[0, moat.waterY, 0]} rotation-x={-Math.PI / 2} material={M.water(2 * moat.outerHalfX, 2 * moat.outerHalfZ)} receiveShadow>
        <planeGeometry args={[2 * moat.outerHalfX, 2 * moat.outerHalfZ]} />
      </mesh>
      <mesh
        name="courtyard"
        position={[0, -h / 2, 0]}
        material={[M.plinth, M.plinth, M.sand(2 * wall.halfX, 2 * wall.halfZ), M.plinth, M.plinth, M.plinth]}
        receiveShadow
      >
        <boxGeometry args={[2 * wall.halfX - 0.4, h, 2 * wall.halfZ - 0.4]} />
      </mesh>
      <mesh name="supply_road" position={[0, supplyRoad.y, (keepNorthZ - half) / 2]} material={M.wood(supplyRoad.width, supplyLen)} castShadow receiveShadow>
        <boxGeometry args={[supplyRoad.width, supplyRoad.thickness, supplyLen]} />
      </mesh>
      <mesh name="road" position={[0, 0.15, roadStart + roadLen / 2]} material={M.wood(road.width, roadLen)} receiveShadow>
        <boxGeometry args={[road.width, 0.3, roadLen]} />
      </mesh>
    </group>
  );
}
