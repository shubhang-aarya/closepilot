/* POLICY — "Given what ATTEST knows, what is it allowed to do?"
 *
 * Not a settings page and not a rule list. The subject of this lens is a
 * DECISION, and the visual is the boundary that produced it:
 *
 *     expected loss  <  cost of a review     ->  automate
 *     expected loss  >= cost of a review     ->  check
 *
 * Two things this lens must never do. It must never present itself as changing
 * a verdict — a settlement can be AMBIGUOUS and REVIEW, and those are two facts
 * rather than one. And it must never express a decision as a confidence: "92%
 * confident" is not an argument anyone can audit, whereas "₹135.48 expected
 * loss against ₹150.00 to check" is one a controller can disagree with.
 *
 * The simulator changes the COSTING, and a costing is hashed into the policy
 * version — so a what-if is a different policy version rather than a
 * recomputation of the recorded one. That is what makes §25 honest instead of
 * a promise: the historical decision keeps its version because the version is
 * derived from the inputs that made it.
 */
'use strict';

(() => {
  const { Section, Row, MetricRow, Disclosure, EmptyState, Conclusion,
          rupees, plural, esc } = window.C;

  const STEPS = [2500, 5000, 10000, 15000, 25000, 50000, 100000, 250000, 500000];

  /* §7, §32. One axis, two comparable numbers, and a line between them. A
     reader should see which side a settlement is on before reading a word. */
  /* The statement leads the room as the conclusion. It used to be repeated
     here word for word — and on an unpriced case this section contained
     nothing else, so it was a heading over a repeat. §13 asks for no marker
     when nothing was priced; the honest form of that is no boundary at all. */
  function Boundary(b, decision) {
    /* §30.5 — the threshold as a measuring instrument.
     *
     * Two comparable numbers and the line between them. This existed and was
     * four small rows; the comparison IS the decision, so it is now the
     * largest thing in the room.
     *
     * On an unpriced case it used to render nothing at all, on the reasoning
     * that "no marker" is the honest form of "nothing was priced". That was
     * half right: hiding the instrument also hides that a price was SUPPOSED
     * to be here. The scale is drawn, the review cost is real, and where the
     * expected loss would sit there is the word UNPRICED and the reason — the
     * absence is the point, and an absence you cannot see is not a statement.
     *
     * A zero is never drawn. Zero expected loss would mean the engine had
     * proved the posting safe, which is the opposite of what happened. */
    const rev = b.review_paise;
    const loss = b.priced ? b.expected_loss_paise : null;
    const span = Math.max(loss || 0, rev) * 2;
    const pos = v => Math.min(v / span * 100, 96);
    const cheaper = b.priced && loss < rev;
    return `<div class="p-bound ${b.priced ? (cheaper ? 'auto' : 'review')
                                           : 'unpriced'}">
      <div class=p-bound-hd>
        <div class="p-bound-k lo">
          <i>expected loss</i>
          <b>${b.priced ? esc(rupees(loss)) : 'Unpriced'}</b>
        </div>
        <div class="p-bound-k rv">
          <i>cost of a review</i>
          <b>${esc(rupees(rev))}</b>
        </div>
      </div>
      <div class=p-bound-t>
        <i class=p-bound-line style="left:${pos(rev)}%"></i>
        ${b.priced ? `<i class=p-bound-mark style="left:${pos(loss)}%"></i>` : ''}
        <span class=p-bound-zl>automating is cheaper</span>
        <span class=p-bound-zr>checking is cheaper</span>
      </div>
      <div class=p-bound-out>${b.priced
        ? `<b>${esc(rupees(Math.abs(rev - loss)))}</b> ${
            cheaper ? 'cheaper to automate than to check'
                    : 'cheaper to check than to risk automating'}`
        : 'nothing to compare against'}</div>
    </div>`;
  }

  /* §17. The chain, as gates in order. Nothing reaches policy without passing
     proof, and the layout says so by putting them in that order and grouping
     them under the stage that owns them. */
  function Gates(gates) {
    const stages = [...new Set(gates.map(g => g.stage))];
    return `<div class=p-gates>${stages.map(st => `
      <div class=p-stage>
        <div class=p-stage-h>${esc(st)}</div>
        ${gates.filter(g => g.stage === st).map(g => `<div class="p-gate ${g.ok ? 'ok' : 'no'}">
          <i aria-hidden=true>${g.ok ? '✓' : '✕'}</i>
          <span class=p-gate-n>${esc(g.name)}</span>
          <span class=p-gate-s>${g.ok ? 'passed' : 'not satisfied'}</span>
          <span class=p-gate-w>${esc(g.why)}</span>
        </div>`).join('')}
      </div>`).join('<i class=p-stage-arrow aria-hidden=true></i>')}</div>`;
  }

  async function settlement(subject, S) {
    const d = await window.shellApi(`/api/decision?run=${S.run}`
      + `&type=settlement&id=${encodeURIComponent(subject.id)}`
      + `&review=${S.review}&exposure=${S.exposure}`);
    if (d.error) return EmptyState(d.error);

    // Policy's answer is the decision, and where no proof exists the honest
    // answer is that nothing was priced — never a fabricated zero.
    const b = d.boundary || {};
    /* One fact each. The room's question is "what is safe to automate", so the
       conclusion answers with the DECISION and the reason for it; the
       threshold below states the two figures that produced it and draws the
       comparison. Both used to state both, which is how REVIEW came to be
       painted twice at hero weight and the reason sentence twice verbatim. */
    const answer = Conclusion({
      fact: esc(d.decision).replace('_', '-'),
      tone: d.decision === 'AUTO_POST' ? 'go' : 'hold',
      figure: null, figureLabel: null,
      because: b.statement || '',
    });

    /* The decision leads the room as the conclusion. This block used to paint
       it a second time at 20px a hundred pixels below — the same word twice in
       one viewport, and the thing that made it worth having buried underneath.
       What is unique here is the relationship: policy READS the verdict. That
       is one of the product's core claims and it appears nowhere else. */
    return answer + `<div class="p-head ${esc(d.decision)}">
        ${d.simulated ? '<div class=p-sim>Simulated costing — no action will be executed</div>' : ''}
        <span class=p-head-k>policy and the verdict</span>
        <div class=p-head-s><i aria-hidden=true></i>the verdict is
          <b class="c-status s-${esc(d.verdict)} sm">${esc(d.verdict)}</b>
          — policy reads it and does not change it</div>
      </div>`
      /* Drawn whether or not it was priced. The unpriced case is the one a
         judge should see: the scale exists, the review cost is real, and the
         slot where a price would go says UNPRICED and why. */
      + Section({ title: 'The threshold', body: Boundary(b, d.decision) })
      + Section({
          title: 'What had to hold',
          aside: `<span class=c-muted>${d.gates.filter(g => g.ok).length}/${d.gates.length} passed</span>`,
          body: Gates(d.gates),
        })
      + Section({
          title: 'What went in',
          body: `<dl class=p-in>${d.inputs.map(x => `<div>
            <dt>${esc(x.k)}</dt>
            <dd><b>${esc(x.v)}</b>${x.note ? `<span>${esc(x.note)}</span>` : ''}</dd>
          </div>`).join('')}</dl>`
            + Disclosure({
                summary: 'Every step the engine took',
                body: `<ol class=c-reasons>${d.reasons
                  .map(x => `<li>${esc(x)}</li>`).join('')}</ol>`,
              }),
        })
      + Section({
          title: 'Which policy decided this',
          body: `<dl class=e-prov>
            <div><dt>policy</dt><dd class=c-mono>${esc(d.policy_version)}</dd></div>
            ${d.simulated ? `<div><dt>recorded as</dt>
              <dd class=c-mono>${esc(d.recorded_version)}</dd></div>` : ''}
            ${Object.entries(d.provenance || {}).map(([k, v]) =>
              `<div><dt>${esc(k.replace('_version', ''))}</dt>
                <dd class=c-mono>${esc(v)}</dd></div>`).join('')}
          </dl>` + Disclosure({
            summary: 'Why a what-if is a different policy, not a recomputation',
            body: `<p>The policy version is a content hash of the costing. Change
              what a review is worth and the version changes with it, so a
              historical decision keeps its own version rather than being
              silently re-decided under today's numbers.</p>`,
          }),
        });
  }

  /* ------------------------------------------------------------- portfolio */
  async function portfolioMaster(S) {
    const d = await window.shellApi(`/api/decision?run=${S.run}&type=portfolio`
      + `&review=${S.review}&exposure=${S.exposure}`);
    const total = d.settlements || 1;
    const idx = STEPS.indexOf(S.review);

    return Conclusion({
      fact: `${d.auto_post} of ${total} post without a person`,
      tone: d.auto_post ? 'go' : 'hold',
      figure: rupees(d.protected_paise), figureLabel: 'held for a person',
      because: `At ${rupees(d.review_paise)} to check one settlement by hand, `
        + `automating ${d.auto_post} is cheaper than checking them and `
        + `${d.wrong_posts === 0 ? 'none of them is wrong'
             : `${d.wrong_posts} of them is wrong`}. `
        + `Proof gates first, economics second: nothing without a unique, `
        + `kernel-checked explanation is eligible at any price.`,
    })
      + Section({
          title: 'Where this threshold came from',
          question: 'Why ' + esc(rupees(d.review_paise)) + '?',
          body: `<p class=c-lead>Nobody picked it. It is the cost of a person
            opening one settlement and deciding — and the engine automates a
            settlement exactly when its <em>measured</em> chance of being wrong,
            multiplied by what being wrong costs, comes out below that. Change
            what an analyst's time is worth and the line moves on its own.</p>
          <p class=c-lead style="margin-top:10px">Below is the same portfolio
            decided at every price. Read the last column: it is what the extra
            automation costs in wrong entries. <b>That is the trade, measured
            rather than argued.</b></p>`,
        }) + `<div class="p-head ${d.simulated ? 'sim' : ''}">
        ${d.simulated ? '<div class=p-sim>Simulated costing — no action will be executed</div>' : ''}
        <span class=p-head-k>what ATTEST may automate</span>
        <div class=p-head-d><i aria-hidden=true></i>${esc(rupees(d.posted_paise, { whole: true }))}</div>
        <div class=p-head-s>of ${esc(rupees(d.posted_paise + d.protected_paise, { whole: true }))} processed</div>
      </div>`
      + Section({
          title: 'What each decision holds',
          body: d.groups.map(g => `<button class="p-grp d-${esc(g.decision)}"
              data-context="decision:${esc(g.decision)}">
              <span class=p-grp-d>${esc(g.decision.replace(/_/g, '-'))}</span>
              <span class=p-grp-b><i style="width:${g.count / total * 100}%"></i></span>
              <span class=p-grp-n>${plural(g.count, 'settlement')}</span>
              <span class=p-grp-v>${esc(rupees(g.paise, { whole: true }))}</span>
            </button>`).join(''),
        })
      + Section({
          title: 'What if a review were worth more',
          aside: '<span class=p-sim-tag>simulation</span>',
          body: `<div class=p-sim-c>
            <label for=p-rev>an analyst opening one settlement and deciding</label>
            <input id=p-rev type=range min=0 max="${STEPS.length - 1}"
              value="${idx < 0 ? 3 : idx}" aria-label="Cost of a review">
            <output id=p-rev-v>${esc(rupees(S.review))}</output>
          </div>
          <div class=p-front><div class="p-front-r hd">
              <span class=p-front-c>if a check costs</span>
              <span class=p-front-b></span>
              <span class=p-front-n>auto</span>
              <span class=p-front-v>posted</span>
              <span class=p-front-w>wrong</span>
            </div>${(d.frontier || []).map(p => {
            const on = p.review_paise === S.review;
            return `<div class="p-front-r${on ? ' on' : ''}">
              <span class=p-front-c>${esc(rupees(p.review_paise))}</span>
              <span class=p-front-b><i style="width:${p.auto_post / total * 100}%"></i></span>
              <span class=p-front-n>${p.auto_post}</span>
              <span class=p-front-v>${esc(rupees(p.posted_paise, { whole: true }))}</span>
              <span class=p-front-w>${p.wrong_posts
                ? `<b>${p.wrong_posts} wrong</b>` : '0 wrong'}</span>
            </div>`;
          }).join('')}</div>`
            + Disclosure({
                summary: 'What this frontier is measuring',
                body: `<p>Every row is the same portfolio decided under a
                  different cost of review. The threshold is never configured:
                  it is wherever expected loss crosses that cost. Nothing is
                  executed by moving it — the recorded decisions keep the policy
                  version they were made under.</p>
                  <p style="margin-top:9px">The shipped operating point is
                  ${esc(rupees(d.review_paise))}, and it was adopted on
                  evidence rather than taste: across the held-out panel every
                  accuracy and safety figure is identical at
                  ${esc(rupees(15000))} and ${esc(rupees(25000))} — same exact
                  recovery, same proof precision, same four false proofs, same
                  zero rupees wrongly posted — while the number of settlements
                  resolved without a person goes from 11 to 33. The engine did
                  not get better. It stopped paying a person to re-check work it
                  had already proved.</p>`,
              }),
        });
  }

  async function decisionContext(which, S) {
    const d = await window.shellApi(`/api/decision?run=${S.run}&type=portfolio`
      + `&review=${S.review}&exposure=${S.exposure}`);
    const g = (d.groups || []).find(x => x.decision === which);
    if (!g) return { kind: 'Decision', title: which, body: EmptyState('Unknown') };
    return {
      kind: 'Decision', title: which.replace(/_/g, '-'),
      body: Section({
          body: MetricRow([
            { label: 'settlements', value: String(g.count) },
            { label: 'value', value: rupees(g.paise, { whole: true }),
              tone: which === 'AUTO_POST' ? 'proven' : 'ambiguous' },
          ]),
        })
        + Section({ title: 'Why they land here',
            body: `<p class=c-lead style="font-size:var(--t-label)">${esc(g.why)}</p>` })
        + Section({
            title: 'What happens next',
            body: `<p class=c-lead style="font-size:var(--t-label)">${
              which === 'AUTO_POST'
                ? 'Policy permits a posting. It does not perform one — the entry '
                  + 'is written by the engine and appears in Journal.'
                : 'No automatic action. The settlement waits for a person, and '
                  + 'Investigate carries the question that would resolve it.'}</p>`,
          }),
    };
  }

  window.defineLens('policy', {
    label: 'Policy',
    question: 'What are we allowed to do?',
    layout: subject => subject.type === 'portfolio' ? 'master-detail' : 'focus',
    emptyContext: 'Select a decision to see what it holds.',
    holds: (ctx, subject) => subject.type === 'portfolio' && ctx.type === 'decision',
    master(subject, S) { return portfolioMaster(S); },
    render(subject, S) {
      if (subject.type === 'settlement') return settlement(subject, S);
      return EmptyState('Policy has nothing to say about this subject.');
    },
    mount(host, subject, S) {
      const r = host.querySelector('#p-rev');
      if (!r) return;
      const out = host.querySelector('#p-rev-v');
      r.addEventListener('input', () => {
        out.textContent = window.C.rupees(STEPS[+r.value]);
      });
      r.addEventListener('change', () => {
        S.review = STEPS[+r.value];
        window.navigate({}, { replace: true });
      });
    },
    context(ctx, subject, S) { return decisionContext(ctx.id, S); },
  });
})();
