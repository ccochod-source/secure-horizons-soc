export type Ease = (t: number) => number;
export const linear: Ease = (t) => t;
export const easeInOut: Ease = (t) => (t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t);
export const easeOut: Ease = (t) => 1 - (1 - t) * (1 - t);
export const easeIn: Ease = (t) => t * t;

interface Tween {
  tag?: string;
  elapsed: number;
  delay: number;
  duration: number;
  ease: Ease;
  update: (k: number) => void;
  resolve: () => void;
}

/** Mini moteur de tweens piloté par `update(dt)` depuis la boucle de rendu. */
export class Tweens {
  private list: Tween[] = [];
  private loops = new Map<string, (t: number, dt: number) => void>();
  private time = 0;

  /** Interpole k de 0 à 1 pendant `duration` secondes ; résout à la fin. */
  run(duration: number, update: (k: number) => void, opts: { ease?: Ease; delay?: number; tag?: string } = {}): Promise<void> {
    return new Promise((resolve) => {
      this.list.push({ tag: opts.tag, elapsed: 0, delay: opts.delay ?? 0, duration, ease: opts.ease ?? easeInOut, update, resolve });
    });
  }

  wait(seconds: number): Promise<void> {
    return this.run(seconds, () => {}, { ease: linear });
  }

  /** Boucle continue identifiée par un nom (feu, drapeau…) ; remplacée si déjà présente. */
  loop(name: string, fn: (t: number, dt: number) => void) {
    this.loops.set(name, fn);
  }

  stopLoop(name: string) {
    this.loops.delete(name);
  }

  /** Abandonne les tweens portant ce tag (ils sont résolus sans aller au bout). */
  cancel(tag: string) {
    this.list = this.list.filter((t) => {
      if (t.tag !== tag) return true;
      t.resolve();
      return false;
    });
  }

  update(dt: number) {
    this.time += dt;
    const done: Tween[] = [];
    for (const t of this.list) {
      if (t.delay > 0) {
        t.delay -= dt;
        if (t.delay > 0) continue;
      }
      t.elapsed += dt;
      const k = Math.min(1, t.elapsed / t.duration);
      t.update(t.ease(k));
      if (k >= 1) done.push(t);
    }
    if (done.length) {
      this.list = this.list.filter((t) => !done.includes(t));
      done.forEach((t) => t.resolve());
    }
    for (const fn of this.loops.values()) fn(this.time, dt);
  }
}
