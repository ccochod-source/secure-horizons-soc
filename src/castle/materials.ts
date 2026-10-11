'use client';
import * as THREE from 'three';
import { PALETTE } from './params';

// Textures procédurales légères (canvas 2D), partagées par toute la scène.
// Échelle : une texture couvre TEX_UNITS × TEX_UNITS unités du modèle.
export const TEX_UNITS = 8;

type Draw = (ctx: CanvasRenderingContext2D, size: number) => void;

function makeTexture(size: number, draw: Draw): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  draw(ctx, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

// Générateur pseudo-aléatoire déterministe : le rendu est identique d'une capture à l'autre.
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function shade(hex: string, amount: number): string {
  const c = new THREE.Color(hex);
  c.offsetHSL(0, 0, amount);
  return '#' + c.getHexString();
}

function stoneTexture(base: string, seed: number): THREE.CanvasTexture {
  return makeTexture(256, (ctx, size) => {
    const rand = rng(seed);
    const blockW = 48, blockH = 24;
    ctx.fillStyle = PALETTE.mortar;
    ctx.fillRect(0, 0, size, size);
    for (let row = 0; row * blockH < size; row++) {
      const offset = row % 2 ? blockW / 2 : 0;
      for (let x = -blockW; x < size + blockW; x += blockW) {
        const w = blockW - 2, h = blockH - 2;
        ctx.fillStyle = shade(base, (rand() - 0.5) * 0.12);
        ctx.fillRect(x + offset + 1, row * blockH + 1, w, h);
        if (rand() < 0.12) {
          ctx.fillStyle = 'rgba(120,130,70,0.25)'; // mousse
          ctx.fillRect(x + offset + 4, row * blockH + 4, w * 0.5, h * 0.5);
        }
      }
    }
  });
}

function lineTexture(base: string, line: string, step: number, seed: number, tiles = false, vertical = false): THREE.CanvasTexture {
  return makeTexture(128, (ctx, size) => {
    const rand = rng(seed);
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, size, size);
    if (vertical) {
      ctx.translate(size, 0);
      ctx.rotate(Math.PI / 2);
    }
    for (let y = 0; y < size; y += step) {
      ctx.fillStyle = shade(base, (rand() - 0.5) * 0.08);
      ctx.fillRect(0, y, size, step);
      ctx.fillStyle = line;
      ctx.fillRect(0, y, size, 1.5);
      if (tiles) {
        const offset = (y / step) % 2 ? step : 0;
        for (let x = offset; x < size; x += step * 2) ctx.fillRect(x, y, 1.2, step);
      }
    }
  });
}

function speckleTexture(base: string, speckle: string, seed: number, count: number): THREE.CanvasTexture {
  return makeTexture(128, (ctx, size) => {
    const rand = rng(seed);
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = speckle;
    for (let i = 0; i < count; i++) ctx.fillRect(rand() * size, rand() * size, 2 + rand() * 3, 1.5);
  });
}

function gridTexture(base: string, line: string, step: number, seed: number): THREE.CanvasTexture {
  return makeTexture(128, (ctx, size) => {
    const rand = rng(seed);
    ctx.fillStyle = base;
    ctx.fillRect(0, 0, size, size);
    for (let y = 0; y < size; y += step)
      for (let x = 0; x < size; x += step) {
        ctx.fillStyle = shade(base, (rand() - 0.5) * 0.06);
        ctx.fillRect(x, y, step, step);
      }
    ctx.fillStyle = line;
    for (let i = 0; i < size; i += step) {
      ctx.fillRect(0, i, size, 1);
      ctx.fillRect(i, 0, 1, size);
    }
  });
}

export interface CastleMaterials {
  earth: THREE.Material;
  /** Pierre en coordonnées monde (1 texture = TEX_UNITS u), pour les géométries extrudées. */
  stoneWorld: THREE.Material;
  plinth: THREE.Material;
  slatePlain: THREE.Material;
  tilePlain: THREE.Material;
  woodDark: THREE.Material;
  iron: THREE.Material;
  dark: THREE.Material;
  flag: THREE.Material;
  smoke: THREE.Material;
  ember: THREE.Material;
  gold: THREE.Material;
  carpet: THREE.Material;
  pigeon: THREE.Material;
  stonePlain: THREE.Material;
  grass: (w: number, h: number) => THREE.Material;
  water: (w: number, h: number) => THREE.Material;
  sand: (w: number, h: number) => THREE.Material;
  /** Pierre texturée, répétition calée sur les dimensions (u) de la face. */
  stone: (w: number, h: number, keep?: boolean) => THREE.Material;
  slate: (w: number, h: number) => THREE.Material;
  tile: (w: number, h: number) => THREE.Material;
  wood: (w: number, h: number) => THREE.Material;
}

