import * as THREE from 'three';
import { DIM, PALETTE } from '../params';
import { Tweens, easeIn, easeOut, linear } from './tween';
import { makeArrow, makeFigure, idlePose, walkPose, type Figure, type FigureKind } from './figures';

export type AlarmLevel = 'off' | 'Faible' | 'Modérée' | 'Élevée' | 'Critique';
export type PulseKind = 'allowed' | 'flagged' | 'blocked';

const PULSE_COLOR: Record<PulseKind, string> = { allowed: '#49c26b', flagged: '#f0a93a', blocked: '#e0433c' };
const ALARM_SCALE: Record<AlarmLevel, number> = { off: 0, Faible: 0.5, Modérée: 0.75, Élevée: 1, Critique: 1.25 };
const PORTCULLIS_LIFT = DIM.gate.arch.height - 1;

/**
 * Pilote le château par les noms de groupes : fonctionne sur le modèle procédural comme sur castle.glb.
 * Chaque action retourne une promesse résolue à la fin du mouvement, pour enchaîner des scénarios.
 */
export class CastleAnimator {
  readonly tweens = new Tweens();
  private readonly materials = new Map<THREE.Mesh, THREE.MeshStandardMaterial>();
  private readonly props = new THREE.Group();
  private alarm: AlarmLevel = 'off';
  private quarantined = new Map<string, THREE.Mesh>();
  private crateMaterial: THREE.Material | null = null;
  private pigeonMaterial: THREE.Material | null = null;
  gateOpen = true;

  /** Identifiants des caisses actuellement en quarantaine. */
  quarantinedIds(): string[] {
    return [...this.quarantined.keys()];
  }

  constructor(readonly root: THREE.Object3D) {
    this.props.name = 'animated_props';
    root.add(this.props);
    // Au repos, la herse est relevée (porte ouverte) : on la place en position haute si besoin.
    const portcullis = this.find('portcullis');
    if (portcullis && this.gateOpen && portcullis.position.y < 2) portcullis.position.y = DIM.gate.arch.height - 0.7;
    for (let i = 0; i < 4; i++) this.find(`alarm_smoke_${i}`)?.scale.setScalar(0.001);
    this.tweens.loop('flag', (t) => {
      const flag = this.find('flag');
      if (flag) flag.rotation.y = Math.sin(t * 1.3) * 0.12;
    });
  }

  update(dt: number) {
    this.tweens.update(dt);
  }

  dispose() {
    this.root.remove(this.props);
  }

  find(name: string): THREE.Object3D | null {
    return this.root.getObjectByName(name) ?? null;
  }

  /** Matériau propre à un mesh (les matériaux du modèle sont partagés). */
  private ownMaterial(mesh: THREE.Mesh): THREE.MeshStandardMaterial {
    let m = this.materials.get(mesh);
    if (!m) {
      const src = (Array.isArray(mesh.material) ? mesh.material[0] : mesh.material) as THREE.MeshStandardMaterial;
      m = src.clone();
      mesh.material = m;
      this.materials.set(mesh, m);
    }
    return m;
  }

