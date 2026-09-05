/* EVIDENCE — "Why should I believe this?"
 *
 * Two compositions were built and compared, per §21.
 *
 *   A · MAP     leads with the SHAPE of the belief: how the candidate universe
 *               narrowed, and what the surviving explanations agree on.
 *   B · LEDGER  leads with the RECORDS: grouped counts, then the typed
 *               relationships as a table.
 *
 * A was kept. B failed on its own output: the relationship table rendered
 * fourteen consecutive rows of `000819 · amount match · setl_000089 · verified`
 * with only the order id changing. That answers "what records exist" and not
 * "why should I believe this", and it pushed the two things that DO answer it —
 * the search-space boundary and the explanation set — below the fold. It is the
 * failure §5 names: node → node → node with the relationship unexplained.
 *
 * Neither drew a node graph. 73 candidate orders is unreadable as nodes and
 * edges, and §22 is explicit that a representation earns its place by making a
 * relationship easier to understand, not by being a graph.
 */
'use strict';

(() => {
  const { Section, Row, MetricRow, Disclosure, EmptyState, Conclusion,
          rupees, plural, esc } = window.C;

  /* ------------------------------------------------------- shared pieces */

  /* §16. What was CONSIDERED, not only what was selected. Each reduction says
     whether it is a deterministic fact or a convention — the distinction the
     32/92 failure was about, where a proof was perfect inside a space that had
     already excluded the truth. */
  function Universe(space, survivors) {
    if (!space) return '';

    /* §30.3 — the reduction chain as an object rather than a bar list.
     *
     * This is the product's signature moment and it was three rows of small
     * type: the reader had to assemble "2,368 orders became 164 candidates
     * became 4 explanations" out of a table. The sequence IS the argument, so
     * the sequence is now the composition — three figures at the size of the
     * claim they make, and between them the cuts that got from one to the next.
     *
     * The rule under each figure is linear in its own population, so the
     * physical collapse from 2,368 to 4 is visible before a digit is read.
     * The floor keeps the survivors from rendering as nothing, since four
     * surviving explanations is the whole reason this case is open.
     *
     * Each cut is focusable and states its justification on hover or focus.
     * That is the one piece of progressive disclosure here: the default view
     * carries the fact and the KIND — deterministic or convention — because
     * that distinction is what the 32/92 failure was about, and a reader who
     * never hovers must still see it. */
    const top = Math.max(space.universe, 1);
    const FLOOR = 0.35;
    const rule = (n) => `<span class=e-uni-t aria-hidden=true><i style="width:${
      Math.max(n / top * 100, n > 0 ? FLOOR : 0).toFixed(3)}%"></i></span>`;

    const node = (n, label, cls = '') => `<div class="e-uni-r ${cls}">
      <span class=e-uni-n>${Number(n).toLocaleString()}</span>
      <span class=e-uni-l>${esc(label)}</span>
      ${rule(n)}</div>`;

    const cuts = space.reductions.map((x, i) => `<button
        class="e-uni-c ${x.deterministic ? 'det' : 'conv'}"
        style="animation-delay:${120 + i * 90}ms"
        aria-describedby="e-just-${i}">
        <span class=e-uni-m>−${Number(x.removed).toLocaleString()}</span>
        <span class=e-uni-w>${esc(x.name)}</span>
        <span class=e-uni-k>${x.deterministic ? 'deterministic' : 'convention'}</span>
        <span class=e-uni-j id="e-just-${i}">${esc(x.justification)}</span>
      </button>`).join('');

    return `<div class=e-uni>
      ${node(space.universe, 'orders in the book')}
      <div class=e-uni-e>${cuts}</div>
      ${node(space.candidates, 'could belong to this credit', 'mid')}
      ${survivors ? `<div class=e-uni-e>
          <div class="e-uni-c arith">
            <span class=e-uni-m>∑</span>
            <span class=e-uni-w>subsets whose net equals the credit</span>
            <span class=e-uni-k>deterministic</span>
            <span class=e-uni-j>the last cut is arithmetic, not a rule: what
              survives is every subset of the ${Number(space.candidates
                ).toLocaleString()} candidates whose net equals the credit
              within tolerance</span>
          </div>
        </div>
        ${node(survivors, survivors === 1
          ? 'explanation survives'
          : 'surviving explanations, and arithmetic cannot choose',
          'e-uni-end')}` : ''}
    </div>`;
  }

  /* §8. Ambiguity, shown rather than stated. The block that every explanation
     contains is settled whichever one is right; the argument is only about the
     slivers beside it. */
  function ExplanationSet(d) {
    const xs = d.explanations || [];
    if (xs.length < 2) return '';
    const widest = Math.max(...xs.map(x => x.orders), 1);
    return `<div class=e-set>
      <div class=e-set-hd>
        <span class=e-set-a>agreed by all ${xs.length}</span>
        <span class=e-set-b>in question</span></div>
      ${xs.map(x => {
        const uPaise = x.unique.reduce((n, o) => n + o.paise, 0);
        return `<button class=e-set-r data-context="explanation:${esc(x.letter)}">
          <span class=e-set-l>${esc(x.letter)}</span>
          <span class=e-set-bar aria-hidden=true>
            <i class=s style="width:${x.shared / widest * 100}%"></i
            ><i class=u style="width:${(x.orders - x.shared) / widest * 100}%"></i>
          </span>
          <span class=e-set-n>${x.shared} + <b>${x.orders - x.shared}</b></span>
          <span class=e-set-v>${esc(rupees(uPaise))}</span>
        </button>`;
      }).join('')}
      <div class=e-set-ft>
        <span><b>${esc(rupees(d.shared.paise))}</b> is settled whichever
          explanation is right</span>
        <span><b class=warn>${esc(rupees(d.shared.disputed_paise))}</b>
          turns on which one is, across ${d.shared.differing} orders</span>
      </div>
    </div>`;
  }

  /* §6, §18. A separate section with a separate visual language, because a
     flag on a shared list is how a hypothesis ends up rendered as a fact. */
  function AISection(d) {
    const t = d.ai.trail || [];
    if (!t.length && !(d.ai.edges || []).length) return '';
    const verdict = t.filter(x => x.stage === 'refute').slice(-1)[0];
    return Section({
      title: 'What the model proposed',
      aside: `<span class="e-ai-tag">not evidence</span>`,
      body: `<div class=e-ai>
        ${t.map(x => `<div class="e-ai-r ${esc(x.stage)}">
          <span class=e-ai-w>${x.stage === 'proposed' ? '◇ model' : '✓ solver'}</span>
          <span class=e-ai-d>${esc(x.detail)}</span></div>`).join('')}
        ${verdict ? `<div class=e-ai-v>Result — <b>non-discriminative</b>.
          The anchor appears in every surviving explanation, so it cannot choose
          between them.</div>` : ''}
      </div>` + Disclosure({
        summary: 'Why a model relationship can never be load-bearing',
        body: `<p>${esc(d.ai.note)}</p>`,
      }),
    });
  }

  function ChainRows(d) {
    const byKind = {};
    (d.chain || []).forEach(e => {
      (byKind[e.kind] = byKind[e.kind] || []).push(e);
    });
    return Object.entries(byKind).map(([kind, es]) => `<div class=e-rel>
      <div class=e-rel-h><b>${esc(kind.replace(/_/g, ' '))}</b>
        <span class=e-rel-n>${plural(es.length, 'relationship')}</span>
        <span class=e-rel-v>✓ verified</span></div>
      <div class=e-rel-w>${esc(es[0].why)}</div>
    </div>`).join('');
  }

  /* ------------------------------------------------ composition A · MAP */
  function compositionA(d) {
    const n = (d.explanations || []).length;
    const sh = d.shared || {};
    // The room's answer, first and largest. Evidence's question is "why should
    // I believe this", and its answer is whether a unique proof exists — which
    // was previously reachable only by reading three sections down.
    const answer = n > 1
      ? Conclusion({
          fact: 'No unique proof', tone: 'stop',
          figure: rupees(sh.disputed_paise || 0), figureLabel: 'in dispute',
          because: `${n} disjoint order sets satisfy the amount exactly, so `
            + `arithmetic cannot choose between them. ${sh.n || 0} orders are in `
            + `every one of them — ${rupees(sh.paise || 0)} is settled whichever `
            + `is right, and the argument is ${sh.differing || 0} orders.`,
        })
      : Conclusion({
          fact: 'One explanation survives', tone: 'go',
          because: 'A single candidate set satisfies every constraint, and the '
            + 'independent kernel re-derived it from source records.',
        });
    return answer + Section({
      title: 'What was considered',
      aside: `<span class=c-muted>${Number(d.space ? d.space.universe : 0)
        .toLocaleString()} → ${d.space ? d.space.candidates : 0}${
        (d.explanations || []).length ? ` → ${d.explanations.length}` : ''}</span>`,
      /* §11. The claim the whole chain rests on used to sit behind the
         disclosure below. A proof is only as good as the space it was proved
         in — that is the argument this composition exists to make, so it is
         stated under the chain rather than folded away beneath it. */
      body: Universe(d.space, (d.explanations || []).length)
        + (d.space ? `<p class=e-uni-claim>${esc(d.space.claim)}</p>` + Disclosure({
        summary: 'Why the boundary matters more than the selection',
        body: `<p>A proof can be arithmetically perfect inside a space that
          already excluded the truth. Two of the reductions above are
          conventions rather than facts, so uniqueness established inside them
          is local.</p>`,
      }) : ''),
    })
    + (d.explanations && d.explanations.length > 1 ? Section({
        title: 'What the explanations agree on',
        aside: `<span class=c-muted>${d.shared.n} of every set</span>`,
        body: ExplanationSet(d),
      }) : '')
    + Section({
        title: 'Verified relationships',
        aside: `<span class=c-muted>${plural((d.chain || []).length, 'edge')}</span>`,
        body: ChainRows(d) || EmptyState('No relationship was established.'),
      })
    + AISection(d);
  }

  /* ------------------------------------------------------------ portfolio */
  async function portfolio(S) {
    const d = await window.shellApi(`/api/evidence?run=${S.run}&type=portfolio`);
    const heur = (d.integrity || {}).heuristic || 0;
    const val = (d.integrity || {}).validated || 0;
    const tot = heur + val;
    // Evidence's portfolio answer is not how many orders there are. It is how
    // much of the book's proof rests on a convention rather than a fact.
    return Conclusion({
      fact: `${heur} of ${tot} search spaces rest on a convention`,
      tone: 'hold',
      figure: rupees(d.heuristic_paise), figureLabel: 'proved inside one',
      because: 'The settlement calendar and the already-claimed reduction are '
        + 'conventions, not facts. A proof can be arithmetically perfect inside '
        + 'a space that already excluded the truth, which is what makes the '
        + 'boundary matter more than the selection.',
    }) + Section({
      title: 'The evidence in this run',
      body: MetricRow((d.counts || []).map(c => ({
        label: c.kind + (c.n === 1 ? '' : 's'),
        value: Number(c.n).toLocaleString(), note: c.note,
      }))),
    })
    + Section({
        title: 'How much of the book rests on a convention',
        aside: `<span class=c-muted>${esc(rupees(d.heuristic_paise, { whole: true }))}</span>`,
        body: MetricRow([
          { label: 'search space validated', value: String(val), tone: 'proven',
            note: 'every reduction was a deterministic fact' },
          { label: 'search space heuristic', value: String(heur),
            tone: 'ambiguous',
            note: 'at least one reduction is a convention' },
        ]) + `<div class=e-red>${(d.reductions || []).map(x =>
          `<div class="e-uni-c ${x.deterministic ? 'det' : 'conv'}">
            <span class=e-uni-m>−${Number(x.removed).toLocaleString()}</span>
            <span class=e-uni-w>${esc(x.name)}</span>
            <span class=e-uni-k>${x.deterministic ? 'deterministic' : 'convention'}</span>
            <span class=e-uni-j>${esc(x.justification)}</span></div>`).join('')}</div>`
          + Disclosure({
              summary: 'Why this is the number that matters at portfolio scale',
              body: `<p>A settlement whose candidate pool was narrowed by a
                convention can be proven inside that pool and still be wrong,
                because the truth may have been removed before the solver ran.
                That is not hypothetical: it cost 32 of 92 resolutions once.</p>`,
            }),
      })
    + Section({
        title: 'AI relationships in force',
        body: `<div class=e-ai-none>None. ${esc(d.ai.note)}</div>`,
      });
  }

  /* -------------------------------------------------------------- context */
  async function orderContext(oid, sid, S) {
    const d = await window.shellApi(
      `/api/settlement?run=${S.run}&id=${encodeURIComponent(sid)}`);
    let found = null, inWhich = [];
    (d.proofs || []).forEach((p, i) => {
      const o = p.orders.find(x => x.id === oid);
      if (o) { found = o; inWhich.push(String.fromCharCode(65 + i)); }
    });
    const shell = { kind: 'Order', title: oid.replace('ord_', ''),
                    promote: null };
    if (!found) return { ...shell, body: EmptyState('Not in any explanation.') };
    return { ...shell, body:
      Section({ body: MetricRow([
        { label: 'gross', value: rupees(found.gross) },
        { label: 'net', value: rupees(found.net), tone: 'proven' },
        { label: 'method', value: found.method },
      ]) })
      + Section({
          title: 'Provenance',
          body: `<dl class=e-prov>
            <div><dt>captured</dt><dd>${esc(found.captured_on)}</dd></div>
            <div><dt>source</dt><dd>synthetic portfolio, seed ${S.record
              && S.record.meta ? esc((S.record.meta.find(m => m.k === 'seed') || {}).v || '') : ''}</dd></div>
            <div><dt>order id</dt><dd class=c-mono>${esc(oid)}</dd></div>
            <div><dt>fee</dt><dd>${esc(rupees(found.fee))} by rule</dd></div>
          </dl>`,
        })
      + Section({
          title: 'Where it appears',
          body: inWhich.length === (d.proofs || []).length
            ? `<p class=c-lead style="font-size:var(--t-label)">In every
               surviving explanation (${inWhich.join(', ')}), so it is settled
               whichever one is right.</p>`
            : `<p class=c-lead style="font-size:var(--t-label)">Only in
               explanation ${inWhich.join(', ')} — one of the orders the
               ambiguity is actually about.</p>`,
        }) };
  }

  async function explanationContext(letter, sid, S) {
    const d = await window.shellApi(
      `/api/evidence?run=${S.run}&type=settlement&id=${encodeURIComponent(sid)}`);
    const x = (d.explanations || []).find(e => e.letter === letter);
    const shell = { kind: 'Explanation', title: letter, status: d.verdict };
    if (!x) return { ...shell, body: EmptyState('No such explanation') };
    return { ...shell, body:
      Section({ body: MetricRow([
        { label: 'explains', value: rupees(x.net_paise), tone: 'proven',
          note: `residual ${x.residual_paise}p within ±${x.tolerance_paise}p` },
        { label: 'orders', value: String(x.orders),
          note: `${x.shared} shared · ${x.unique.length} only here` },
      ]) })
      + Section({
          title: 'The orders only this explanation uses',
          aside: `<span class=c-muted>${esc(rupees(
            x.unique.reduce((n, o) => n + o.paise, 0)))}</span>`,
          body: x.unique.length ? x.unique.map(o => Row({
            id: o.id.replace('ord_', ''), amount: o.paise,
            detail: `<span class=c-muted>${esc(o.method)} · ${esc(o.captured_on)}</span>`,
            context: { type: 'order', id: o.id },
          })).join('') : EmptyState('None — it uses only shared orders.'),
        }) };
  }

  window.defineLens('evidence', {
    label: 'Evidence',
    question: 'Why do we believe this?',
    layout: () => 'focus',
    holds: (ctx, subject) => subject.type === 'settlement'
      && (ctx.type === 'order' || ctx.type === 'explanation'),
    async render(subject, S) {
      if (subject.type === 'portfolio') return portfolio(S);
      if (subject.type !== 'settlement') {
        return EmptyState('Evidence has nothing to say about this subject.');
      }
      const d = await window.shellApi(
        `/api/evidence?run=${S.run}&type=settlement&id=${encodeURIComponent(subject.id)}`);
      if (d.error) return EmptyState(d.error);
      return compositionA(d);
    },
    context(ctx, subject, S) {
      return ctx.type === 'order'
        ? orderContext(ctx.id, subject.id, S)
        : explanationContext(ctx.id, subject.id, S);
    },
  });
})();
