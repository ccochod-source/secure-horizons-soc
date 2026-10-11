'use client';
import { useMemo } from 'react';
import { DIM } from '../params';
import { getMaterials } from '../materials';
import { archGeometry, flagGeometry, rectMerlonsGeometry, rectParapetGeometry } from '../geometry';

/** Donjon : fût, couronne machicoulée, drapeau, porte sur la cour (keep_door) et porte arrière (rear_gate). */
export function Keep() {
  const M = useMemo(getMaterials, []);
  const K = DIM.keep;
  const [cx, cz] = K.center;
  const shaftH = K.shaftTop - K.bottom;
  const cw = K.width + 2 * K.crownOverhang;
  const cd = K.depth + 2 * K.crownOverhang;
  const parapet = useMemo(() => rectParapetGeometry(cw, cd, K.parapetThickness, K.parapetTop - K.crownBase), [cw, cd, K]);
  const merlons = useMemo(() => rectMerlonsGeometry(cw, cd, K.merlon, K.parapetThickness), [cw, cd, K]);
  const flag = useMemo(() => flagGeometry(K.flag[0], K.flag[1]), [K]);
  const winTwin = useMemo(() => archGeometry(1.3, 3, 0.3), []);
  const winMid = useMemo(() => archGeometry(1.6, 3.6, 0.3), []);
  const slit = useMemo(() => archGeometry(0.9, 2.4, 0.3), []);
  const door = useMemo(() => archGeometry(K.door.width, K.door.height, 0.4), [K]);
  const rear = useMemo(() => archGeometry(K.rearGate.width, K.rearGate.height, 0.4), [K]);
  const south = K.depth / 2 + 0.05;
  const north = -K.depth / 2 - 0.05;
  const sideMat = M.stone(K.depth, shaftH, true);
  const frontMat = M.stone(K.width, shaftH, true);
  const A = K.awning;
  const flagTop = K.crownBase + K.flagPole;

  return (
    <group name="keep" position={[cx, 0, cz]}>
      <mesh position={[0, (K.shaftTop + K.bottom) / 2, 0]} material={[sideMat, sideMat, M.stonePlain, M.stonePlain, frontMat, frontMat]} castShadow receiveShadow>
        <boxGeometry args={[K.width, shaftH, K.depth]} />
      </mesh>
      <mesh position={[0, (K.plinthTop + K.bottom) / 2, 0]} material={M.plinth}>
        <boxGeometry args={[K.width + 0.3, K.plinthTop - K.bottom, K.depth + 0.3]} />
      </mesh>
      <mesh position={[0, (K.crownBase + K.shaftTop) / 2, 0]} material={M.stonePlain} castShadow>
        <boxGeometry args={[cw, K.crownBase - K.shaftTop, cd]} />
      </mesh>
      <mesh geometry={parapet} position={[0, K.crownBase, 0]} material={M.stonePlain} castShadow />
      <mesh geometry={merlons} position={[0, K.parapetTop, 0]} material={M.stonePlain} castShadow />

      <group name="flag" position={[0, K.crownBase, 0]}>
        <mesh position={[0, K.flagPole / 2, 0]} material={M.iron}>
          <cylinderGeometry args={[0.15, 0.15, K.flagPole, 6]} />
        </mesh>
        <mesh geometry={flag} position={[0.15, K.flagPole - K.flag[1] / 2, 0]} material={M.flag} castShadow />
      </group>

      {/* fenêtres : face sud (cour) */}
      <mesh geometry={winTwin} material={M.dark} position={[-1.4, 43.5, south]} />
      <mesh geometry={winTwin} material={M.dark} position={[1.4, 43.5, south]} />
      <mesh geometry={winMid} material={M.dark} position={[0, 29, south]} />
      <mesh geometry={slit} material={M.dark} position={[-4.2, 19, south]} />
      <mesh geometry={slit} material={M.dark} position={[4.2, 19, south]} />
      {/* face nord (douves) */}
      <mesh geometry={winTwin} material={M.dark} position={[-1.4, 43.5, north]} rotation-y={Math.PI} />
      <mesh geometry={winTwin} material={M.dark} position={[1.4, 43.5, north]} rotation-y={Math.PI} />
      <mesh geometry={winMid} material={M.dark} position={[0, 36, north]} rotation-y={Math.PI} />
      <mesh geometry={slit} material={M.dark} position={[-4.2, 28, north]} rotation-y={Math.PI} />
      <mesh geometry={slit} material={M.dark} position={[4.2, 28, north]} rotation-y={Math.PI} />
      {/* faces est / ouest */}
      <mesh geometry={slit} material={M.dark} position={[-K.width / 2 - 0.05, 26, 0]} rotation-y={-Math.PI / 2} />
      <mesh geometry={slit} material={M.dark} position={[K.width / 2 + 0.05, 26, 0]} rotation-y={Math.PI / 2} />
      <mesh geometry={slit} material={M.dark} position={[-K.width / 2 - 0.05, 40, 0]} rotation-y={-Math.PI / 2} />
      <mesh geometry={slit} material={M.dark} position={[K.width / 2 + 0.05, 40, 0]} rotation-y={Math.PI / 2} />

      <group name="keep_door" position={[0, 0, south]}>
        <mesh geometry={door} material={M.dark} />
      </group>

      <group name="rear_gate" position={[0, 0, north]}>
        <mesh geometry={rear} material={M.dark} rotation-y={Math.PI} />
        <group name="rear_gate_door" position={[-K.rearGate.width / 2 + 0.2, 0, -0.15]}>
          <mesh position={[K.rearGate.width / 2 - 0.2, (K.rearGate.height - 0.4) / 2, 0]} material={M.woodDark} castShadow>
            <boxGeometry args={[K.rearGate.width - 0.4, K.rearGate.height - 0.4, 0.3]} />
          </mesh>
        </group>
      </group>

      {/* auvent d'ardoise sur la face nord (visible sur la vue arrière) */}
      <mesh
        name="keep_awning"
        position={[0, A.y + A.drop / 2, north - A.depth / 2]}
        rotation-x={-Math.atan2(A.drop, A.depth)}
        material={M.slatePlain}
        castShadow
      >
        <boxGeometry args={[A.width, 0.4, Math.hypot(A.depth, A.drop) + 0.3]} />
      </mesh>
      <mesh position={[0, flagTop + 0.2, 0]} material={M.iron}>
        <sphereGeometry args={[0.3, 6, 4]} />
      </mesh>
    </group>
  );
}
