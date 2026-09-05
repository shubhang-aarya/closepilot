/* Semantic component layer.
 *
 * The autopsy counted 227 CSS classes across 16 screens, 11 different "header"
 * classes and 16 different implementations of one flex-baseline row. Every
 * screen invented its own vocabulary because there was nothing above the token
 * layer to inherit — tokens without components.
 *
 * These are not styling helpers. They are product-semantic primitives: a Metric
 * is "a number that means something with a label and a qualifier", an Amount is
 * "money, in paise, rendered the one correct way". A lens composes these and is
 * not permitted to reach past them for layout, because the moment one does, the
 * next one will, and we are back to 227 classes.
 *
 * Everything returns an HTML string except the stateful pieces (SubjectHeader,
 * LensStrip), which own a DOM node and PATCH it. That distinction is
 * load-bearing: the shell's transitions depend on the header and the strip not
 * being re-rendered when the axis they represent has not changed.
 */
'use strict';

const esc = s => String(s ?? '').replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* Indian digit grouping. One implementation, because a second one would
   eventually disagree with the first about a lakh. */
function rupees(paise, { whole = false, sign = false } = {}) {
  if (paise === null || paise === undefined) return '—';
  const neg = paise < 0;
  const v = Math.abs(paise);
  let r = String(Math.floor(v / 100));
  const p = String(v % 100).padStart(2, '0');
  if (r.length > 3) {
    let head = r.slice(0, -3);
    const tail = r.slice(-3);
    const parts = [];
    while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) parts.unshift(head);
    r = parts.join(',') + ',' + tail;
  }
  const body = whole ? r : `${r}.${p}`;
  return `${neg ? '−' : sign ? '+' : ''}₹${body}`;
}

const plural = (n, one, many) =>
  `${Number(n).toLocaleString()} ${n === 1 ? one : (many || one + 's')}`;

/* ------------------------------------------------------------------ atoms */

const Status = (s, opts = {}) => s
  ? `<span class="c-status s-${esc(s)}${opts.sm ? ' sm' : ''}">${esc(s)}</span>`
  : '';

const Metric = ({ label, value, note, tone }) => `<div class=c-metric>
  <span class=k>${esc(label)}</span>
  <span class=v${tone ? ` style="color:var(--st-${tone})"` : ''}>${value}</span>
  ${note ? `<span class=n>${esc(note)}</span>` : ''}</div>`;

const MetricRow = (metrics) =>
  `<div class=c-metrics>${metrics.map(Metric).join('')}</div>`;

/* Level 2 and 3 of progressive disclosure. Level 1 is whatever the lens shows
   by default; this is what the sceptic opens. Closed on arrival, every time —
   an operator on their ninth visit should not have to re-collapse the essay. */
const Disclosure = ({ summary, body, open = false }) => `<details class=c-disc${open ? ' open' : ''}${open ? ' open' : ''}>
  <summary>${esc(summary)}</summary>
  <div class=c-disc-b>${body}</div></details>`;

const Section = ({ title, aside, body, question }) => `<section class=c-section>
  ${title ? `<div class=c-section-h><h3>${esc(title)}</h3>
    ${question ? `<span class=q>${esc(question)}</span>` : ''}
    ${aside ? `<span class=a>${aside}</span>` : ''}</div>` : ''}
  ${body}</section>`;

/* One row shape. The autopsy found sixteen implementations of this. */
/* `subject` navigates; `context` inspects. Two affordances because they are two
   different acts — one changes what the workspace is about, the other opens
   something inside it. */
const Row = ({ id, amount, status, detail, aside, subject, context, tone }) => {
  const nav = subject || context;
  const attr = context ? `data-context="${esc(context.type)}:${esc(context.id)}"`
             : subject ? `data-subject="${esc(subject.type)}:${esc(subject.id)}"` : '';
  return `<${nav ? 'button' : 'div'} class="c-row${nav ? ' link' : ''}" ${attr}
     ${context ? 'aria-selected=false' : ''}>
    ${tone ? `<i class="c-dot s-${esc(tone)}"></i>` : ''}
    ${id !== undefined ? `<span class=c-row-id>${esc(id)}</span>` : ''}
    ${amount !== undefined ? `<span class=c-row-amt>${esc(rupees(amount))}</span>` : ''}
    ${status ? Status(status, { sm: true }) : ''}
    ${detail !== undefined ? `<span class=c-row-d>${detail}</span>` : ''}
    ${aside !== undefined ? `<span class=c-row-a>${aside}</span>` : ''}
  </${nav ? 'button' : 'div'}>`;
};

