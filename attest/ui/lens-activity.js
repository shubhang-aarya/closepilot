/* ACTIVITY — "What actually happened?"
 *
 * A log answers "what events exist". This has to answer what happened, what
 * caused it, what changed, and what it did to the money — so causality is the
 * connector between events rather than a column beside them, and every entry
 * carries its cause above it and its effect below.
 *
 * Two boundaries are kept apart structurally rather than by wording:
 *
 *     POLICY   records what was PERMITTED
 *     ACTION   records what was DONE
 *
 * They are separate stages with separate actors, because a settlement can be
 * permitted and unposted and a reader must see that at a glance. Collapsing
 * permission into execution is the one mistake this lens exists to prevent.
 *
 * Two things this system genuinely does not have, and which are therefore
 * absent rather than invented: human review events (no operator identity is
 * recorded anywhere) and failed postings (the ledger write is in-process and
 * deterministic). §16 and §19 asked for real data, and the honest form of that
 * is a gap where the data is a gap.
 */
'use strict';

(() => {
  const { Section, Row, MetricRow, Disclosure, EmptyState, Conclusion,
          rupees, plural, esc } = window.C;

  const ACTOR = {
    system: ['System', '▪'], model: ['Model', '◇'], solver: ['Solver', '○'],
    engine: ['Engine', '●'], policy: ['Policy', '▣'], human: ['Human', '◆'],
  };

  function Event(e, i) {
    const [name, glyph] = ACTOR[e.actor] || ['—', '·'];
    const permBadge = e.permitted !== undefined
      ? `<span class="a-badge ${e.permitted ? 'yes' : 'no'}">${
          e.permitted ? 'permitted' : 'not permitted'}</span>` : '';
    const execBadge = e.executed !== undefined
      ? `<span class="a-badge ${e.executed ? 'done' : 'undone'}">${
          e.executed ? 'executed' : 'not executed'}</span>` : '';
    return `${e.caused_by ? `<div class=a-cause>
        <i aria-hidden=true></i><span>because ${esc(e.caused_by)}</span></div>` : ''}
      <div class="a-ev a-${esc(e.actor || 'none')}" data-context="event:${i}">
        <i class=a-mark aria-hidden=true>${glyph}</i>
        <div class=a-body>
          <div class=a-h>
            <span class=a-actor>${esc(name)}</span>
            <span class=a-stage>${esc(e.stage)}</span>
            <span class=a-at>${esc(e.at || '')}</span>
          </div>
          <div class=a-what>${esc(e.what)}
            ${e.result ? `<span class="a-res r-${esc(e.result.replace(/\s/g, '_'))}"
              >${esc(e.result)}</span>` : ''}
            ${permBadge}${execBadge}</div>
          ${e.value ? `<div class=a-val>${esc(e.value)}</div>` : ''}
          ${e.effect ? `<div class=a-eff>${esc(e.effect)}</div>` : ''}
        </div>
      </div>`;
  }

  async function settlement(subject, S) {
    const d = await window.shellApi(`/api/activity?run=${S.run}`
      + `&type=settlement&id=${encodeURIComponent(subject.id)}`);
    if (d.error) return EmptyState(d.error);

    // Activity's question is what actually happened, and the most important
    // fact is usually what did NOT: eight events ran and the ledger is
    // unchanged. An absence is a result.
    const posted = d.state && d.state.posted;
    return Conclusion({
      fact: posted ? 'An entry was written' : 'Ledger unchanged',
      tone: posted ? 'go' : 'hold',
      figure: plural((d.events || []).length, 'event'),
      figureLabel: 'this run',
      because: posted
        ? 'The proof was unique, the policy permitted it, and the entry balances.'
        : `Every event was recorded and none of them changed the verdict. `
          + `It ended ${esc((d.state || {}).verdict || '')} and was decided `
          + `${esc(((d.state || {}).decision || '').replace('_', ' '))}.`,
    }) + `<div class=a-state>
        <span class=a-state-k>where it ended up</span>
        <div class=a-state-r>
          <span class="c-status s-${esc(d.state.verdict)}">${esc(d.state.verdict)}</span>
          <i aria-hidden=true>→</i>
          <span class=a-state-p>${esc(d.state.decision.replace(/_/g, '-'))}</span>
          <i aria-hidden=true>→</i>
          <span class="a-state-a ${d.state.posted ? 'yes' : 'no'}"
            >${d.state.posted ? 'posted' : 'not posted'}</span>
        </div>
      </div>`
      + Section({
          title: 'What happened',
          aside: `<span class=c-muted>${plural(d.events.length, 'event')}</span>`,
          body: `<div class=a-tl>${d.events.map(Event).join('')}</div>`
            + Disclosure({
                summary: 'About these timestamps',
                body: `<p>${esc(d.note)}</p>`,
              }),
        });
  }

  /* ------------------------------------------------------------- portfolio */
  async function portfolioMaster(S) {
    const d = await window.shellApi(`/api/activity?run=${S.run}&type=portfolio`);
    const del = d.delivery_counts || {};

    const unrev = (d.unrevised || []).length;
    /* The figure answers the fact above it. It used to be the delivery count,
       labelled 'events delivered' — which counted arrival, not acceptance, and
       went to zero on a freshly started run. The accept/refuse breakdown is
       stated in 'Deliveries since' below, per status, where it cannot be read
       as a headline claim about what landed. */
    const total = (d.outcome || []).reduce((n, o) => Math.max(n, o.n || 0), 0);
    return Conclusion({
      fact: unrev ? `${plural(unrev, 'settlement')} unrevised`
                  : 'Nothing is unrevised',
      tone: unrev ? 'hold' : 'go',
      figure: total ? `${total - unrev} of ${total}` : '—',
      figureLabel: 'verdicts current',
      because: unrev
        ? 'Events arrived after these settlements were decided; their verdicts '
          + 'have not been recomputed.'
        : (d.unrevised_note || 'Every ingested event is reflected in the '
           + 'current verdicts.'),
    }) + `<div class=a-state>
        <span class=a-state-k>the run</span>
        <div class=a-state-r>
          <span class=c-mono>${esc(d.run.id)}</span>
          <i aria-hidden=true>·</i>
          <span class=a-state-p>${esc(d.run.from)} → ${esc(d.run.to)}</span>
        </div>
      </div>`
      + Section({
          title: 'What the run did',
          body: `<div class=a-out>${d.outcome.map(o => `<div class=a-out-r>
            <span class=a-out-k>${esc(o.k)}</span>
            <span class=a-out-v>${esc(o.v)}</span>
            <span class=a-out-n>${plural(o.n, 'settlement')}</span>
          </div>`).join('')}</div>`,
        })
      + Section({
          title: 'The phases beneath it',
          body: `<div class=a-tl compact>${d.run.phases.map((p, i) => {
            const [name, glyph] = ACTOR[p.actor] || ['—', '·'];
            return `<div class="a-ev a-${esc(p.actor)}" data-context="phase:${i}">
              <i class=a-mark aria-hidden=true>${glyph}</i>
              <div class=a-body>
                <div class=a-h>
                  <span class=a-actor>${esc(name)}</span>
                  <span class=a-stage>${esc(p.what)}</span>
                  <span class=a-at>${esc(p.at)}</span></div>
                <div class=a-eff>${esc(p.detail)}</div>
              </div></div>`;
          }).join('')}</div>`,
        })
      + Section({
          title: 'Deliveries since',
          aside: `<span class=c-muted>${Object.entries(del)
            .map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`).join(' · ') || 'none'}</span>`,
          body: (d.deliveries || []).length
            ? `<div class=a-del>${d.deliveries.slice(0, 10).map(x => `<div class=a-del-r>
                <span class=a-del-t>${esc((x.received_at || '').slice(11, 19))}</span>
                <span class="a-del-k c-mono">${esc(x.kind || '')}</span>
                <span class=a-del-d>${esc(x.detail || '')}</span>
                <span class="a-del-s s-${esc(x.status || '')}"
                  >${esc((x.status || '').replace(/_/g, ' '))}</span>
              </div>`).join('')}</div>`
              + Disclosure({
                  summary: 'Why a repeat delivery changes nothing',
                  body: `<p>Deliveries are de-duplicated on both the event id and
                    a hash of the payload. The same id arriving twice with the
                    same body is ignored; the same id with a different body is a
                    contradiction and neither is acted on. A repeat is recorded
                    and produces no second action.</p>`,
                })
            : EmptyState('Nothing has been delivered since this run decided.'),
        })
      /* Only when something IS unrevised. With nothing to list, the section
         was a heading, a "0 settlements" count and a note repeating the
         conclusion word for word — the empty-heading shape this phase removed
         from the rail. "Nothing is unrevised" is already the room's headline. */
      + ((d.unrevised || []).length
        ? Section({
            title: 'Decided before evidence that names them',
            aside: `<span class=c-muted>${plural(d.unrevised.length, 'settlement')}</span>`,
            body: d.unrevised.map(o => Row({
                id: o.id.replace('setl_', ''), amount: o.amount_paise,
                detail: `<span class=c-muted>named by ${esc(o.because)}</span>`,
                aside: 'unrevised',
                subject: { type: 'settlement', id: o.id },
              })).join('')
              + `<p class=c-lead style="font-size:var(--t-label);margin-top:var(--sp-2)"
                  >${esc(d.unrevised_note)}</p>`,
          })
        : '')
      + Section({
          title: 'Reproduce this run',
          body: `<div class=a-replay>
            <button class="c-ctx-b go" id=a-replay-go>Run it again and compare</button>
            <span class=c-muted>A run is a function of size and seed. This
              executes it a second time and reports whether the verdicts came
              back identical — the original is untouched.</span>
          </div><div id=a-replay-out></div>`,
        });
  }

  async function phaseContext(i, S) {
    const d = await window.shellApi(`/api/activity?run=${S.run}&type=portfolio`);
    const p = (d.run.phases || [])[+i];
    if (!p) return { kind: 'Phase', title: '—', body: EmptyState('No such phase') };
    const [name] = ACTOR[p.actor] || ['—'];
    return { kind: 'Phase', title: p.what, body:
      Section({ body: `<dl class=e-prov>
          <div><dt>at</dt><dd class=c-mono>${esc(p.at)}</dd></div>
          <div><dt>actor</dt><dd>${esc(name)}</dd></div>
          <div><dt>run</dt><dd class=c-mono>${esc(d.run.id)}</dd></div>
        </dl>` })
      + Section({ title: 'What it recorded',
          body: `<p class=c-lead style="font-size:var(--t-label)">${esc(p.detail)}</p>` })
      + Section({ title: 'Immutable',
          body: `<p class=c-lead style="font-size:var(--t-label)">This is what the
            run recorded at the time. Opening it does not re-run anything, and a
            later run does not rewrite it — it becomes a separate record.</p>` }) };
  }

  async function eventContext(i, sid, S) {
    const d = await window.shellApi(`/api/activity?run=${S.run}`
      + `&type=settlement&id=${encodeURIComponent(sid)}`);
    const e = (d.events || [])[+i];
    if (!e) return { kind: 'Event', title: '—', body: EmptyState('No such event') };
    const [name] = ACTOR[e.actor] || ['—'];
    return { kind: e.stage, title: e.what, status: e.result || null, body:
      Section({ body: `<dl class=e-prov>
          <div><dt>actor</dt><dd>${esc(name)}</dd></div>
          <div><dt>phase</dt><dd class=c-mono>${esc(e.at || '')}</dd></div>
          ${e.value ? `<div><dt>value</dt><dd class=c-mono>${esc(e.value)}</dd></div>` : ''}
          ${e.result ? `<div><dt>result</dt><dd>${esc(e.result)}</dd></div>` : ''}
        </dl>` })
      + (e.caused_by ? Section({ title: 'Caused by',
          body: `<p class=c-lead style="font-size:var(--t-label)">${esc(e.caused_by)}</p>` }) : '')
      + (e.effect ? Section({ title: 'Effect',
          body: `<p class=c-lead style="font-size:var(--t-label)">${esc(e.effect)}</p>` }) : '')
      + (e.detail ? Section({ title: 'What it said',
          body: `<p class=c-lead style="font-size:var(--t-label)">${esc(e.detail)}</p>` }) : '')
      + Section({ title: 'Immutable',
          body: `<p class=c-lead style="font-size:var(--t-label)">Inspecting an
            event does not re-run it. If a later run decides differently it
            becomes a separate record rather than an edit to this one.</p>` }) };
  }

  window.defineLens('activity', {
    label: 'Activity',
    question: 'What actually happened?',
    layout: subject => subject.type === 'portfolio' ? 'master-detail' : 'focus',
    emptyContext: 'Select a phase to see what it recorded.',
    holds: (ctx, subject) => subject.type === 'portfolio'
      ? ctx.type === 'phase' : ctx.type === 'event',
    master(subject, S) { return portfolioMaster(S); },
    render(subject, S) {
      if (subject.type === 'settlement') return settlement(subject, S);
      return EmptyState('Activity has nothing to say about this subject.');
    },
    mount(host, subject, S) {
      const go = host.querySelector('#a-replay-go');
      if (!go) return;
      go.addEventListener('click', async () => {
        go.disabled = true; go.textContent = 'Running…';
        const d = await window.shellApi(`/api/replay?run=${S.run}`);
        const out = host.querySelector('#a-replay-out');
        if (!out) return;
        out.innerHTML = `<div class="a-rep ${d.reproduced ? 'ok' : 'no'}">
          <div class=a-rep-v>${d.reproduced ? 'Reproduced' : 'Did not reproduce'}</div>
          <dl class=e-prov>
            <div><dt>original</dt><dd class=c-mono>${esc(d.original.id)}</dd></div>
            <div><dt>replay</dt><dd class=c-mono>${esc(d.replay.id)} · ${d.replay.seconds}s</dd></div>
            <div><dt>settlements</dt><dd>${d.settlements}</dd></div>
            <div><dt>differing</dt><dd>${d.differing}</dd></div>
            <div><dt>provenance</dt><dd>${d.provenance_identical
              ? 'identical' : 'DIFFERENT'}</dd></div>
          </dl>
          <p class=a-rep-n>${esc(d.note)}</p></div>`;
        go.disabled = false; go.textContent = 'Run it again and compare';
      });
    },
    context(ctx, subject, S) {
      return ctx.type === 'phase'
        ? phaseContext(ctx.id, S)
        : eventContext(ctx.id, subject.id, S);
    },
  });
})();
