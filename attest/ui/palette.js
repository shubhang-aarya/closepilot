/* Command palette — CASE NAVIGATION.
 *
 * Not application search and not a chat box. The three axes this product has
 * are subject, lens and context, so those are what it navigates: a settlement
 * by id, a lens by name, and the actions the run has actually proposed. It
 * proposes nothing it cannot do.
 *
 * The whole journey has to be possible without a mouse (§9.4.18), and the
 * palette is the part that makes that true — reaching a settlement otherwise
 * means tabbing through a queue of 250.
 */
'use strict';

(() => {
  const esc = window.C && window.C.esc ? window.C.esc : (s => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'));

  let root, input, list, items = [], active = 0, open = false, lastFocus = null;

  function build() {
    root = document.createElement('div');
    root.className = 'c-pal';
    root.hidden = true;
    root.innerHTML = `
      <div class=c-pal-box role=dialog aria-modal=true aria-label="Go to">
        <input class=c-pal-q type=text autocomplete=off spellcheck=false
               placeholder="settlement, lens or action" aria-label="Go to"
               role=combobox aria-expanded=true aria-controls=c-pal-list>
        <ul class=c-pal-list id=c-pal-list role=listbox></ul>
        <div class=c-pal-foot>
          <span><kbd>↑</kbd><kbd>↓</kbd> move</span>
          <span><kbd>↵</kbd> go</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>`;
    document.body.appendChild(root);
    input = root.querySelector('.c-pal-q');
    list = root.querySelector('.c-pal-list');

    input.addEventListener('input', () => { active = 0; refresh(); });
    input.addEventListener('keydown', onKey);
    root.addEventListener('mousedown', e => { if (e.target === root) close(); });
    list.addEventListener('click', e => {
      const li = e.target.closest('[data-i]');
      if (li) run(items[+li.dataset.i]);
    });
  }

  /* Everything the palette can reach, built from what the run holds. */
  function candidates() {
    const S = window.SHELL;
    const out = [];
    (S.lenses || []).forEach(l => out.push({
      group: 'Lens', label: l.label, hint: l.question,
      go: () => window.navigate({ lens: l.key }),
    }));
    out.push({
      group: 'Subject', label: 'Financial control', hint: 'the whole portfolio',
      go: () => window.navigate({ subject: { type: 'portfolio', id: 'portfolio' } }),
    });
    (window.PALETTE_ROWS || []).forEach(r => out.push({
      group: 'Settlement', label: r.id, hint: r.hint,
      go: () => window.navigate({ subject: { type: 'settlement', id: r.id } }),
    }));
    return out;
  }

  /* Subsequence match, so "s89" finds setl_000089 and "wh" finds "What is
   * happening?". Scored so a prefix beats a scatter. */
  function score(hay, needle) {
    if (!needle) return 0;
    const h = hay.toLowerCase(), n = needle.toLowerCase();
    if (h.startsWith(n)) return 1000 - h.length;
    const idx = h.indexOf(n);
    if (idx >= 0) return 500 - idx;
    let i = 0, gaps = 0, last = -1;
    for (const c of n) {
      const at = h.indexOf(c, i);
      if (at < 0) return -1;
      if (last >= 0) gaps += at - last - 1;
      last = at; i = at + 1;
    }
    return 200 - gaps;
  }

  function refresh() {
    const q = input.value.trim();
    items = candidates()
      .map(c => ({ ...c, s: Math.max(score(c.label, q), score(c.hint || '', q) - 60) }))
      .filter(c => !q || c.s >= 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 14);
    if (active >= items.length) active = Math.max(0, items.length - 1);
    list.innerHTML = items.length ? items.map((c, i) => `
      <li class="c-pal-i${i === active ? ' on' : ''}" data-i="${i}" role=option
          aria-selected="${i === active}" id="c-pal-o${i}">
        <span class=c-pal-g>${esc(c.group)}</span>
        <span class=c-pal-l>${esc(c.label)}</span>
        <span class=c-pal-h>${esc(c.hint || '')}</span>
      </li>`).join('')
      : `<li class=c-pal-none>Nothing matches “${esc(q)}”. The palette reaches
         subjects, lenses and this run's settlements — it does not search text.</li>`;
    input.setAttribute('aria-activedescendant', items.length ? `c-pal-o${active}` : '');
    const on = list.querySelector('.on');
    if (on) on.scrollIntoView({ block: 'nearest' });
  }

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!items.length) return;
      active = (active + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length;
      refresh();
      return;
    }
    if (e.key === 'Enter') { e.preventDefault(); run(items[active]); }
  }

  function run(item) {
    if (!item) return;
    close();
    item.go();
  }

  function show() {
    if (!root) build();
    lastFocus = document.activeElement;
    open = true;
    root.hidden = false;
    input.value = '';
    active = 0;
    refresh();
    input.focus();
  }

  function close() {
    if (!open) return;
    open = false;
    root.hidden = true;
    // Focus goes back where it came from. Losing it to <body> after a palette
    // closes is how a keyboard journey ends — so when there was nowhere to
    // return to, it lands on the active lens, which is a real place to be
    // rather than the document.
    if (lastFocus && lastFocus !== document.body && document.contains(lastFocus)) {
      lastFocus.focus();
      return;
    }
    const here = document.querySelector('#lenses [aria-selected=true]')
              || document.querySelector('#lenses [data-lens]');
    if (here) here.focus();
  }

  document.addEventListener('keydown', e => {
    const k = e.key.toLowerCase();
    if ((e.metaKey || e.ctrlKey) && k === 'k') { e.preventDefault(); open ? close() : show(); }
  });

  window.PALETTE = { show, close, isOpen: () => open };
})();