const DataTable = ({ cols, rows, foot }) => `<table class=c-table>
  <thead><tr>${cols.map(c =>
    `<th${c.num ? ' class=num' : ''}>${esc(c.label)}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(r => `<tr>${r.map((cell, i) =>
    `<td${cols[i] && cols[i].num ? ' class=num' : ''}>${cell}</td>`).join('')}</tr>`).join('')}
  ${foot ? `<tr class=foot>${foot.map((cell, i) =>
    `<td${cols[i] && cols[i].num ? ' class=num' : ''}>${cell}</td>`).join('')}</tr>` : ''}
  </tbody></table>`;

const EmptyState = (msg, sub) => `<div class=c-empty>
  <div>${esc(msg)}</div>${sub ? `<span>${esc(sub)}</span>` : ''}</div>`;

const LoadingState = (msg) =>
  `<div class=c-empty><span class=c-spin></span>${esc(msg || '')}</div>`;

/* The run is the most interesting thing this product does and it used to be a
   spinner and one word for up to eight seconds, which reads as a hung page.
   Nothing here is invented: the batch size is what was asked for, and the timer
   is a real stopwatch on a real operation. There is no fake progress bar,
   because the engine returns once and there is no intermediate state to honestly
   report. */
const RunningState = (n) => `<div class="c-empty c-run">
  <span class=c-spin></span>
  <b class=c-run-h>Reconciling ${esc(String(n))} settlements</b>
  <span class=c-run-t data-run-timer>0.0s</span>
  <span class=c-run-n>Every candidate explanation is enumerated and checked
    before anything is written. Nothing is posted on a guess.</span>