let cache: CastleMaterials | null = null;

export function getMaterials(): CastleMaterials {
  if (cache) return cache;
  const stoneTex = stoneTexture(PALETTE.stone, 7);
  const keepTex = stoneTexture(PALETTE.stoneKeep, 11);
  const slateTex = lineTexture(PALETTE.slate, PALETTE.slateLine, 10, 3, false, true);
  const tileTex = lineTexture(PALETTE.tileRed, PALETTE.tileRedLine, 8, 5, true, true);
  const woodTex = lineTexture(PALETTE.wood, PALETTE.woodLine, 12, 9);
  const grassTex = speckleTexture(PALETTE.grass, PALETTE.grassSpeckle, 13, 90);
  const waterTex = speckleTexture(PALETTE.water, PALETTE.waterSpeckle, 17, 40);
  const sandTex = gridTexture(PALETTE.sand, PALETTE.sandLine, 32, 19);

  const repeated = new Map<string, THREE.Material>();
  const textured = (key: string, tex: THREE.Texture, w: number, h: number, extra: THREE.MeshStandardMaterialParameters = {}) => {
    const rw = Math.max(1, Math.round((w / TEX_UNITS) * 4) / 4);
    const rh = Math.max(1, Math.round((h / TEX_UNITS) * 4) / 4);
    const id = `${key}:${rw}:${rh}`;
    let mat = repeated.get(id);
    if (!mat) {
      const map = tex.clone();
      map.repeat.set(rw, rh);
      map.needsUpdate = true;
      mat = new THREE.MeshStandardMaterial({ map, roughness: 0.95, metalness: 0, flatShading: true, ...extra });
      mat.name = id;
      repeated.set(id, mat);
    }
    return mat;
  };
  const std = (name: string, params: THREE.MeshStandardMaterialParameters) => {
    const m = new THREE.MeshStandardMaterial({ roughness: 0.9, metalness: 0, flatShading: true, ...params });
    m.name = name;
    return m;
  };

  const worldStone = stoneTex.clone();
  worldStone.repeat.set(1 / TEX_UNITS, 1 / TEX_UNITS);
  worldStone.needsUpdate = true;

  cache = {
    earth: std('earth', { color: PALETTE.earth }),
    stoneWorld: std('stoneWorld', { map: worldStone, roughness: 0.95 }),
    plinth: std('plinth', { color: PALETTE.plinth }),
    slatePlain: std('slatePlain', { color: PALETTE.slate, flatShading: true }),
    tilePlain: std('tilePlain', { color: PALETTE.tileRed, flatShading: true }),
    woodDark: std('woodDark', { color: PALETTE.woodDark }),
    iron: std('iron', { color: PALETTE.iron, roughness: 0.6, metalness: 0.4 }),
    dark: std('dark', { color: PALETTE.dark }),
    flag: std('flag', { color: PALETTE.flag, side: THREE.DoubleSide }),
    smoke: std('smoke', { color: '#4a4744', transparent: true, opacity: 0.75, roughness: 1 }),
    ember: std('ember', { color: '#7a2e1c', emissive: '#c0391f', emissiveIntensity: 0.25 }),
    gold: std('gold', { color: PALETTE.gold, roughness: 0.5, metalness: 0.3 }),
    carpet: std('carpet', { color: PALETTE.carpet }),
    pigeon: std('pigeon', { color: PALETTE.pigeon }),
    stonePlain: std('stonePlain', { color: PALETTE.stone }),
    grass: (w, h) => textured('grass', grassTex, w, h),
    water: (w, h) => textured('water', waterTex, w, h, { roughness: 0.6, metalness: 0.02 }),
    sand: (w, h) => textured('sand', sandTex, w, h),
    stone: (w, h, keep = false) => textured(keep ? 'keep' : 'stone', keep ? keepTex : stoneTex, w, h),
    slate: (w, h) => textured('slate', slateTex, w, h),
    tile: (w, h) => textured('tile', tileTex, w, h),
    wood: (w, h) => textured('wood', woodTex, w, h),
  };
  return cache;
}
