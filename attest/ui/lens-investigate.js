/* INVESTIGATE — "What should I check next?"
 *
 * Evidence reports established relationships. This reports inquiry, and the two
 * have to look different or the distinction collapses: Evidence is structural
 * and calm, this is temporal and forensic. Question, then hypothesis, then the
 * test, then what was learned when it failed.
 *
 * The failures are the product. A trail cleaned up to make the model look
 * competent is worth nothing, because a reader cannot then tell a good answer
 * from a lucky one — which is the entire reason to show any of this.
 *
 * Three actors, and the layout must make their order impossible to
 * misunderstand: the model PROPOSES, the solver TESTS, the engine DECIDES. A
 * hypothesis can never appear downstream of the verdict it failed to change.
 */
'use strict';

(() => {
  const { Section, Row, MetricRow, Disclosure, EmptyState, Conclusion,
          DecisionRecord, rupees, plural, esc } = window.C;

  const ACTOR = {
    model:  ['Model',  'proposes', 'e-act-model'],
    solver: ['Solver', 'tests',    'e-act-solver'],
    engine: ['Engine', 'decides',  'e-act-engine'],
  };

  /* §16. Every event states actor, action, input and result — never a sentence
     that has to be parsed to work out which of the three did what. */
  function Timeline(steps) {
    return `<ol class=i-tl>${steps.map(s => {
      const [name, , cls] = ACTOR[s.actor] || [s.actor, '', ''];
      return `<li class="i-tl-s ${esc(cls)}${s.result ? ' has-r' : ''}">
        <i class=i-tl-m aria-hidden=true></i>
        <div class=i-tl-b>
          <div class=i-tl-h>
            <span class=i-tl-a>${esc(name)}</span>
            <span class=i-tl-v>${esc(s.action)}</span>
            ${s.input ? `<span class=i-tl-i>${esc(s.input)}</span>` : ''}
            ${s.result ? `<span class="i-tl-r r-${esc(s.result)}"
              >${esc(s.result.replace(/_/g, ' '))}</span>` : ''}
          </div>
          <div class=i-tl-d>${esc(s.detail)}</div>
          ${s.why ? `<div class=i-tl-w>${esc(s.why)}</div>` : ''}
        </div></li>`;
    }).join('')}</ol>`;
  }

  /* THE AI BOUNDARY.
   *
   * The strongest fact about this system was only in the payload: the loop's
   * verdict is computed and then discarded, so the model's conclusion cannot
   * become the financial one. `changed_nothing` was true and nobody could see
   * it.
   *
   * The order stated here is the order the code executes. Deterministic
   * reconciliation established AMBIGUOUS first; only then was the model asked
   * for an anchor; then the solver tested whether that anchor DISCRIMINATES.
   * The solver is not adjudicating the model — it never asks whether the model
   * was right, only whether what it proposed separates the surviving
   * explanations. Getting that backwards would make the model sound like the
   * author of the answer, which is the one thing this instrument exists to
   * deny.
   *
   * The benchmark note is supporting evidence, not the hero, and it is read
   * from the payload — which reads it from benchmark/anchoring.json. It is a
   * property of the loop across a panel, never of this settlement. */
  function AiBoundary(d) {
    if (d.state !== 'abstained') return '';
    const m = d.measurement;
    const step = (mark, actor, did) =>
      `<div class=i-bound-s><i class="i-bound-dot ${mark}" aria-hidden=true></i>
         <b>${actor}</b><span>${did}</span></div>`;
    /* §30.4 — the experiment's terminal, stated at the size of the claim.
     *
     * Every piece of this was already on screen and it read as a footnote: the
     * three actors as three small rows, and the sentence that matters — that
     * the loop moved no money — as the first clause of a paragraph. It is the
     * one thing a judge is meant to leave with, so it is now the largest thing
     * in the room. No new words: "No financial action." was lifted out of the
     * prose below rather than written a second time. */
    return `<div class=i-bound>
      <div class=i-bound-k><span class=n>03</span>the boundary</div>
      <div class=i-bound-seq>
        ${step('model', 'MODEL', 'proposed an anchor')}
        ${step('solver', 'SOLVER', 'tested whether the anchor discriminates')}
        ${step('engine', 'ENGINE', 'original verdict retained')}
      </div>
      <div class=i-bound-t>
        <b>Verdict unchanged</b>
        <b>No financial action</b>
      </div>
      <div class=i-bound-r>
        <span><i>tested</i><b>${d.tested}</b></span>
        <span><i>discriminative</i><b>${d.discriminative}</b></span>
        <span><i>model output</i>diagnostic only</span>
        <span><i>verdict</i><b class="c-status s-${esc(d.verdict)} sm"
          >${esc(d.verdict)}</b></span>
        <span><i>changed</i><b>No</b></span>
      </div>
      <div class=i-bound-x>The loop's conclusion is recorded as evidence and
        discarded; it is not eligible to become the verdict, and nothing
        downstream reads it.</div>
      ${m && m.resolved ? `<p class=i-bound-m-note>Benchmark, not this
        settlement: re-measured across the evaluation panel, the loop offered an
        answer on <b>${m.resolved} of ${m.ambiguous}</b> ambiguous cases — silent
        on ${(m.silent_share * 100).toFixed(0)}% of the work it exists for — and
        was right on <b>${m.correct}</b> of those ${m.resolved}. That is why it
        does not decide.</p>` : ''}
    </div>`;
  }

  /* §25's abstention block is gone. It stated the verdict, that no financial
     action was taken, and that nothing the model proposed separated the
     explanations — which is what the boundary above now says, with the counts
     folded in. Two blocks making the same point is the duplication this
     product has been removing throughout. */

  async function settlement(subject, S) {
    const [d, loop] = await Promise.all([
      window.shellApi(`/api/investigation?run=${S.run}`
        + `&type=settlement&id=${encodeURIComponent(subject.id)}`),
      window.shellApi(`/api/loop?run=${S.run}`
        + `&id=${encodeURIComponent(subject.id)}`),
    ]);
    if (d.error) return EmptyState(d.error);
    const chain = DecisionRecord(loop);

    // The loop's outcome is the answer, and the fact that the verdict did NOT
    // change is the product's whole claim about where the model sits.
    const OUT = { abstained: ['Engine abstained', 'stop'],
                  resolved: ['Engine resolved it', 'go'],
                  open: ['Still open', 'hold'] };
    const [word, tone] = OUT[d.state] || ['Engine abstained', 'stop'];
    const head = Conclusion({
      fact: word, tone,
      figure: d.verdict_changed ? null : 'Verdict unchanged',
      because: d.tested
        ? `${plural(d.tested, 'anchor')} tested, ${d.discriminative} `
          + `discriminative. ${d.note || ''}`.trim()
        : (d.note || ''),
    }) + `<div class=i-q>
      <span class=i-q-k>the question</span>
      <h2>${esc(d.question)}</h2></div>`;

    if (!d.steps.length) {
      /* The resolution loop did not run, so `head` — which narrates that loop —
         has nothing true to say. It said "Still open · Verdict unchanged" over
         a settlement that is PROVEN, AUTO-POSTED and in the ledger, directly
         under a control loop showing exactly that. A conclusion that
         contradicts the instrument above it is worse than no conclusion. */
      const settled = loop && loop.acted;
      return chain + Conclusion({
        fact: settled ? 'Resolved without a person'
                      : `Nothing to investigate — ${esc(d.verdict.toLowerCase())}`,
        tone: settled ? 'go' : 'hold',
        figure: settled ? 'Advisory input changed nothing' : null,
        because: settled
          ? 'The arithmetic was already unique, so no tie needed breaking. The '
            + 'advisor proposed anyway, and the engine reached the same answer '
            + 'without reading it — which is what the boundary looks like on a '
            + 'case that ends in money moving.'
          : 'The resolution loop runs only on ambiguity, and this settlement is '
            + 'not ambiguous.',
      }) + `<div class=i-q>
        <span class=i-q-k>the question</span>
        <h2>${esc(d.question)}</h2></div>` + Section({
        title: 'No tie to break',
        body: `<p class=c-lead>The <em>resolution</em> loop only runs on
          ambiguity. A ${esc(d.verdict.toLowerCase())} settlement is not a case
          of the engine being unable to choose — it is a case of there being
          nothing to choose between, so there is nothing for an advisor to
          resolve. The advisor above still ran; the loop above shows where its
          proposal sat relative to an answer reached without it.</p>`,
      }) + Resolvers(d);
    }

    /* §31 — the order the room is read in.
     *
     * The three actors and what they produced is the single thing this
     * instrument exists to show, and it was FOURTH: conclusion, question, a
     * five-row trail of solver output, a section on why one lens was silent,
     * and only then the boundary. A judge scrolling past the question hit a
     * log, and the sentence the whole product turns on — the engine keeping a
     * verdict the model could not move — was below the fold on every screen
     * size we test.
     *
     * So the boundary comes straight after the question, and the trail becomes
     * what it always was: the evidence for a claim already made. Nothing was
     * removed; the order changed, which is the difference between a story and
     * a log. */
    return chain + head
      + AiBoundary(d)
      + Section({
          title: 'What was tried',
          aside: `<span class=c-muted>${plural(d.tested, 'test')} ·
            ${d.discriminative} discriminative</span>`,
          body: Timeline(d.steps),
        })
      + (d.signal ? Section({
          title: 'Why that lens had nothing to say here',
          body: `<div class=i-sig">
            <div class=i-sig-r>
              <span class=i-sig-n>${d.signal.capture_dates}</span>
              <span class=i-sig-l>capture ${d.signal.capture_dates === 1
                ? 'date' : 'dates'} across ${plural(d.signal.pool, 'candidate')}</span>
            </div>
            <p class=i-sig-d>${esc(d.signal.note)}</p>
          </div>` + (d.signal.share_single_date != null ? Disclosure({
            summary: 'Is that particular to this settlement?',
            body: `<p>Measured across the evaluation seeds,
              ${(d.signal.share_single_date * 100).toFixed(0)}% of candidate
              pools span a single capture date. The pool is built by inverting
              the settlement calendar, so a pool largely IS a capture date — the
              lens and the blocking are asking the same question, and the lens
              adds nothing on top of it.</p>`,
          }) : ''),
        }) : '')
      + Resolvers(d);
  }

  /* §20. Investigation has to end somewhere an operator can act. */
  function Resolvers(d) {
    if (!d.resolvers || !d.resolvers.length) return '';
    return Section({
      title: 'What would resolve this',
      body: `<div class=i-res>${d.resolvers.map(x => `<div class=i-res-r>
        <span class="i-res-s s-${esc((x.status || '').replace(/\s/g, '-'))}"
          >${esc(x.status)}</span>
        <span class=i-res-w>${esc(x.what)}</span>
        <span class=i-res-d>${esc(x.would)}</span>
      </div>`).join('')}</div>`,
    });
  }

  /* ------------------------------------------------------------- portfolio */
  async function portfolioMaster(S) {
    const d = await window.shellApi(`/api/investigation?run=${S.run}&type=portfolio`);
    return Conclusion({
      fact: `${plural(d.groups.length, 'question')} account for the ambiguity`,
      figure: rupees(d.total_paise), figureLabel: 'behind them',
      tone: 'hold',
      because: 'Ordered by what an answer would unlock, not by amount. A '
        + 'question that resolves 197 settlements at once outranks one worth '
        + 'more on a single case.',
    }) + `<div class=i-q><span class=i-q-k>the queue</span>
        <h2>What should be investigated first?</h2></div>`
      + Section({
          aside: `<span class=c-muted>${esc(rupees(d.total_paise, { whole: true }))} behind ${
            plural(d.groups.length, 'question')}</span>`,
          body: d.groups.map(g => `<button class="i-case ${g.one_answer ? 'one' : 'many'}"
              data-context="cause:${esc(g.reason)}">
              <span class=i-case-q>${esc(g.question)}</span>
              <span class=i-case-m>
                <em>${esc(rupees(g.value_paise, { whole: true }))}</em>
                <span>${plural(g.settlements, 'settlement')}</span>
                <span class=i-case-k>${g.one_answer ? 'one answer' : 'one each'}</span>
              </span>
            </button>`).join('')
            + Disclosure({
                summary: 'How this is ordered',
                body: `<p>${esc(d.note)}</p>`,
              }),
        });
  }

  async function causeContext(reason, S) {
    const d = await window.shellApi(`/api/investigation?run=${S.run}&type=portfolio`);
    const g = (d.groups || []).find(x => x.reason === reason);
    if (!g) return { kind: 'Cause', title: 'Unknown', body: EmptyState('Unknown') };
    return {
      kind: 'Cause', title: g.question,
      body: Section({
          body: MetricRow([
            { label: 'behind this question', value: rupees(g.value_paise, { whole: true }),
              tone: g.one_answer ? 'proven' : 'ambiguous' },
            { label: 'settlements', value: String(g.settlements), note: g.worth },
          ]),
        })
        + Section({ title: 'Why they are stuck',
            body: `<p class=c-lead style="font-size:var(--t-label)">${esc(g.cause)}</p>` })
        + Section({
            title: 'Investigate one',
            body: g.examples.map(x => Row({
              id: x.replace('setl_', ''),
              subject: { type: 'settlement', id: x },
            })).join(''),
          }),
    };
  }

  async function stepContext(i, sid, S) {
    const d = await window.shellApi(`/api/investigation?run=${S.run}`
      + `&type=settlement&id=${encodeURIComponent(sid)}`);
    const s = (d.steps || [])[+i];
    if (!s) return { kind: 'Step', title: '—', body: EmptyState('No such step') };
    const [name] = ACTOR[s.actor] || [s.actor];
    // §12: a hypothesis is not a subject anything can be about, so no promotion
    // is offered. An affordance that leads nowhere teaches the wrong model.
    return {
      kind: name, title: s.input || s.action,
      status: s.result || null,
      body: Section({
          body: `<dl class=e-prov>
            <div><dt>actor</dt><dd>${esc(name)} — ${esc((ACTOR[s.actor] || [,''])[1])}</dd></div>
            <div><dt>action</dt><dd>${esc(s.action)}</dd></div>
            ${s.input ? `<div><dt>input</dt><dd>${esc(s.input)}</dd></div>` : ''}
            ${s.result ? `<div><dt>result</dt><dd>${esc(s.result.replace(/_/g, ' '))}</dd></div>` : ''}
          </dl>`,
        })
        + Section({ title: 'What it said', body: `<p class=c-lead
            style="font-size:var(--t-label)">${esc(s.detail)}</p>` })
        + (s.why ? Section({ title: 'What that means',
            body: `<p class=c-lead style="font-size:var(--t-label)">${esc(s.why)}</p>` }) : '')
        + Section({ title: 'Provenance',
            body: `<dl class=e-prov>${Object.entries(d.provenance || {})
              .map(([k, v]) => `<div><dt>${esc(k.replace('_version', ''))}</dt>
                <dd class=c-mono>${esc(v)}</dd></div>`).join('')}</dl>` }),
    };
  }

  window.defineLens('investigate', {
    label: 'Investigate',
    question: 'What should I check next?',
    layout: subject => subject.type === 'portfolio' ? 'master-detail' : 'focus',
    emptyContext: 'Select a question to see what is behind it.',
    holds: (ctx, subject) => subject.type === 'portfolio'
      ? ctx.type === 'cause'
      : ctx.type === 'step',
    master(subject, S) { return portfolioMaster(S); },
    render(subject, S) {
      if (subject.type === 'settlement') return settlement(subject, S);
      return EmptyState('Investigate has nothing to say about this subject.');
    },
    mount(host, subject) {
      if (subject.type !== 'settlement') return;
      host.querySelectorAll('.i-tl-s').forEach((n, i) =>
        n.setAttribute('data-context', `step:${i}`));
    },
    context(ctx, subject, S) {
      return ctx.type === 'cause'
        ? causeContext(ctx.id, S)
        : stepContext(ctx.id, subject.id, S);
    },
  });
})();