</div>`;

const ErrorState = (msg) => `<div class="c-empty err">${esc(msg)}</div>`;

/* ------------------------------------------------------------- state spine
 *
 * Not a progress bar. A statement about where value is standing and what is
 * holding it there — the same five stages for a portfolio and for one
 * settlement, because it is the same pipeline and only the population differs.
 */
/* §22.10. Which instrument owns each stage of the chain.
 *
 * The spine states the whole model and was five inert divs — the one part of
 * the product that says where money stops and could not be touched. A stage
 * click is a LENS change: already addressable, already in the URL, already
 * reversible with Back. No new state and no new screen.
 *
 * VERIFICATION is the only stage whose owner depends on the case. With a
 * unique proof the question is "can it be proved" and that is Evidence; with
 * several explanations surviving it is "what would separate them", which is
 * the question Investigate exists to answer. Derived, not authored. */
const STAGE_OWNER = {
  source: 'evidence', matching: 'evidence',
  policy: 'policy', action: 'journal',
};
const ownerOf = (stage) => stage.key === 'verification'
  ? (String(stage.value).toUpperCase() === 'AMBIGUOUS'
      ? 'investigate' : 'evidence')
  : STAGE_OWNER[stage.key] || 'control';

/* And the other direction: the segment each room is talking about, marked on
   the spine the shell already draws rather than by drawing a second one. */
const LENS_SEGMENT = {
  evidence: ['matching', 'verification'],
  investigate: ['verification'],
  policy: ['verification', 'policy'],
  journal: ['policy', 'action'],
};

function StateSpine(spine, opts = {}) {
  if (!spine || !spine.stages) return '';
  const per = spine.type === 'portfolio';
  const lit = LENS_SEGMENT[opts.lens] || [];

  // Proportional to what CONTINUES past each stage. The bar collapsing from
  // full width to a sliver is the entire story of the portfolio, and it should
  // be legible before any number is read. Five equal cards with ticks made the
  // reader do that comparison themselves, which is a stepper wearing a
  // financial diagram's clothes.
  const vals = spine.stages.map(s => s.continues_paise);
  const known = vals.every(v => typeof v === 'number');
  const top = known ? Math.max(...vals, 1) : 1;
  const MIN = 0.6;   // a surviving sliver must stay visible or it reads as zero

  return `<div class="c-flow${per ? ' portfolio' : ''}${opts.rail ? ' rail' : ''}"
    role="img" aria-label="Money flow${spine.stopped_at
      ? `, stopped at ${esc(spine.stopped_at)}` : ''}">
    ${spine.stages.map((s, i) => {
      const w = known
        ? Math.max(s.continues_paise / top * 100, s.continues_paise > 0 ? MIN : 0)
        : (s.state === 'not_reached' ? 0 : 100);
      const held = per && s.held;
      // The value is stated where the money CHANGES. Four of five stages
      // repeated the figure above them — source and matching both read
      // ₹53,02,701.96, policy and action both read ₹353.73 — so the column
      // was mostly the same number written twice, in a rail that then had no
      // room left for the next action. The bar carries magnitude at every
      // stage; the figure marks each collapse.
      const same = opts.rail && i > 0
        && spine.stages[i - 1].value === s.value;
      const owner = ownerOf(s);
      const on = lit.includes(s.key);
      return `<${opts.rail ? 'button' : 'div'} class="c-flow-r ${esc(s.state)}${
        on ? ' lit' : ''}"${opts.rail ? ` data-stage="${esc(s.key)}"
        data-lens="${esc(owner)}" title="${esc(s.label)} — open ${esc(owner)}"` : ''}>
        <span class=c-flow-n>${esc(s.label)}</span>
        <span class=c-flow-track>
          <i class=c-flow-bar style="width:${w.toFixed(2)}%"></i>
        </span>
        <span class=c-flow-v>${same ? '' : esc(s.value)}</span>
        <span class=c-flow-x>${held
          ? `<b class=c-flow-h>${esc(s.held_value || '')}</b> held · ${Number(s.held).toLocaleString()}`
          : s.state === 'stopped' ? `<b>stopped here</b>`
          : s.state === 'not_reached' ? 'not reached' : ''}</span>
      </${opts.rail ? 'button' : 'div'}>
      ${(held || s.state === 'stopped') && opts.detail !== false
        ? `<div class=c-flow-d>${esc(s.detail)}</div>` : ''}`;
    }).join('')}
  </div>`;
}

/* --------------------------------------------------------- context chrome
 *
 * The shell owns this, not the lenses. §18: the context system stays generic,
 * so there is no DrawerSettlement and no DrawerExplanation — a lens supplies a
 * title, a kind and a body, and every drawer in the product is then the same
 * drawer. Each lens hand-writing its own header was three copies of a close
 * button waiting to drift.
 *
 * The breadcrumb is the point. §6 asks that the UI never suggest the context
 * REPLACED the subject, and the only reliable way to say that is to show the
 * chain it hangs off.
 */
function ContextChrome({ subject, lens, kind, title, status, promote }) {
  return `<div class=c-crumb data-crumb>
      <span class=c-crumb-s>${esc(subject.id === 'portfolio'
        ? 'Portfolio' : subject.id)}</span>
      <i>›</i><span class=c-crumb-l>${esc(lens)}</span>
      <i>›</i><span class=c-crumb-c>${esc(kind)}</span>
    </div>
    <div class=c-ctx-h>
      <b>${esc(title)}</b>
      ${status ? Status(status, { sm: true }) : ''}
      <span class=c-ctx-x>
        ${promote ? `<button class="c-ctx-b go"
          data-subject="${esc(promote.type)}:${esc(promote.id)}"
          title="Make this the subject — zoom in">Open ↗</button>` : ''}
        <button class=c-ctx-b data-close-ctx aria-label="Close" title="Close (Esc)">✕</button>
      </span>
    </div>`;
}

/* -------------------------------------------------- subject header (stateful)
 *
 * ONE header for portfolio, settlement, action and source. It PATCHES rather
 * than re-rendering, so that switching lens leaves it visually untouched —
 * which is the difference between an instrument and a page load.
 */
/* One composed identity, not four fields in a row.
 *
 * A case is its name, its state, its money and where that money currently
 * stands. The old header set those side by side at the same weight and the
 * amount — the financial subject of the whole screen — read as a field in a
 * record at 13.5px. Here the amount is the largest thing on the page and the
 * state and stage hang off the identity, because they are properties OF the
 * case rather than neighbours of it.
 *
 * It is patched, never re-rendered. During a lens change the workspace turns
 * over and this must not blink: the case is what did not change.
 */
class SubjectHeader {
  constructor(host) {
    this.host = host;
    this.host.className = 'c-subject';
    this.host.innerHTML = `
      <div class=c-case>
        <div class=c-case-amt><span class=v></span><span class=k></span></div>
        <div class=c-case-id>
          <span class=st></span>
          <span class=lbl></span>
          <span class=sub></span>
        </div>
        <div class=c-case-meta></div>
        <div class="c-slot c-state" id=c-state></div>
        <div class="c-slot c-now" id=c-now></div>
        <div class="c-slot c-next" id=c-next></div>
      </div>`;
    this.q = sel => this.host.querySelector(sel);
  }

  update(s) {
    if (!s || s.error) return;
    this.rec = s;
    const set = (sel, text) => {
      const n = this.q(sel);
      const t = text ?? '';
      if (n.textContent !== t) n.textContent = t;   // patch, never replace
      n.hidden = !t;
    };
    set('.lbl', s.type === 'portfolio' ? s.label : s.id);
    set('.sub', s.type === 'portfolio' ? s.sublabel : (s.amount_label || ''));
    const st = this.q('.st');
    st.className = s.status ? `st c-status s-${s.status}` : 'st c-status';
    st.textContent = s.status || '';
    st.hidden = !s.status;
    const amt = this.q('.c-case-amt');
    amt.hidden = s.amount_paise === null || s.amount_paise === undefined;
    set('.c-case-amt .v', rupees(s.amount_paise));
    set('.c-case-amt .k', s.type === 'portfolio' ? (s.amount_label || '') : '');
    /* §14. The rail is financial state, and its first viewport on a phone is
       the most contested space in the product. `seed` is run provenance — it
       is stated in Evidence, which explains what the portfolio is, and in
       Trust, which owns what produced a result. It does not outrank the
       conclusion, so it does not sit above it. */
    const meta = (s.meta || [])
      .filter(m => m.k !== 'seed')
      .map(m => `<span><i>${esc(m.k)}</i>${esc(m.v)}</span>`).join('');
    const box = this.q('.c-case-meta');
    if (box.innerHTML !== meta) box.innerHTML = meta;
    this.host.dataset.type = s.type;
  }

  /* The financial state of the case, and what follows from it.
   *
   * Written from SUBJECT-level data only. A rail assembled from whichever lens
   * is open would be a summary of the instrument, and the product model is that
   * the case does not change when the room does — which is also asserted by
   * `test_changing_lens_leaves_the_subject_and_the_header_untouched`.
   */
  caseState(spine, kase, lens) {
    const put = (id, html) => {
      const n = this.q('#' + id);
      if (!n) return;
      if (n.innerHTML !== html) n.innerHTML = html;
      n.hidden = !html;
    };

    /* §31. The landing was carrying the portfolio's state twice — five bars
     * and four repeated figures in the rail, beside the room's full-width
     * collapse — and that duplication is most of why it read as two
     * dashboards side by side.
     *
     * The first fix was to drop the rail's copy on the landing. That was
     * wrong, and two contracts said so in the same run: dropping it for the
     * whole portfolio took "where did the money stop" off portfolio Trust and
     * Journal, and dropping it for portfolio×control alone made the RAIL
     * change when the LENS changed — which is the one thing the case object
     * must never do.
     *
     * So the rail keeps its chain on every screen, and the duplication is
     * answered where it actually lived: the weight. It is a tick column with
     * names now, not a bar chart with the money written four times. */
    put('c-state', spine ? StateSpine(spine, { rail: true, lens }) : '');

    /* §31.11 — the rail is the CASE FILE SPINE: who this is, how much, what
     * state it is in, and the chain it is standing in. Nothing else.
     *
     * It used to carry the agreed/disputed split and the next action as well,
     * and at 1024x768 the result was 633px of content in a 179px slot — all
     * five stages of the spine cut off, with a rule terminating in mid-air.
     * A judge does not scroll a rail; they read a truncated case file and move
     * on. Both blocks are already stated by the rooms that own them: Evidence
     * states what the explanations agree on, and the blocker register states
     * what would unblock the work. The rail stopped repeating them.
     */
    put('c-now', '');
    put('c-next', '');
  }
}

/* ---------------------------------------------------- lens strip (stateful)
 *
 * Also patches. Switching SUBJECT must leave this visually untouched, because
 * the question the user is asking has not changed — only the thing they are
 * asking it about.
 */
class LensStrip {
  constructor(host, onPick) {
    this.host = host;
    this.host.className = 'c-lenses';
    this.host.setAttribute('role', 'tablist');
    this.keys = null;
    host.addEventListener('click', e => {
      const b = e.target.closest('[data-lens]');
      if (b) onPick(b.dataset.lens);
    });
    host.addEventListener('keydown', e => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const bs = [...host.querySelectorAll('[data-lens]')];
      const i = bs.findIndex(b => b.getAttribute('aria-selected') === 'true');
      const n = bs[i + (e.key === 'ArrowRight' ? 1 : -1)];
      if (n) { e.preventDefault(); n.focus(); onPick(n.dataset.lens); }
    });
  }

  update(lenses, active) {
    const keys = lenses.map(l => `${l.key}:${l.state || ''}`).join(',');
    if (keys !== this.keys) {
      this.keys = keys;
      /* §29.5. Index, name, question, and what the instrument currently
         answers. The ordinal encodes the product loop, so reading the dock top
         to bottom teaches the order an operator moves through; the state makes
         it a summary of this case rather than a list of places. An instrument
         with nothing to say yet renders no state line — a placeholder would be
         the dock inventing an answer the engine has not reached. */
      this.host.innerHTML = lenses.map((l, i) =>
        `<button data-lens="${esc(l.key)}" role=tab title="${esc(l.question)}"
           aria-selected=false><span class=c-lens-i aria-hidden=true>${
             String(i + 1).padStart(2, '0')}</span><span class=c-lens-n>${
             esc(l.label)}</span>
           <span class=c-lens-q>${esc(l.question)}</span>${
             l.state ? `<span class=c-lens-s>${esc(l.state)}</span>` : ''
           }</button>`).join('');
    }
    // The sliding ink indicator went with the horizontal tab band it belonged
    // to. Absolutely positioned inside what is now a two-column grid in the
    // rail, it stretched to 136x888 and painted over the case. The active
    // instrument is carried by weight and ground instead — and the ROOM is
    // what should be telling you which instrument you are holding.
    let held = null;
    this.host.querySelectorAll('[data-lens]').forEach(b => {
      const on = b.dataset.lens === active;
      b.setAttribute('aria-selected', String(on));
      b.classList.toggle('on', on);
      if (on) held = b;
    });

    /* §31 — on a phone the dock is one horizontal line, so the instrument you
       are holding can be scrolled off the edge of it. Bring it back. Only when
       the strip actually scrolls: on a desktop rail this is a no-op, and
       calling scrollIntoView there would move the page. */
    if (held && this.host.scrollWidth > this.host.clientWidth + 1) {
      const r = held.getBoundingClientRect();
      const h = this.host.getBoundingClientRect();
      if (r.left < h.left || r.right > h.right) {
        this.host.scrollTo({
          left: held.offsetLeft - (h.width - r.width) / 2,
          behavior: matchMedia('(prefers-reduced-motion: reduce)').matches
                    ? 'auto' : 'smooth' });
      }
    }
  }
}

/* THE BLOCKER A CASE CAME FROM.
 *
 * Compact and contextual, never another header. An operator who walked a
 * systemic blocker into one of its 197 settlements should still be able to
 * see WHY this case is on screen, three instruments later — and the rail
 * cannot say it, because the rail is the case, and the blocker is not.
 */
function FromBlocker(from) {
  if (!from || !from.reason) return '';
  return `<div class=c-from>
    <span>${esc(from.scope || 'blocker')}</span>
    <b>${esc(from.what || from.reason)}</b>
    <span class=c-from-x>→</span>
    <span class=v>${esc(from.value || '')}</span>
    <span>${esc(from.affected || '')}</span>
    <button class=c-from-b data-subject="portfolio:portfolio"
      data-lens=control data-context="action:${esc(from.reason)}"
      >back to the work</button>
  </div>`;
}

/* THE ROOM'S ANSWER.
 *
 * Every lens asks one question, and the autopsy found that on six of seven the
 * answer was not among the three strongest things on screen — on Policy the
 * word REVIEW lost to the application's own name. This is the instrument's
 * conclusion, and it is the first and largest thing in the room.
 *
 * `fact` is the verdict in the lens's own vocabulary. `figure` is the money it
 * turns on, when there is one. `because` is one sentence of why — prose is
 * allowed to say WHY, never WHAT.
 */
/* `second` is one subordinate figure, for a room whose answer is a RELATION
   between two amounts — what is unresolved against what is already settled.
   It is deliberately a single optional pair and not a list: a conclusion with
   three figures is a metric row wearing a conclusion's clothes, and the room
   would then have no headline at all. */
function Conclusion({ fact, figure, figureLabel, because, tone, second }) {
  return `<div class="c-concl${tone ? ` t-${esc(tone)}` : ''}">
    <div class=c-concl-f>${esc(fact)}</div>
    ${figure ? `<div class=c-concl-n><b>${esc(figure)}</b>${
      figureLabel ? `<em>${esc(figureLabel)}</em>` : ''}</div>` : ''}
    ${second ? `<div class=c-concl-2><b>${esc(second.value)}</b>${
      second.label ? `<em>${esc(second.label)}</em>` : ''}</div>` : ''}
    ${because ? `<p class=c-concl-w>${esc(because)}</p>` : ''}
  </div>`;
}


/* ── §58 THE DECISION RECORD ──────────────────────────────────────────────
 *
 * The primary object of this product. Not a portfolio and not a lens: one
 * financial event, and the four parties to the decision about it, in order of
 * authority.
 *
 *     ADVISOR   proposes   may name records · may not name amounts · may not act
 *     VERIFIER  proves     recomputes from source · never reads the proposal
 *     POLICY    permits    prices measured error against what a review costs
 *     LEDGER    records    takes nothing the verifier has not re-derived
 *
 * It lives here rather than in a lens because it is what a settlement IS.
 * Every lens is a deeper cut of one of these four rows, and a reader who
 * opens any of them should already have met the record they belong to.
 *
 * Two rules are drawn rather than captioned, because a caption has to be read:
 * the advisory row is the only one in outline (filled means this party can
 * change financial state), and every row states what it MAY and MAY NOT do in
 * the same place, so the boundary is a property of the row.
 */
function DecisionRecord(d, opts) {
  const o = opts || {};
  if (!d || d.error || !(d.stages || []).length) return '';
  const acted = !!d.acted;
  const ev = d.event || {}, out = d.outcome || {};

  const may = s => `<span class=dr-may>
    <span class=y><i>may</i><span>${esc(s.may || '')}</span></span>
    <span class=n><i>may not</i><span>${esc(s.may_not || '')}</span></span></span>`;

  const body = {
    advisor(s) {
      const a = s.advisor || {}, tr = a.track_record || {};
      if (!a.proposed) return `<p>${esc(a.detail || '')}</p>` + may(s);
      return `<p>${esc(a.reasoning || '')}</p>
        <span class=dr-ids>${(a.orders || []).map(esc).join(' · ')}</span>
        <p>Never shown an amount — identifiers, names and dates only.${
          tr.resolved ? ` Held out, it answered ${tr.resolved} of ${tr.ambiguous}
          ambiguous cases and was right on ${tr.correct}.` : ''}</p>${may(s)}`;
    },
    verifier(s) {
      const cuts = (s.reductions || []).filter(r => r.removed > 0);
      const n = s.narrowing || {};
      return `<p>${esc(s.detail || '')}</p>
        ${s.narrowing_line ? `<span class=dr-nar>${
          Number(n.universe || 0).toLocaleString()} <u>records</u> → ${
          n.candidates} <u>candidates</u> → ${n.explanations} <u>explanation${
          n.explanations === 1 ? '' : 's'}</u></span>` : ''}
        ${cuts.length ? `<span class=dr-cut>${cuts.map(r => `
          <span class=rm>−${Number(r.removed).toLocaleString()}</span>
          <span>${esc(r.name)}</span>
          <span class="k ${r.deterministic ? 'd' : 'c'}">${
            r.deterministic ? 'fact' : 'convention'}</span>`).join('')}</span>` : ''}
        ${s.residual_paise != null ? `<p>Residual <b>${s.residual_paise}
          ${s.residual_paise === 1 ? 'paisa' : 'paise'}</b> against a bound of
          ±${s.tolerance_paise}.</p>` : ''}
        ${(s.agreed_orders && s.contested_orders) ? `<p><b>${
          rupees(s.agreed_paise)}</b> across ${s.agreed_orders} orders is settled
          whichever explanation is right; <b>${rupees(s.contested_paise)}</b>
          across ${s.contested_orders} is the argument.</p>` : ''}
        <p>${esc(s.mechanisms || '')} — <b>without reading what the advisor
          proposed</b>.</p>
        ${s.advisor_outcome ? `<p>Tested the advisor's proposal:
          <b>${esc(s.advisor_outcome)}</b>.</p>` : ''}${may(s)}`;
    },
    policy(s) {
      return `<p>${esc(s.detail || '')}</p>${s.p_error != null
        ? `<p>Priced at the measured error rate for this class of result, at its
           95% upper bound — <b>${Number(s.p_error).toFixed(4)}</b>.</p>` : ''}${may(s)}`;
    },
    ledger(s) {
      if (!(s.lines || []).length) return `<p>${esc(s.detail || '')}</p>` + may(s);
      return `<span class=dr-je>${s.lines.map(l => `
        <span>${esc(l.account)}</span><span class=amt>${
          l.debit_paise ? 'Dr ' : 'Cr '}${rupees(l.debit_paise || l.credit_paise)}</span>`
        ).join('')}</span><p>Balanced to the paisa.</p>${may(s)}`;
    },
  };

  const cls = s => s.key === 'advisor' ? 'adv'
    : (s.key === 'ledger' || s.key === 'policy') ? (acted ? 'acts' : 'holds') : '';

  return `<figure class="dr${o.compact ? ' compact' : ''}">
    <div class=dr-e>
      <div><span class=dr-ek>${esc(o.label || 'financial event')}</span>
        <div class=dr-ev>${rupees(ev.amount_paise || d.amount_paise)}</div>
        <p class=dr-eq><b>${esc(ev.question || '')}</b> ${esc(ev.unknown || '')}</p></div>
      <div class=dr-em>${esc(d.settlement_id)}<br>UTR ${esc(d.utr || '—')}<br>${
        esc(ev.value_date || '')}</div>
    </div>
    ${d.stages.map(s => `
      <div class="dr-r ${cls(s)}">
        <span class=dr-a><b>${esc(s.actor)}</b><em>${esc(s.verb)}</em></span>
        <span class=dr-n><i class=dr-dot></i></span>
        <span class=dr-b>
          <b class=dr-h>${esc(s.headline)}${s.badge
            ? `<span class=dr-badge>${esc(s.badge)}</span>` : ''}</b>
          ${(body[s.key] || (t => `<p>${esc(t.detail || '')}</p>`))(s)}
        </span>
      </div>`).join('')}
    <div class="dr-out ${acted ? 'go' : 'stop'}">
      <div><div class=dr-oh>${esc(out.headline || '')}</div>
        <p class=dr-oc>${esc(out.consequence || '')}</p></div>
      <span class=dr-ov>${acted ? 'action' : 'no financial action'}</span>
    </div>
  </figure>`;
}

/* Exported because a lens uses it. Amount and Panel were declared here and
   called by nothing, so they are gone — a component with no caller is a
   guess about the future, and it will be the wrong guess. */
window.C = {
  esc, rupees, plural, Conclusion, FromBlocker, DecisionRecord,
  Status, Metric, MetricRow, Disclosure, Section, Row, ContextChrome,
  DataTable, EmptyState, LoadingState, RunningState, ErrorState, StateSpine, ownerOf,
  SubjectHeader, LensStrip,
};
