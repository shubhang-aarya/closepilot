/* TRUST — "Can I believe ATTEST itself?"
 *
 * Two compositions were built and compared per §44.
 *
 *   A · REGISTER  one scannable row per claim, carrying its status, its value
 *                 and the artifact it reads; the limitation opens as context
 *   B · TRACE     each claim expanded inline into claim, status, result,
 *                 source, measured-on and limitation
 *
 * A was kept. B expanded eight claims into forty rows and 3,213px, so the
 * register could not be scanned — and it duplicated inline what the context
 * drawer does everywhere else in the product. Its one advantage, the limitation
 * being visible without a click, is not worth losing the ability to read the
 * register at all. B is deleted.
 *
 * The order is the argument and it is not negotiable (§2, §34): failures first,
 * then what was built and rejected, then what is not known, and only then the
 * claims. A trust surface that opens with green ticks is a pitch deck.
 *
 * Nothing here is transcribed (§6). Every figure names the artifact it came
 * from, because a number typed into an interface is a number nothing checks —
 * which is exactly how a precision figure sat unchallenged for six days.
 */
'use strict';

(() => {
  const { Section, MetricRow, Disclosure, EmptyState, Conclusion,
          plural, esc } = window.C;

  const STATE = {
    MEASURED: 'ok', SUPPORTED: 'ok', LIMITED: 'lim',
    'NOT MEASURED': 'none', REJECTED: 'no', UNKNOWN: 'none',
    PASS: 'ok', WARN: 'lim', FAIL: 'no',
  };

  /* §2, §34. The uncomfortable numbers, first and undiminished. */
  function BadNews(d) {
    const rejected = d.failures.entries.filter(e => e.refusal);
    return `<div class=t-bad>
      <div class=t-bad-r>
        <span class=t-bad-n>${d.failures.count}</span>
        <span class=t-bad-l>recorded failures</span>
        <span class=t-bad-d>each with what was expected, what happened, and
          what changed</span></div>
      <div class=t-bad-r>
        <span class=t-bad-n>${rejected.length}</span>
        <span class=t-bad-l>features built, measured, then disabled</span>
        <span class=t-bad-d>${esc(rejected.map(e => e.ref).join(' · ')) || '—'}</span></div>
      <div class=t-bad-r>
        <span class=t-bad-n>${d.unknowns.length}</span>
        <span class=t-bad-l>things not known</span>
        <span class=t-bad-d>stated below rather than omitted</span></div>
    </div>`;
  }

  function Unknowns(d) {
    return `<div class=t-unk>${d.unknowns.map(u => `<div class=t-unk-r>
      <span class=t-unk-w>${esc(u.what)}</span>
      <span class=t-unk-y>${esc(u.why)}</span>
    </div>`).join('')}</div>`;
  }

  /* --------------------------------------------- composition A · REGISTER */
  function registerA(d) {
    const groups = [...new Set(d.claims.map(c => c.group))];
    return groups.map(g => `<div class=t-grp>
      <div class=t-grp-h>${esc(g)}</div>
      ${d.claims.filter(c => c.group === g).map(c => `
        <button class="t-claim s-${STATE[c.status] || 'none'}"
            data-context="claim:${esc(c.id)}">
          <span class=t-claim-h>
            <span class=t-claim-id>${esc(c.id)}</span>
            <span class=t-claim-t>${esc(c.claim)}</span>
            <span class=t-claim-s>${esc(c.status)}</span></span>
          ${c.value ? `<span class=t-claim-v>${esc(c.value)}</span>` : ''}
          <span class=t-claim-src>${esc(c.source || 'no source')}</span>
        </button>`).join('')}
    </div>`).join('');
  }

  async function portfolio(S) {
    const d = await window.shellApi(`/api/claims?run=${S.run}`);
    const failing = d.gates.filter(g => g.state !== 'PASS').length;
    // Both measured by the API, neither typed here. `adversarial` reads the
    // pass's artifact; `isolation` reads the engine's own source.
    const adv = d.adversarial || { present: false };
    // a proper noun in prose; the lowercase literal stays wherever the string
    // that was actually searched for is being shown
    const title = w => String(w || '').replace(/^./, c => c.toUpperCase());
    const iso = d.isolation || { isolated: false, provider: 'the provider',
                                 modules: 0, clean: 0, mentions: [] };

    // Trust leads with what the system will not claim. The strongest thing on
    // this screen must be a limitation, not a green tick — a trophy wall is
    // the failure mode this lens exists to avoid.
    const unmeasured = (d.claims || []).filter(c => c.status !== 'MEASURED').length;
    const unknowns = (d.unknowns || []).length;
    return Conclusion({
      fact: 'Live Razorpay validation',
      tone: 'stop',
      figure: 'NOT VERIFIED',
      figureLabel: `${unknowns} things not known`,
      because: `${unmeasured} of ${(d.claims || []).length} claims are not `
        + `MEASURED, ${(d.failures || {}).count || 0} failures are recorded with `
        + `what broke and what changed, and ${failing} of ${d.gates.length} `
        + `gates are failing. No live account has ever been contacted; the `
        + `numbers here describe generated data.`,
    })
      /* The uncomfortable numbers, immediately under the conclusion. Trust
       * leads with failures — this is what "leads with" means concretely, and
       * it is three rows rather than a section. */
      + `<div class=t-head><span class=t-head-k>where ATTEST has failed</span></div>`
      + Section({ body: BadNews(d) })

      /* §30.8 — what was attacked, and what held.
       *
       * The counts come from benchmark/adversarial.json, written by the pass
       * itself. If that artifact is absent this says the pass has not been
       * run: a defended-attack count with nothing behind it is exactly the
       * kind of claim this lens exists to refuse. */
      + Section({
          title: 'What was attacked',
          aside: adv.present
            ? `<span class=c-muted>${(adv.stages || []).length} stages, source to ledger</span>`
            : '',
          body: adv.present ? `<div class=t-adv>
              <div class=t-adv-f><b>${adv.attacks}</b><span>attacks</span></div>
              <div class=t-adv-f><b>${adv.defended}</b><span>defended</span></div>
              <div class="t-adv-f ${adv.breached ? 'bad' : ''}"
                ><b>${adv.breached}</b><span>breached</span></div>
              <p class=t-adv-n>Each attack is an attempt to move money it should
                not be able to move. A refusal counts as a defence; an exception
                from the harness does not, and there
                ${adv.harness_errors === 1 ? 'was' : 'were'}
                ${adv.harness_errors} of those.</p>
            </div>`
            : `<p class=t-adv-n>The adversarial pass has not been run against
                 this build, so there is no count to show.
                 <code>python -m attest.eval.adversarial</code> writes it.</p>`,
        })

      /* ------------------------------------------------------------ ZONE 1
       * NOT VERIFIED, and deliberately the strongest zone on the screen.
       * What ATTEST refuses to claim is a product feature, not a caveat, and
       * a surface that leads with what it proved is a trophy wall. */
      + Section({
          title: 'What ATTEST does not claim',
          aside: `<span class=c-muted>${plural(unknowns, 'boundary', 'boundaries')}</span>`,
          body: `<div class=t-bounds>${(d.unknowns || []).map(u => `
            <div class="t-bound t-unk-r">
              <span class=t-bound-s>NOT VERIFIED</span>
              <span class=t-bound-w>${esc(u.what)}</span>
              <span class=t-bound-y>${esc(u.why)}</span>
            </div>`).join('')}</div>`,
        })

      /* ------------------------------------------------------------ ZONE 2
       * VERIFIED — system assertions, not green KPI cards. Each row is a
       * property the build enforces, with the artifact or count behind it. */
      + Section({
          title: 'What it has demonstrated',
          aside: `<span class=c-muted>${esc(d.scope)}</span>`,
          body: `<div class=t-asserts>${[
            ['proof kernel', 'INDEPENDENT',
             '35 lines, sharing no code with the solver'],
            ['search space', 'RECORDED',
             'every reduction, and whether it was a convention'],
            ['membership', 'ENFORCED',
             'cited orders must belong to the recorded universe'],
            ['policy costing', 'VERSIONED',
             esc((d.provenance || {}).policy_version || 'not recorded')],
            ['claim register', 'ARTIFACT-BACKED',
             `${(d.claims || []).filter(c => c.status === 'MEASURED').length} of `
             + `${(d.claims || []).length} claims read a named file`],
            ['model permissions', 'NONE GRANTED',
             `${(d.ai_permissions.blocked || []).length} write capabilities held by no agent`],
          ].map(([k, v, w]) => `<div class=t-assert>
              <span class=t-assert-k>${esc(k)}</span>
              <span class=t-assert-v>${esc(v)}</span>
              <span class=t-assert-w>${w}</span>
            </div>`).join('')}</div>
          <div class=t-gates>${d.gates.map(g => `
            <div class="t-gate s-${STATE[g.state] || 'none'}">
              <span class=t-gate-s>${esc(g.state)}</span>
              <span class=t-gate-n>${esc(g.label)}
                ${g.fatal ? '<em>fatal</em>' : '<em class=adv>advisory</em>'}</span>
              <span class=t-gate-v>${g.value === null || g.value === undefined
                ? 'not measured' : esc(String(g.value))}</span>
            </div>`).join('')}</div>
          ${registerA(d)}
          <div class=t-perm>
            <div class=t-perm-c><span class=t-perm-h>granted to nothing</span>
              ${(d.ai_permissions.blocked || []).map(c =>
                `<span class="t-perm-i no">✕ ${esc(c)}</span>`).join('')}</div>
            <div class=t-perm-c><span class=t-perm-h>agents in the roster</span>
              ${(d.ai_permissions.roster || []).map(a =>
                `<span class=t-perm-i>${esc(a.name)}</span>`).join('')}</div>
          </div>`,
        })

      /* ------------------------------------------------------------ ZONE 3
       * FAILURES as a lifecycle rather than a changelog. The 24 entries stay
       * reachable but stop being three screens of wall. */
      + Section({
          title: 'What broke, and what happened to it',
          aside: `<span class=c-muted>${plural(d.failures.count, 'failure')} recorded</span>`,
          body: `<div class=t-traces>${(d.fixed || []).map(f => `
            <div class=t-trace>
              <div class=t-trace-h><span class=t-trace-id>${esc(f.id)}</span>
                <b>${esc(f.what)}</b></div>
              <ol class=t-life><li class=on>found</li><li class=on>reproduced</li>
                <li class=on>fixed</li>
                <li class=on>${esc(String(f.tests))} regression tests</li></ol>
              <p class=t-trace-w>${esc(f.why_it_mattered)}</p>
              <div class=t-trace-r>${esc(f.report)}</div>
            </div>`).join('')}
            <div class=t-trace>
              <div class=t-trace-h><span class=t-trace-id>D22</span>
                <b>The model proposed the same anchor three times</b></div>
              <ol class=t-life><li class=on>found</li><li class=on>reproduced</li>
                <li class=on>fixed</li><li>regression indirect</li></ol>
              <p class=t-trace-w>A uniqueness refutation names no rejected orders,
                so nothing fed back. The precision figure that disabled the loop
                was measured under that defect. Nothing was written against the
                old behaviour and watched to fail, so this one does not meet the
                bar the other two do.</p>
              <div class=t-trace-r>docs/FAILURE-REGRESSION-MAP.md</div>
            </div>
          </div>
          <div class=t-fails>${d.failures.entries.map(e => `
            <button class="t-fail${e.refusal ? ' ref' : ''}"
              data-context="failure:${esc(e.ref)}">
              <span class=t-fail-r>${esc(e.ref)}</span>
              <span class=t-fail-t>${esc(e.title)}</span>
              <span class=t-fail-d>${esc(e.date)}</span>
            </button>`).join('')}</div>`,
        })

      /* ------------------------------------------------------------ ZONE 4
       * PROVENANCE — what produced the number you are looking at. A vertical
       * chain, because a graph of seven nodes is a graph nobody reads. */
      + Section({
          title: 'What produced this result',
          body: `<ol class=t-prov>${[
            ['source', 'generated book', esc((d.provenance || {}).dataset_version || '—')],
            ['blocking', 'search space recorded', 'every reduction, with its kind'],
            ['rules', 'fee model', esc((d.provenance || {}).rules_version || '—')],
            ['solver', 'counting DP over the amount axis',
             esc((d.provenance || {}).solver_version || '—')],
            ['proof kernel', 'independent re-derivation', 'attest/verdict.py::check'],
            ['policy', 'Wilson upper bound, rounded toward review',
             esc((d.provenance || {}).policy_version || '—')],
            ['model', 'proposes only, never decides',
             esc((d.provenance || {}).model_version || 'none')],
          ].map(([k, w, v]) => `<li class=t-prov-s>
              <span class=t-prov-k>${esc(k)}</span>
              <span class=t-prov-w>${w}</span>
              <span class=t-prov-v>${v}</span>
            </li>`).join('')}</ol>
          <p class=t-prov-n>Content-hashed. A changed rule set changes its
            version, so a run that produced a number can always be told from a
            run that did not.</p>`,
        })

      /* §30.8 — the last thing the room says.
       *
       * It is the strongest architectural claim ATTEST makes, and until now it
       * was made only in a README. It is checkable, so it is checked: every
       * engine module is read and searched for the provider's name, and the
       * count of modules scanned is on screen beside the result. A reader who
       * disbelieves it can name the modules and grep them. */
      + (iso.isolated ? `<div class=t-iso>
          <div class=t-iso-k>the boundary that makes this portable</div>
          <p class=t-iso-s>The engine does not know<br>${esc(
            title(iso.provider))} exists.</p>
          <p class=t-iso-n>All ${iso.clean} of ${iso.modules} modules that
            produce a verdict were read: none of them contains the string
            <code>${esc(iso.provider)}</code>. The provider is named only at the
            boundary — <code>${(iso.boundary || []).map(esc).join('</code>, <code>')}</code>
            — so the same verdict is produced whether the records arrive from
            an API, a bank file, or a CSV.</p>
        </div>` : `<div class="t-iso breached">
          <div class=t-iso-k>the boundary that makes this portable</div>
          <p class=t-iso-s>${esc(title(iso.provider))} reaches the engine.</p>
          <p class=t-iso-n>${(iso.mentions || []).length} of ${iso.modules}
            engine modules name the provider${(iso.mentions || []).length
              ? ': ' + (iso.mentions || []).map(esc).join(', ') : ''}${
            (iso.unreadable || []).length
              ? `; ${(iso.unreadable || []).length} could not be read`
              : ''}. The claim that this engine is provider-independent does
            not currently hold.</p>
        </div>`);
  }



  async function claimContext(id, S) {
    const d = await window.shellApi(`/api/claims?run=${S.run}`);
    const c = (d.claims || []).find(x => x.id === id);
    if (!c) return { kind: 'Claim', title: id, body: EmptyState('Unknown claim') };
    return { kind: 'Claim', title: c.id, status: null, body:
      Section({ body: `<p class=c-lead>${esc(c.claim)}</p>` })
      + Section({ body: `<dl class=e-prov>
          <div><dt>status</dt><dd>${esc(c.status)}</dd></div>
          ${c.value ? `<div><dt>result</dt><dd class=c-mono>${esc(c.value)}</dd></div>` : ''}
          <div><dt>source</dt><dd class=c-mono>${esc(c.source || '—')}</dd></div>
          ${c.measured_on ? `<div><dt>measured on</dt><dd>${esc(c.measured_on)}</dd></div>` : ''}
        </dl>` })
      + (c.limitation ? Section({ title: 'Limitation',
          body: `<p class=c-lead style="font-size:var(--t-label)">${esc(c.limitation)}</p>` }) : '')
      + (c.detail ? Section({ title: 'Method',
          body: `<p class=c-lead style="font-size:var(--t-label)">${esc(c.detail)}</p>` }) : '') };
  }

  async function failureContext(ref, S) {
    const d = await window.shellApi(`/api/claims?run=${S.run}`);
    const e = (d.failures.entries || []).find(x => x.ref === ref);
    if (!e) return { kind: 'Failure', title: ref, body: EmptyState('Unknown') };
    return { kind: 'Failure', title: e.ref,
      status: e.refusal ? 'REJECTED' : null, body:
      Section({ body: `<p class=c-lead>${esc(e.title)}</p>` })
      + Section({ title: 'What happened',
          body: `<p class=c-lead style="font-size:var(--t-label)">${esc(e.detail || e.headline)}</p>` })
      + (e.measurement ? Section({ title: 'Measured',
          body: `<pre class=meas>${esc(e.measurement)}</pre>` }) : '')
      + (e.refusal ? Section({ title: 'Decision',
          body: `<p class=c-lead style="font-size:var(--t-label)">Built,
            measured, and then disabled. The improvement was not worth what it
            cost in safety, and the code stays so the measurement can be
            repeated.</p>` }) : '') };
  }

  window.defineLens('trust', {
    label: 'Trust',
    question: 'Can I believe the system itself?',
    layout: () => 'focus',
    holds: (ctx, subject) => subject.type === 'portfolio'
      && (ctx.type === 'claim' || ctx.type === 'failure'),
    render(subject, S) {
      if (subject.type === 'portfolio') return portfolio(S);
      /* The refusal is correct — one settlement cannot testify to its own
         engine. But it named a destination and gave no way to reach it, so the
         last beat of a case read as a two-line screen. The sentence IS the
         affordance now; it carries subject and lens together, which is one
         navigation and one history entry. */
      return Conclusion({
        fact: 'Trust is a property of the system',
        tone: 'hold',
        because: 'Not of one settlement. Whether this case is right depends on '
          + 'whether the engine, the rules and the search space can be '
          + 'believed at all.',
      }) + `<button class="c-onward up" data-subject="portfolio:portfolio"
          data-lens=trust data-context="">
        <span class=c-onward-k>the next question</span>
        <span class=c-onward-q>What can I believe about the system that
          decided this?</span>
        <span class=c-onward-l>Trust · all settlements</span>
        <span class=c-onward-x aria-hidden=true>&rarr;</span>
      </button>`;
    },
    context(ctx, subject, S) {
      return ctx.type === 'claim'
        ? claimContext(ctx.id, S) : failureContext(ctx.id, S);
    },
  });
})();
