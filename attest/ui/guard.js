/* AsyncResourceGuard — §30.
 *
 * D15: an investigation trail computed for one settlement rendered under
 * another's case file, because the selection moved while the request was in
 * flight. That is not a cosmetic race. In a product whose whole claim is that
 * every statement is checkable, attaching real evidence to the wrong subject is
 * a fabricated audit record, and worse than showing nothing.
 *
 * The guard already existed inside one function and nowhere else. A convention
 * that lives in a single place is not a convention, so it is an abstraction now
 * and every async path uses it.
 *
 * Two mechanisms, because they fail differently:
 *
 *   SUBJECT  a result is discarded unless the caller still wants that entity.
 *            Protects against attaching data to the wrong thing.
 *
 *   EPOCH    a result is discarded if a newer request for the SAME entity has
 *            started. Protects against an older response overwriting a newer
 *            one — the same bug wearing different clothes.
 */
'use strict';

class AsyncResourceGuard {
  constructor(name) {
    this.name = name;
    this.epochs = new Map();
    this.discarded = 0;
  }

  /* Run `fetcher` for `entityId` and apply the result only if it is still the
     one being asked for. `stillWanted()` is evaluated AFTER the await, because
     what the user wants can change during it — which is the entire point. */
  async run(entityId, fetcher, stillWanted) {
    const epoch = (this.epochs.get(entityId) || 0) + 1;
    this.epochs.set(entityId, epoch);

    let value;
    try {
      value = await fetcher();
    } catch (err) {
      if (this.epochs.get(entityId) === epoch) throw err;
      this.discarded++;
      return { ok: false, stale: true };
    }

    if (this.epochs.get(entityId) !== epoch) {
      this.discarded++;
      return { ok: false, stale: true, reason: 'superseded' };
    }
    if (stillWanted && !stillWanted(entityId, value)) {
      this.discarded++;
      return { ok: false, stale: true, reason: 'subject-changed' };
    }
    return { ok: true, value };
  }

  /* Abandon everything in flight — a wholesale context change such as a new
     reconciliation run, where nothing outstanding refers to anything real. */
  invalidateAll() {
    for (const k of this.epochs.keys()) this.epochs.set(k, (this.epochs.get(k) || 0) + 1);
  }
}

window.AsyncResourceGuard = AsyncResourceGuard;