  private firstMesh(obj: THREE.Object3D | null, predicate?: (m: THREE.Mesh) => boolean): THREE.Mesh | null {
    let found: THREE.Mesh | null = null;
    obj?.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!found && m.isMesh && (!predicate || predicate(m))) found = m;
    });
    return found;
  }

  /** Éclat émissif sur un mesh. */
  async glow(mesh: THREE.Mesh | null, color: string, duration = 1.2, intensity = 1.4) {
    if (!mesh) return;
    const m = this.ownMaterial(mesh);
    m.emissive.set(color);
    await this.tweens.run(duration, (k) => {
      m.emissiveIntensity = intensity * Math.sin(k * Math.PI);
    });
    m.emissiveIntensity = 0;
  }

  // --- porte -------------------------------------------------------------

  async raisePortcullis() {
    const p = this.find('portcullis');
    if (!p) return;
    const from = p.position.y;
    await this.tweens.run(1.6, (k) => void (p.position.y = from + (PORTCULLIS_LIFT + 0.3 - from) * k), { ease: easeOut, tag: 'portcullis' });
  }

  async lowerPortcullis() {
    const p = this.find('portcullis');
    if (!p) return;
    const from = p.position.y;
    await this.tweens.run(0.7, (k) => void (p.position.y = from + (0.3 - from) * k), { ease: easeIn, tag: 'portcullis' });
  }

  async raiseDrawbridge() {
    const d = this.find('drawbridge');
    if (!d) return;
    const from = d.rotation.x;
    this.find('drawbridge_chain_l')?.scale.setScalar(0.001);
    this.find('drawbridge_chain_r')?.scale.setScalar(0.001);
    await this.tweens.run(2.2, (k) => void (d.rotation.x = from + (-Math.PI / 2 + 0.08 - from) * k), { tag: 'drawbridge' });
  }

  async lowerDrawbridge() {
    const d = this.find('drawbridge');
    if (!d) return;
    const from = d.rotation.x;
    await this.tweens.run(1.8, (k) => void (d.rotation.x = from * (1 - k)), { ease: easeIn, tag: 'drawbridge' });
    this.find('drawbridge_chain_l')?.scale.setScalar(1);
    this.find('drawbridge_chain_r')?.scale.setScalar(1);
  }

  /** Ferme l'accès : herse baissée puis pont levé. */
  async closeGate() {
    this.gateOpen = false;
    await this.lowerPortcullis();
    await this.raiseDrawbridge();
  }

  async openGate() {
    this.gateOpen = true;
    await this.lowerDrawbridge();
    await this.raisePortcullis();
  }

  async openRearGate() {
    const door = this.find('rear_gate_door');
    if (!door) return;
    await this.tweens.run(1, (k) => void (door.rotation.y = -1.9 * k));
  }

  async closeRearGate() {
    const door = this.find('rear_gate_door');
    if (!door) return;
    const from = door.rotation.y;
    await this.tweens.run(1, (k) => void (door.rotation.y = from * (1 - k)));
  }

  // --- tours & alarme ------------------------------------------------------

  /** Pulsation colorée sur le dôme de `tower_<id>` (vert, ambre ou rouge) avec un léger sursaut. */
  async towerPulse(id: string, kind: PulseKind = 'allowed') {
    const tower = this.find(`tower_${id}`);
    if (!tower) return;
    const dome = this.firstMesh(tower, (m) => m.name.endsWith('_dome')) ?? this.firstMesh(tower);
    const base = tower.scale.y;
    void this.tweens.run(0.6, (k) => void (tower.scale.y = base * (1 + 0.04 * Math.sin(k * Math.PI))));
    await this.glow(dome, PULSE_COLOR[kind], kind === 'allowed' ? 0.9 : 1.6, kind === 'blocked' ? 2 : 1.4);
  }

  get alarmLevel() {
    return this.alarm;
  }

  /** Alarme sur la tour de guet : colonne de fumée qui monte du brasero ; `off` la dissipe. */
  async setAlarm(level: AlarmLevel) {
    this.alarm = level;
    const smoke = [0, 1, 2, 3].map((i) => this.find(`alarm_smoke_${i}`)).filter((o): o is THREE.Object3D => !!o);
    const ember = this.find('alarm_ember') as THREE.Mesh | null;
    if (!smoke.length) return;
    const target = ALARM_SCALE[level];
    const from = smoke[0].scale.x;
    if (level === 'off') {
      this.tweens.stopLoop('alarm');
      if (ember) this.ownMaterial(ember).emissiveIntensity = 0.25;
      await this.tweens.run(1.2, (k) => smoke.forEach((o) => o.scale.setScalar(Math.max(0.001, from * (1 - k)))));
      return;
    }
    if (ember) this.ownMaterial(ember).emissiveIntensity = 0.4 + 0.5 * target;
    await this.tweens.run(1, (k) => smoke.forEach((o, i) => o.scale.setScalar(Math.max(0.001, from + (target - from) * k * (1 - i * 0.12)))), { ease: easeOut });
    this.tweens.loop('alarm', (t) => {
      smoke.forEach((o, i) => {
        const s = target * (1 - i * 0.12) * (1 + 0.08 * Math.sin(t * 2.1 + i));
        o.scale.setScalar(s);
        o.position.x = Math.sin(t * 0.9 + i * 1.3) * 0.35 * (i + 1);
        o.position.z = Math.cos(t * 0.7 + i * 0.9) * 0.3 * (i + 1);
      });
    });
  }

  // --- caisses (packages) & livraisons -----------------------------------------

  private crate(name: string, size = 1.5): THREE.Mesh {
    if (!this.crateMaterial) {
      const ref = this.find('quarantine_crate_0') as THREE.Mesh | null;
      this.crateMaterial = ref ? (ref.material as THREE.Material) : new THREE.MeshStandardMaterial({ color: PALETTE.wood });
    }
    const m = new THREE.Mesh(new THREE.BoxGeometry(size, size, size), this.crateMaterial);
    m.name = name;
    m.castShadow = true;
    this.props.add(m);
    return m;
  }

  private async travel(obj: THREE.Object3D, path: [number, number, number][], speed = 9) {
    for (let i = 1; i < path.length; i++) {
      const a = new THREE.Vector3(...path[i - 1]);
      const b = new THREE.Vector3(...path[i]);
      const d = a.distanceTo(b);
      await this.tweens.run(d / speed, (k) => void obj.position.lerpVectors(a, b, k), { ease: linear });
    }
  }

  /** Une caisse franchit la porte et rejoint l'enclos de quarantaine. */
  async quarantine(packageId: string) {
    if (this.quarantined.has(packageId)) return;
    const pen = DIM.quarantinePen;
    const g = DIM.gate.center[1];
    const slot = this.quarantined.size;
    const dest: [number, number, number] = [pen.center[0] - 3 + (slot % 3) * 2.2, 0.75, pen.center[1] + 2.5 - Math.floor(slot / 3) * 2.2];
    const crate = this.crate(`package_${packageId}`);
    crate.position.set(0, 0.75, 52);
    this.quarantined.set(packageId, crate);
    const wasOpen = this.gateOpen;
    if (!wasOpen) await this.openGate();
    await this.travel(crate, [[0, 0.75, 52], [0, 0.75, g], [0, 0.75, pen.center[1]], dest]);
    await this.glow(crate, PULSE_COLOR.flagged, 1);
    if (!wasOpen) await this.closeGate();
  }

  /** Libère une caisse : elle sort par la porte arrière le long de la route de ravitaillement. */
  async release(packageId: string) {
    const crate = this.quarantined.get(packageId);
    if (!crate) return;
    this.quarantined.delete(packageId);
    const kz = DIM.keep.center[1];
    await this.glow(crate, PULSE_COLOR.allowed, 0.8);
    await this.openRearGate();
    await this.travel(crate, [crate.position.toArray() as [number, number, number], [DIM.keep.width / 2 + 3, 0.75, kz + DIM.keep.depth / 2 + 4], [DIM.keep.width / 2 + 3, 0.75, kz - DIM.keep.depth / 2 - 3], [0, 0.75, kz - DIM.keep.depth / 2 - 3], [0, 0.75, -52]]);
    await this.closeRearGate();
    this.props.remove(crate);
  }

  /** Livraison sortante par la porte arrière (sans passer par la quarantaine). */
  async dispatchSupply(id: string) {
    const kz = DIM.keep.center[1];
    const crate = this.crate(`supply_${id}`, 1.2);
    crate.position.set(0, 0.6, kz - DIM.keep.depth / 2 - 1);
    await this.openRearGate();
    await this.travel(crate, [[0, 0.6, kz - DIM.keep.depth / 2 - 1], [0, 0.6, -52]], 11);
    await this.closeRearGate();
    this.props.remove(crate);
  }

  // --- messages, trésor, bibliothèque, trône --------------------------------

  /** Un pigeon arrive de l'est et se pose sur le pigeonnier. */
  async mailArrive() {
    if (!this.pigeonMaterial) {
      const ref = this.find('pigeon_0') as THREE.Mesh | null;
      this.pigeonMaterial = ref ? (ref.material as THREE.Material) : new THREE.MeshStandardMaterial({ color: PALETTE.pigeon });
    }
    const bird = new THREE.Mesh(new THREE.SphereGeometry(0.4, 6, 5), this.pigeonMaterial);
    bird.name = 'pigeon_inbound';
    this.props.add(bird);
    const post = DIM.midTower.east.pos;
    const land = new THREE.Vector3(post[0] - 2, DIM.midTower.parapetTop + 0.4, post[1] + 3.5);
    const start = new THREE.Vector3(85, 40, 30);
    await this.tweens.run(2.4, (k) => {
      bird.position.lerpVectors(start, land, k);
      bird.position.y += Math.sin(k * Math.PI) * 10 + Math.sin(k * 40) * 0.3;
    }, { ease: easeOut });
    await this.glow(this.firstMesh(this.find('mail_post')), '#ffffff', 0.8, 0.5);
    await this.tweens.wait(4);
    this.props.remove(bird);
  }

  private async doorFlash(building: string, kind: PulseKind) {
    const b = this.find(building);
    const door = this.firstMesh(b, (m) => (m.material as THREE.Material).name === 'dark') ?? this.firstMesh(b);
    await this.glow(door, PULSE_COLOR[kind], 1.2, 2.5);
  }

  treasuryAccess(kind: PulseKind = 'allowed') {
    return this.doorFlash('treasury', kind);
  }

  libraryAccess(kind: PulseKind = 'allowed') {
    return this.doorFlash('library', kind);
  }

  /** Halo sur le trône : une décision humaine est attendue. */
  private throneHome: THREE.Vector3 | null = null;
  private throneHomeScale = 1;

  /** Décision humaine attendue : le trône s'élève au-dessus du château, bien visible, et scintille. */
  async throneAttention(on = true) {
    const t = this.find('throne');
    if (!t) return;
    if (!this.throneHome) { this.throneHome = t.position.clone(); this.throneHomeScale = t.scale.x || 1; }
    const home = this.throneHome;
    this.tweens.cancel('throne_move');
    if (on) {
      if (!this.find('throne_beam')) {
        const beam = new THREE.PointLight('#ffd36b', 0, 160, 1.1);
        beam.name = 'throne_beam';
        beam.position.set(0, 22, 20);
        this.props.add(beam);
        void this.tweens.run(0.8, (k) => void (beam.intensity = 180 * k));
      }
      const from = t.position.clone();
      const fromScale = t.scale.x;
      await this.tweens.run(1.8, (k) => {
        t.position.set(from.x + (0 - from.x) * k, from.y + (14 - from.y) * k, from.z + (20 - from.z) * k);
        t.scale.setScalar(fromScale + (this.throneHomeScale * 1.7 - fromScale) * k);
      }, { ease: easeOut, tag: 'throne_move' });
      this.tweens.loop('throne', (time) => {
        t.rotation.y = time * 0.5;
        t.position.y = 14 + Math.sin(time * 1.2) * 1;
      });
    } else {
      this.tweens.stopLoop('throne');
      const from = t.position.clone();
      const fromScale = t.scale.x;
      const beam = this.find('throne_beam') as THREE.PointLight | null;
      await this.tweens.run(1.2, (k) => {
        t.position.lerpVectors(from, home, k);
        t.scale.setScalar(fromScale + (this.throneHomeScale - fromScale) * k);

        if (beam) beam.intensity = 180 * (1 - k);
      }, { ease: easeIn, tag: 'throne_move' });
      t.rotation.y = 0;
      if (beam) this.props.remove(beam);
    }
  }

  // --- bataille : guerriers, chevaliers, archers -----------------------------------

  private warriors: Figure[] = [];
  private defenders: Figure[] = [];
  private figureSeq = 0;
  private rand = 7;
  private random() {
    this.rand = (this.rand * 1664525 + 1013904223) >>> 0;
    return this.rand / 4294967296;
  }

  private spawn(kind: FigureKind, x: number, y: number, z: number): Figure {
    const f = makeFigure(kind);
    f.group.name = `${kind}_${this.figureSeq++}`;
    f.group.position.set(x, y, z);
    f.group.scale.setScalar(0.001);
    this.props.add(f.group);
    void this.tweens.run(0.4, (k) => void f.group.scale.setScalar(Math.max(0.001, 1.3 * k)), { ease: easeOut });
    (kind === 'warrior' ? this.warriors : this.defenders).push(f);
    return f;
  }

  private face(f: Figure, x: number, z: number) {
    const dx = x - f.group.position.x;
    const dz = z - f.group.position.z;
    if (Math.abs(dx) + Math.abs(dz) > 1e-3) f.group.rotation.y = Math.atan2(dx, dz);
  }

  /** Marche vers un point (y conservé), jambes animées. */
  async walk(f: Figure, x: number, z: number, speed = 7) {
    if (!f.alive) return;
    const from = f.group.position.clone();
    const to = new THREE.Vector3(x, from.y, z);
    const d = from.distanceTo(to);
    if (d < 0.01) return;
    this.face(f, x, z);
    const tag = `walk_${f.group.name}`;
    await this.tweens.run(d / speed, (k) => {
      if (!f.alive) return;
      f.group.position.lerpVectors(from, to, k);
      walkPose(f, k * d * 1.6);
      f.group.position.y = from.y + Math.abs(Math.sin(k * d * 1.6)) * 0.15;
    }, { ease: linear, tag });
    if (f.alive) {
      idlePose(f);
      f.group.position.y = from.y;
    }
  }

  /** Brandit l'arme (bras levé puis abaissé). */
  async swing(f: Figure) {
    const base = f.arm.rotation.x;
    await this.tweens.run(0.5, (k) => void (f.arm.rotation.x = base - 2.2 * Math.sin(k * Math.PI)));
  }

  /** Le personnage tombe et disparaît. */
  async fall(f: Figure) {
    if (!f.alive) return;
    f.alive = false;
    this.tweens.cancel(`walk_${f.group.name}`);
    const g = f.group;
    await this.tweens.run(0.6, (k) => void (g.rotation.x = -Math.PI / 2 * k), { ease: easeIn });
    await this.tweens.wait(1.5);
    await this.tweens.run(1, (k) => void (g.position.y -= 0.03 * k), { ease: linear });
    this.props.remove(g);
    this.warriors = this.warriors.filter((w) => w !== f);
    this.defenders = this.defenders.filter((w) => w !== f);
  }

  /** Tir d'une flèche d'un point vers un personnage ; le touche s'il est encore debout. */
  async shoot(from: THREE.Vector3, target: Figure) {
    const arrow = makeArrow();
    arrow.position.copy(from);
    this.props.add(arrow);
    const to = target.group.position.clone().add(new THREE.Vector3(0, 2, 0));
    const mid = from.clone().lerp(to, 0.5);
    mid.y += from.distanceTo(to) * 0.25;
    const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
    await this.tweens.run(0.9, (k) => {
      const p = curve.getPoint(k);
      const t = curve.getTangent(k);
      arrow.position.copy(p);
      arrow.lookAt(p.clone().add(t));
    }, { ease: linear });
    this.props.remove(arrow);
    if (target.alive) void this.fall(target);
  }

  get livingWarriors() {
    return this.warriors.filter((w) => w.alive);
  }

  /** Une troupe de guerriers surgit au sud et marche sur le château (vers les douves et le pont). */
  async attack(count = 8) {
    const g = DIM.gate.center[1] + DIM.gate.size / 2;
    const squad: Figure[] = [];
    for (let i = 0; i < count; i++) {
      const x = -28 + (56 * (i + 0.5)) / count + (this.random() - 0.5) * 4;
      squad.push(this.spawn('warrior', x, 0.05, 56 + this.random() * 6));
    }
    await Promise.all(
      squad.map((w, i) => {
        const nearBridge = Math.abs(w.group.position.x) < 6;
        const tx = nearBridge ? (i % 2 ? 2.5 : -2.5) : w.group.position.x;
        const tz = nearBridge ? (this.gateOpen ? g + 1.5 : DIM.moat.outerHalfZ + 1.5) : DIM.moat.outerHalfZ + 1.5 + this.random() * 2;
        return this.walk(w, tx, tz, 6 + this.random() * 2).then(async () => {
          for (let n = 0; n < 3 && w.alive && this.alarm !== 'off'; n++) {
            await this.swing(w);
            await this.tweens.wait(0.3 + this.random() * 0.5);
          }
        });
      }),
    );
  }

  /** Chevaliers sur le chemin de ronde sud et archers sur les tours sud. */
  async defend(knights = 5, archers = 2) {
    const wallZ = DIM.wall.halfZ - DIM.wall.thickness / 2 - 0.4;
    const wallY = DIM.wall.top;
    for (let i = 0; i < knights; i++) {
      const x = -26 + (52 * (i + 0.5)) / knights;
      const k = this.spawn('knight', x, wallY, wallZ);
      k.group.rotation.y = 0; // face au sud
      void this.swing(k);
    }
    const towers = DIM.tower.corners.filter((c) => c.pos[1] > 0);
    for (let i = 0; i < archers; i++) {
      const c = towers[i % towers.length];
      const a = this.spawn('archer', c.pos[0], DIM.tower.crownTop, c.pos[1] + 1);
      a.group.rotation.y = 0;
    }
    await this.tweens.wait(0.5);
  }

  /** Les archers tirent `volleys` salves sur les guerriers encore debout. */
  async volley(volleys = 3) {
    const archers = this.defenders.filter((d) => d.kind === 'archer' && d.alive);
    for (let v = 0; v < volleys; v++) {
      const targets = this.livingWarriors;
      if (!targets.length || !archers.length) return;
      await Promise.all(
        archers.map((a, i) => {
          const t = targets[(v * archers.length + i) % targets.length];
          const from = a.group.position.clone().add(new THREE.Vector3(0, 3, 0));
          void this.swing(a);
          return this.shoot(from, t);
        }),
      );
      await this.tweens.wait(0.8);
    }
  }

  /** Sortie : des chevaliers franchissent le pont et affrontent les guerriers restants au corps à corps. */
  async sortie(count = 3) {
    const g = DIM.gate.center[1];
    if (!this.gateOpen) await this.openGate();
    const team: Figure[] = [];
    for (let i = 0; i < count; i++) team.push(this.spawn('knight', (i - 1) * 2.2, 0.05, g - 4));
    await Promise.all(team.map((k, i) => this.walk(k, (i - 1) * 2.2, DIM.moat.outerHalfZ + 4, 8)));
    for (const k of team) {
      const target = this.livingWarriors.sort((a, b) => a.group.position.distanceTo(k.group.position) - b.group.position.distanceTo(k.group.position))[0];
      if (!target) break;
      await this.walk(k, target.group.position.x - Math.sign(target.group.position.x || 1) * 1.8, target.group.position.z, 9);
      this.face(k, target.group.position.x, target.group.position.z);
      await this.swing(k);
      void this.fall(target);
      await this.tweens.wait(0.3);
    }
    await Promise.all(team.map((k, i) => this.walk(k, (i - 1) * 2.2, g - 4, 8)));
    for (const k of team) await this.tweens.run(0.3, (kk) => void k.group.scale.setScalar(Math.max(0.001, 1.3 * (1 - kk))));
    team.forEach((k) => {
      this.props.remove(k.group);
      this.defenders = this.defenders.filter((d) => d !== k);
    });
  }

  /** Les guerriers survivants fuient vers le sud et disparaissent. */
  async retreat() {
    this.tweens.cancel('attack');
    const left = this.livingWarriors;
    await Promise.all(left.map((w) => this.walk(w, w.group.position.x + (this.random() - 0.5) * 10, 64, 10)));
    left.forEach((w) => {
      w.alive = false;
      this.props.remove(w.group);
    });
    this.warriors = this.warriors.filter((w) => w.alive);
  }

  /** Les défenseurs sautent de joie puis quittent les remparts. */
  async victory() {
    const d = this.defenders.filter((x) => x.alive);
    for (let j = 0; j < 2; j++) await Promise.all(d.map((f) => this.swing(f)));
    await Promise.all(d.map((f, i) => this.tweens.run(0.6, (k) => void (f.group.position.y += Math.sin(k * Math.PI) * 0.08), { delay: i * 0.1 })));
  }

  /** Retire tous les personnages et flèches. */
  clearBattle() {
    for (const f of [...this.warriors, ...this.defenders]) {
      this.tweens.cancel(`walk_${f.group.name}`);
      this.props.remove(f.group);
    }
    this.warriors = [];
    this.defenders = [];
  }

  /** Bataille complète : assaut, alarme, fermeture, salves, sortie, déroute, victoire. */
  async battle(opts: { keepDefenders?: boolean } = {}) {
    this.clearBattle();
    const assault = this.attack(9);
    await this.tweens.wait(1.2);
    void this.mailArrive();
    await this.setAlarm('Élevée');
    await this.defend(5, 2);
    await this.closeGate();
    await this.setAlarm('Critique');
    await this.volley(3);
    await assault;
    await this.sortie(3);
    await this.retreat();
    await this.setAlarm('off');
    await this.victory();
    if (opts.keepDefenders) return;
    await this.tweens.wait(2);
    for (const f of this.defenders) void this.tweens.run(0.4, (k) => void f.group.scale.setScalar(Math.max(0.001, 1.3 * (1 - k))));
    await this.tweens.wait(0.5);
    this.clearBattle();
  }

  /** Escarmouche courte : quelques guerriers abattus par les archers (utilisée pour un événement bloqué). */
  async skirmish(count = 3) {
    if (!this.defenders.some((d) => d.kind === 'archer' && d.alive)) await this.defend(0, 2);
    const assault = this.attack(count);
    await this.tweens.wait(2.5);
    await this.volley(2);
    await assault;
    await this.retreat();
  }

  // --- bac à sable : tornade de sable ----------------------------------------

  private tornado: THREE.Group | null = null;

  private buildTornado(): THREE.Group {
    const g = new THREE.Group();
    g.name = 'sandbox_tornado';
    const sand = new THREE.MeshStandardMaterial({ color: '#cdb27a', transparent: true, opacity: 0.85, side: THREE.DoubleSide, roughness: 1, depthWrite: false });
    const dark = new THREE.MeshStandardMaterial({ color: '#9c8250', transparent: true, opacity: 0.8, side: THREE.DoubleSide, roughness: 1, depthWrite: false });
    for (let i = 0; i < 11; i++) {
      const rBottom = 1.5 + i * 1.35;
      const ring = new THREE.Mesh(new THREE.CylinderGeometry(rBottom + 1.35, rBottom, 3.4, 16, 1, true), i % 2 ? dark : sand);
      ring.position.y = 1.7 + i * 3.3;
      ring.name = `tornado_ring_${i}`;
      g.add(ring);
    }
    const debris = new THREE.MeshStandardMaterial({ color: '#8d7650', flatShading: true });
    for (let i = 0; i < 40; i++) {
      const d = new THREE.Mesh(new THREE.BoxGeometry(0.7, 0.7, 0.7), debris);
      d.name = `tornado_debris_${i}`;
      d.userData = { h: 1 + this.random() * 34, r: 3 + this.random() * 12, a: this.random() * Math.PI * 2, w: 2 + this.random() * 3 };
      g.add(d);
    }
    return g;
  }

  get sandboxActive() {
    return this.tornado !== null;
  }

  /** Aspire un guerrier : il tourne autour de la tornade en montant, rétrécit et disparaît. */
  private async suck(f: Figure) {
    if (!f.alive || !this.tornado) return;
    f.alive = false;
    this.tweens.cancel(`walk_${f.group.name}`);
    const g = f.group;
    const start = g.position.clone();
    const a0 = Math.atan2(start.z - this.tornado.position.z, start.x - this.tornado.position.x);
    await this.tweens.run(2.2, (k) => {
      const c = this.tornado?.position ?? start;
      const r = (1 - k) * Math.max(2, Math.hypot(start.x - c.x, start.z - c.z)) + 2;
      const a = a0 + k * 9;
      g.position.set(c.x + Math.cos(a) * r, start.y + k * 32, c.z + Math.sin(a) * r);
      g.rotation.set(k * 6, k * 11, k * 4);
      g.scale.setScalar(Math.max(0.001, 1.3 * (1 - k * 0.85)));
    }, { ease: easeIn });
    this.props.remove(g);
    this.warriors = this.warriors.filter((w) => w !== f);
  }

  /**
   * Le bac à sable démarre : une tornade se forme devant le château et aspire les assaillants un à un.
   * Elle tourne tant que `stopSandbox()` n'est pas appelé (fin réelle du traitement côté passerelle).
   */
  async startSandbox() {
    if (this.tornado) return;
    const t = this.buildTornado();
    const home = new THREE.Vector3(0, 0, DIM.moat.outerHalfZ + 8);
    t.position.copy(home);
    t.scale.setScalar(0.001);
    this.props.add(t);
    this.tornado = t;
    this.tweens.loop('tornado', (time, dt) => {
      t.children.forEach((c) => {
        if (c.name.startsWith('tornado_ring_')) {
          const i = Number(c.name.slice(13));
          c.rotation.y += dt * (2.5 + i * 0.35);
          c.position.x = Math.sin(time * 3 + i * 0.7) * 0.35 * i;
          c.position.z = Math.cos(time * 2.4 + i * 0.6) * 0.3 * i;
        } else {
          const u = c.userData as { h: number; r: number; a: number; w: number };
          u.a += dt * u.w;
          c.position.set(Math.cos(u.a) * u.r, u.h + Math.sin(time * 2 + u.a) * 0.8, Math.sin(u.a) * u.r);
          c.rotation.x += dt * 4;
          c.rotation.y += dt * 3;
        }
      });
      // la tornade reste devant le pont et balaie les douves ; elle attire les assaillants vers elle
      t.position.x = Math.sin(time * 0.7) * 9;
      t.position.z = home.z + Math.cos(time * 0.5) * 2;
      for (const w of this.livingWarriors) {
        const p = w.group.position;
        const dx = t.position.x - p.x;
        const dz = t.position.z - p.z;
        const d2 = dx * dx + dz * dz;
        if (d2 < 49) void this.suck(w);
        else {
          this.tweens.cancel(`walk_${w.group.name}`);
          const k = Math.min(1, dt * 1.6);
          p.x += dx * k * 0.5;
          p.z += dz * k * 0.5;
          w.group.rotation.y = Math.atan2(dx, dz);
          w.legs[0].rotation.x = Math.sin(time * 14) * 0.9;
          w.legs[1].rotation.x = -Math.sin(time * 14) * 0.9;
        }
      }
    });
    await this.tweens.run(1.2, (k) => void t.scale.setScalar(Math.max(0.001, k)), { ease: easeOut });
  }

  /** Fin du traitement dans le bac à sable : les derniers assaillants sont aspirés, la tornade se dissipe. Plus aucun ennemi. */
  async stopSandbox() {
    const t = this.tornado;
    if (!t) return;
    await Promise.all(this.livingWarriors.map((w) => this.suck(w)));
    await this.tweens.run(1.4, (k) => {
      t.scale.set(Math.max(0.001, 1 - k), Math.max(0.001, 1 + k * 0.6), Math.max(0.001, 1 - k));
    }, { ease: easeIn });
    this.tweens.stopLoop('tornado');
    this.props.remove(t);
    this.tornado = null;
    for (const w of this.warriors) this.props.remove(w.group);
    this.warriors = [];
  }

  // --- caisse « package » --------------------------------------------------------

  private pkg: { crate: THREE.Mesh; name: string } | null = null;

  /** Une caisse (le package demandé) arrive par la route et s'arrête devant le pont. */
  async packageArrives(name: string) {
    if (this.pkg) this.props.remove(this.pkg.crate);
    const crate = this.crate(`package_${name}`, 3);
    crate.position.set(0, 1.5, 60);
    this.pkg = { crate, name };
    const stop = DIM.gate.center[1] + DIM.gate.size / 2 + DIM.drawbridge.length + 3;
    await this.travel(crate, [[0, 1.5, 60], [0, 1.5, stop]], 7);
  }

  /** Inspection : la caisse pulse en ambre tant que le contrôle des packages analyse. */
  packageInspecting(on: boolean) {
    const crate = this.pkg?.crate;
    if (!crate) return;
    const m = this.ownMaterial(crate);
    if (!on) {
      this.tweens.stopLoop('pkg_inspect');
      m.emissiveIntensity = 0;
      return;
    }
    m.emissive.set(PULSE_COLOR.flagged);
    this.tweens.loop('pkg_inspect', (t) => void (m.emissiveIntensity = 0.6 + 0.6 * Math.sin(t * 6)));
  }

  private setCrateColor(kind: PulseKind, intensity = 1) {
    const crate = this.pkg?.crate;
    if (!crate) return;
    this.tweens.stopLoop('pkg_inspect');
    const m = this.ownMaterial(crate);
    m.emissive.set(PULSE_COLOR[kind]);
    m.emissiveIntensity = intensity;
  }

  /** Package sain : il entre et rejoint les réserves (installé). */
  async packageInstalled() {
    const crate = this.pkg?.crate;
    if (!crate) return;
    this.setCrateColor('allowed');
    if (!this.gateOpen) await this.openGate();
    const [sx, sz] = DIM.stables.center;
    await this.travel(crate, [crate.position.toArray() as [number, number, number], [0, 1.1, DIM.gate.center[1] - 6], [sx, 1.1, sz + 6]], 8);
    await this.tweens.run(0.6, (k) => void crate.scale.setScalar(Math.max(0.001, 1 - k)));
    this.props.remove(crate);
    this.pkg = null;
  }

  private beacon: THREE.Mesh | null = null;

  /** Package suspect : la caisse devient rouge et reste bloquée devant le pont relevé, sous un faisceau rouge ; le trône s'allume. */
  async packageBlocked() {
    const crate = this.pkg?.crate;
    if (!crate) return;
    this.setCrateColor('blocked', 1.4);
    const beam = new THREE.Mesh(
      new THREE.CylinderGeometry(2.4, 2.4, 40, 16, 1, true),
      new THREE.MeshStandardMaterial({ color: '#e0433c', emissive: '#e0433c', emissiveIntensity: 0.8, transparent: true, opacity: 0.28, side: THREE.DoubleSide, depthWrite: false }),
    );
    beam.name = 'package_blocked_beam';
    beam.position.set(crate.position.x, 20, crate.position.z);
    this.props.add(beam);
    this.beacon = beam;
    this.tweens.loop('pkg_beam', (t) => {
      (beam.material as THREE.MeshStandardMaterial).opacity = 0.2 + 0.12 * Math.sin(t * 4);
      crate.rotation.y = Math.sin(t * 2) * 0.15;
    });
    await this.closeGate();
    await this.throneAttention(true);
  }

  private clearBeacon() {
    this.tweens.stopLoop('pkg_beam');
    if (this.beacon) this.props.remove(this.beacon);
    this.beacon = null;
  }

  /** Décision de l'analyste : autorisé, la caisse entre ; refusé, elle est détruite et coule dans les douves. */
  async packageDecided(decision: 'approved' | 'rejected') {
    await this.throneAttention(false);
    this.clearBeacon();
    const crate = this.pkg?.crate;
    if (!crate) return;
    if (decision === 'approved') {
      this.setCrateColor('allowed');
      await this.openGate();
      const [sx, sz] = DIM.stables.center;
      await this.travel(crate, [crate.position.toArray() as [number, number, number], [0, 1.1, DIM.gate.center[1] - 6], [sx, 1.1, sz + 6]], 8);
      await this.tweens.run(0.6, (k) => void crate.scale.setScalar(Math.max(0.001, 1 - k)));
    } else {
      this.setCrateColor('blocked', 2);
      const from = crate.position.clone();
      await this.tweens.run(1.6, (k) => {
        crate.position.set(from.x + k * 6, from.y - k * 3, from.z - k * 2);
        crate.rotation.z = k * 2;
        crate.scale.setScalar(Math.max(0.001, 1 - k * 0.9));
      }, { ease: easeIn });
      await this.openGate();
    }
    this.props.remove(crate);
    this.pkg = null;
  }

  /** Retrait après contre-vérification : la caisse ressort des réserves, rouge, et est jetée dans les douves. */
  async packageRemoved(name: string) {
    const crate = this.crate(`removed_${name}`, 3);
    const m = this.ownMaterial(crate);
    m.emissive.set(PULSE_COLOR.blocked);
    m.emissiveIntensity = 1.4;
    const [sx, sz] = DIM.stables.center;
    crate.position.set(sx, 1.5, sz + 6);
    if (!this.gateOpen) await this.openGate();
    const out = DIM.gate.center[1] + DIM.gate.size / 2 + DIM.drawbridge.length + 3;
    await this.travel(crate, [[sx, 1.5, sz + 6], [0, 1.5, DIM.gate.center[1] - 6], [0, 1.5, out], [8, 1.5, out + 2]], 9);
    const from = crate.position.clone();
    await this.tweens.run(1.4, (k) => {
      crate.position.set(from.x + k * 4, from.y - k * 3.5, from.z - k);
      crate.rotation.z = k * 2.5;
      crate.scale.setScalar(Math.max(0.001, 1 - k * 0.9));
    }, { ease: easeIn });
    this.props.remove(crate);
  }

  /** Tout remettre à zéro avant un nouveau test. */
  reset() {
    this.clearBattle();
    if (this.tornado) {
      this.tweens.stopLoop('tornado');
      this.props.remove(this.tornado);
      this.tornado = null;
    }
    this.clearBeacon();
    if (this.pkg) {
      this.tweens.stopLoop('pkg_inspect');
      this.props.remove(this.pkg.crate);
      this.pkg = null;
    }
    this.tweens.stopLoop('throne');
  }

  /** Scénario de démonstration enchaînant les actions principales. */
  async demo(towerIds: readonly string[]) {
    const [a, b, c] = towerIds;
    await this.mailArrive().then(() => {});
    await this.towerPulse(a, 'allowed');
    await this.towerPulse(b, 'allowed');
    await this.libraryAccess('allowed');
    await this.towerPulse(c ?? a, 'flagged');
    await this.setAlarm('Modérée');
    await this.treasuryAccess('blocked');
    await this.towerPulse(c ?? a, 'blocked');
    await this.setAlarm('Critique');
    await this.closeGate();
    await this.throneAttention(true);
    await this.tweens.wait(1.5);
    await this.throneAttention(false);
    await this.quarantine('demo');
    await this.setAlarm('Faible');
    await this.openGate();
    await this.release('demo');
    await this.setAlarm('off');
  }
}
