import type * as THREE from 'three';
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';

/** Exporte un objet (le groupe `castle`) en GLB binaire, noms de groupes conservés. */
export async function exportCastleGlb(root: THREE.Object3D): Promise<Blob> {
  const exporter = new GLTFExporter();
  const result = await exporter.parseAsync(root, { binary: true, onlyVisible: true });
  if (!(result instanceof ArrayBuffer)) throw new Error('Export GLB : résultat inattendu');
  return new Blob([result], { type: 'model/gltf-binary' });
}

export function downloadBlob(blob: Blob, filename: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}
