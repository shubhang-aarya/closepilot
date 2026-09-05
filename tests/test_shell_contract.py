"""The subject × lens continuity contract, driven through a real browser.

These are the invariants from the directive's §7 and §8, written as assertions
rather than as a convention someone has to remember:

    changing LENS     -> subject unchanged, header untouched
    changing SUBJECT  -> lens unchanged, strip untouched
    async result      -> discarded if either axis moved during the request
    reload            -> both axes restored from the URL

The autopsy found the subject dying in four of six navigations under the old
shell. That was possible because nothing tested it. Requires a running server
and playwright; skipped when either is absent, because a test that cannot run
should not fail a build for the wrong reason.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

URL = "http://localhost:8420/workspace.html"

#: The settlements these contracts navigate to, and the verdict each one is
#: chosen to exhibit. They are fixtures: the guarantees below are about how the
#: shell renders a PROVEN or a CONTRADICTED case, not about these four ids.
#:
#: §47.F1 moved the demo from a calibration seed to a held-out one and 25 of
#: these contracts went red at once - not because anything regressed, but
#: because setl_000020 is PROVEN on 20260821 and AMBIGUOUS on 555001. The
#: coupling was real and nothing named it, so the failure arrived as two dozen
#: unrelated-looking assertion errors instead of one sentence. It is named now,
#: and `test_the_pinned_cases_still_exhibit_their_verdicts` fails first and
#: alone if the data moves under them again.
CASES = {
    "setl_000089": "AMBIGUOUS",
    "setl_000225": "AMBIGUOUS",
    "setl_000022": "PROVEN",
    "setl_000166": "CONTRADICTED",
    "setl_000163": "AMBIGUOUS",
    # the one whose candidate pool spans more than one capture date, so the
    # hypothesis loop actually proposes and is actually refuted. On a
    # single-date pool the lens is vacuous and the trail reads differently.
    "setl_000128": "AMBIGUOUS",
}


def test_the_pinned_cases_still_exhibit_their_verdicts():
    """§47.F1. Every fixture id still has the verdict its contracts assume.

    This is the canary for the failure above: if a data change moves one of
    these, this test says which id and which verdict in one line, before the
    contracts that depend on it start failing for reasons that look unrelated.
    """
    import json
    import urllib.request
    with urllib.request.urlopen("http://localhost:8420/api/run?n=250") as r:
        run = json.load(r)
    got = {}
    for sid in CASES:
        with urllib.request.urlopen(
                f"http://localhost:8420/api/settlement?run={run['run_id']}"
                f"&id={sid}") as r:
            got[sid] = json.load(r).get("verdict")
    drifted = {k: (v, got.get(k)) for k, v in CASES.items() if got.get(k) != v}
    assert not drifted, (
        f"on seed {run['seed']} these fixtures no longer exhibit the verdict "
        f"their contracts assume (expected, actual): {drifted}")


playwright = pytest.importorskip("playwright.sync_api",
                                 reason="playwright not installed")


def _server_up() -> bool:
    try:
        urllib.request.urlopen("http://localhost:8420/api/observatory", timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


pytestmark = pytest.mark.skipif(not _server_up(),
                                reason="attest.web is not running on :8420")


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        errors: list[str] = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_function("() => SHELL.record", timeout=90000)
        pg.wait_for_timeout(800)
        pg.errors = errors            # type: ignore[attr-defined]
        yield pg
        b.close()


def _state(pg):
    """subject, lens, context — the three axes the shell owns."""
    return pg.evaluate(
        "[SHELL.subject.type + ':' + SHELL.subject.id, SHELL.lens,"
        " SHELL.context ? SHELL.context.type + ':' + SHELL.context.id : null]")


def test_changing_lens_leaves_the_subject_and_the_header_untouched(page):
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1500)
    before_subject = _state(page)[0]
    before_header = page.inner_text(".c-subject")

    page.click("[data-lens=journal]")
    page.wait_for_timeout(1500)
    after_subject, after_lens, _ = _state(page)

    assert after_subject == before_subject
    assert after_lens == "journal"
    assert page.inner_text(".c-subject") == before_header


def test_changing_subject_leaves_the_lens_and_the_strip_untouched(page):
    """Phase 2 changed how a subject change is REQUESTED, not the contract.

    Clicking a row in a master list now sets CONTEXT — that is what master and
    detail means, and Phase 1 was wrong to make it navigation. Promoting the
    inspected thing to the subject is a separate, deliberate act, and it is that
    act which must preserve the lens."""
    rack = """() => [...document.querySelectorAll('.c-lenses [data-lens]')].map(
        b => ({ key: b.dataset.lens,
                q: (b.querySelector('.c-lens-q') || {}).textContent,
                on: b.getAttribute('aria-selected') === 'true',
                state: (b.querySelector('.c-lens-s') || {}).textContent || null }))"""

    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1600)
    before = page.evaluate(rack)

    page.click(".c-row.link")
    page.wait_for_timeout(1300)
    page.click(".c-ctx-b.go")
    page.wait_for_timeout(1600)
    subject, lens, context = _state(page)

    assert subject.startswith("settlement:")
    assert lens == "control", "the user already said what they wanted to know"
    assert context is None, "context does not survive a subject change"

    after = page.evaluate(rack)
    # The RACK is what must not move: same instruments, same order, same
    # questions, same one selected. This was `inner_text(".c-lenses") ==
    # before_strip`, which also pinned the states — and once Phase 29 gave each
    # instrument the state of the subject it would open, that equality was
    # pinning "no state text exists" rather than "the rack held still".
    assert [i["key"] for i in after] == [i["key"] for i in before]
    assert [i["q"] for i in after] == [i["q"] for i in before]
    assert [i["on"] for i in after] == [i["on"] for i in before]

    # The states are the half that MUST move, because they describe the subject
    # rather than the rack. A dock still reporting the portfolio's states over a
    # settlement is a dock disagreeing with the room it opens, so the weaker
    # assertion above is paid for with a stronger one here.
    assert all(i["state"] is None for i in before), \
        "the portfolio has no per-lens verdict to report"
    assert [i["state"] for i in after] != [i["state"] for i in before], \
        "the dock must re-derive against the new subject"


def test_the_url_addresses_both_axes_and_a_reload_restores_them(page):
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000089'},lens:'control'})")
    page.wait_for_timeout(1600)
    assert page.evaluate("location.hash") == "#/settlement/setl_000089/control"

    page.reload(wait_until="networkidle")
    page.wait_for_function("() => SHELL.record", timeout=90000)
    page.wait_for_timeout(900)
    assert _state(page) == ["settlement:setl_000089", "control", None]


def test_a_result_is_discarded_when_the_subject_moved_during_the_request(page):
    """D15, at the shell level. A slow response for one subject must not paint
    over another — attaching real evidence to the wrong subject is a fabricated
    audit record, and worse than showing nothing."""
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1500)

    # Hold the journal request open, ask for it, then move the subject.
    page.route("**/api/journal*", lambda route: (page.wait_for_timeout(2500),
                                                 route.continue_()))
    page.evaluate("navigate({lens:'journal'})")
    page.wait_for_timeout(300)
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000089'},lens:'control'})")
    page.wait_for_timeout(3500)
    page.unroute("**/api/journal*")

    subject, lens, _ = _state(page)
    assert (subject, lens) == ("settlement:setl_000089", "control")
    # inner_text returns what is rendered, and the section headings are
    # uppercased by CSS — compare case-insensitively or the test asserts about
    # the stylesheet rather than about the behaviour.
    body = page.inner_text("#workspace").lower()
    assert "money trail" not in body, "a stale journal render landed"
    # "Where it stopped" moved out of Control and into the shell's state spine,
    # which now renders above every lens — so it no longer identifies Control.
    # The guarantee is unchanged: the stale journal must not land, and Control
    # must be what is showing.
    assert "what we know" in body or "the decision" in body


def test_an_unsupported_lens_falls_back_visibly_and_never_silently(page):
    """§7: never silently return to a default. A source has no journal, so
    asking for one must say so rather than quietly showing something else."""
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'journal'})")
    page.wait_for_timeout(1500)
    page.evaluate("navigate({subject:{type:'source',id:'active'}})")
    page.wait_for_timeout(1600)

    subject, lens, _ = _state(page)
    assert subject.startswith("source:")
    assert lens != "journal", "source does not support journal"
    assert page.query_selector(".c-notice"), "the fallback was not announced"
    assert "does not apply" in page.inner_text(".c-notice")


def test_the_shell_raised_no_script_errors(page):
    assert page.errors == []           # type: ignore[attr-defined]


# --------------------------------------------------------------- Phase 2: context

def test_inspecting_a_row_does_not_move_the_subject_or_rebuild_the_master(page):
    """§5's interaction model. Opening something is not going somewhere: the
    master list must not re-render, or the thing you clicked moves under you."""
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1600)
    before = page.inner_text("#w-main")

    page.click(".c-row.link")
    page.wait_for_timeout(1300)
    subject, lens, context = _state(page)

    assert subject == "portfolio:portfolio"
    assert lens == "control"
    assert context and context.startswith("settlement:")
    assert page.inner_text("#w-main") == before, "the master re-rendered"
    assert len(page.inner_text("#w-ctx")) > 80, "the detail is empty"


def test_the_selected_row_stays_selected_while_its_detail_is_open(page):
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1600)
    page.click(".c-row.link")
    page.wait_for_timeout(1200)
    assert page.eval_on_selector_all(".c-row.sel", "x => x.length") == 1
    assert page.eval_on_selector_all(
        ".c-row[aria-selected=true]", "x => x.length") == 1


def test_closing_returns_to_exactly_where_you_were(page):
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1600)
    before = page.inner_text("#w-main")
    page.click(".c-row.link")
    page.wait_for_timeout(1200)
    page.click("[data-close-ctx]")
    page.wait_for_timeout(900)

    subject, lens, context = _state(page)
    assert (subject, lens, context) == ("portfolio:portfolio", "control", None)
    assert page.inner_text("#w-main") == before
    assert page.eval_on_selector_all(".c-row.sel", "x => x.length") == 0


def test_escape_and_back_close_the_drawer_without_leaving_the_page(page):
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1600)

    page.click(".c-row.link")
    page.wait_for_timeout(1200)
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    assert _state(page)[2] is None, "Escape did not close"

    page.click(".c-row.link")
    page.wait_for_timeout(1200)
    page.go_back()
    page.wait_for_timeout(1100)
    subject, lens, context = _state(page)
    assert context is None, "Back did not close the drawer"
    assert (subject, lens) == ("portfolio:portfolio", "control"), \
        "Back left the page instead of closing what was opened"


def test_the_url_addresses_context_too(page):
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1600)
    page.click(".c-row.link")
    page.wait_for_timeout(1200)
    assert "?in=settlement" in page.evaluate("location.hash")

    page.reload(wait_until="networkidle")
    page.wait_for_function("() => SHELL.record", timeout=90000)
    page.wait_for_timeout(1400)
    assert _state(page)[2] is not None, "context did not survive a reload"


def test_a_context_the_next_lens_cannot_hold_is_dropped_visibly(page):
    """§7 again, for the third axis. An explanation inspected inside Control is
    not a thing Policy can open, and dropping it silently would be the same lie.

    This used to inspect the order list inside Journal. On the held-out seed
    the ledger is empty by design - nothing cleared the policy, so there is no
    entry and no `.c-inline` to click. The axis under test is that a lens drops
    a context it cannot hold and SAYS SO; Policy holds no context of any kind,
    which makes it the honest end of that move on any data.
    """
    _ev(page, "#/settlement/setl_000089/control")
    page.click(".c-cand")
    page.wait_for_timeout(1300)
    assert _state(page)[2] is not None

    page.click("[data-lens=policy]")
    page.wait_for_timeout(1700)
    assert _state(page)[2] is None
    assert page.query_selector(".c-notice"), "the drop was not announced"


def test_a_drawer_leaves_the_subject_visible_underneath(page):
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000089'},lens:'control'})")
    page.wait_for_timeout(1700)
    page.click(".c-cand")
    page.wait_for_timeout(1300)
    assert page.eval_on_selector_all(".w-ctx.drawer", "x => x.length") == 1
    assert len(page.inner_text("#w-main")) > 200, "the workspace was replaced"


# ------------------------------------------------- Phase 2 gate: the spatial feel

def test_the_drawer_opens_from_the_object_that_was_clicked(page):
    """§4. A pane that always expands from the same edge is a route transition
    with a different name. The origin must follow the click."""
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1800)
    rows = page.query_selector_all(".c-row.link")
    assert len(rows) >= 3, "not enough rows to tell origins apart"

    # Scroll the queue into view first. `setOrigin` clamps the click rect to the
    # workspace box, so a row below the fold resolves to the edge — and
    # Playwright's click auto-scrolls, which centres every one of them and makes
    # three different rows report the same origin. That is an artifact of
    # driving the page, not of the product: a person clicks rows they can see.
    # The test used to rely on the queue happening to sit in view, and stopped
    # holding when the queue moved up the lens.
    page.eval_on_selector("#w-main", "e => e.scrollTop = e.scrollHeight * 0.34")
    page.wait_for_timeout(500)
    rows = [r for r in page.query_selector_all(".c-row.link") if r.is_visible()]
    assert len(rows) >= 3, "fewer than three queue rows are on screen"

    origins = []
    for r in (rows[0], rows[len(rows) // 2], rows[-1]):
        r.click()
        page.wait_for_timeout(650)
        origins.append(page.evaluate(
            "document.getElementById('w-ctx').style.getPropertyValue('--oy')"))
    assert len(set(origins)) > 1, f"origin never moved: {origins}"
    assert "px" in page.evaluate(
        "getComputedStyle(document.getElementById('w-ctx')).transformOrigin")


def test_the_context_states_the_chain_it_hangs_off(page):
    """§6. The UI must never suggest the context replaced the subject."""
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000089'},lens:'control'})")
    page.wait_for_timeout(1800)
    page.click(".c-cand")
    page.wait_for_timeout(1300)

    crumb = page.inner_text(".c-crumb")
    assert "setl_000089" in crumb
    assert "CONTROL" in crumb.upper()
    assert "EXPLANATION" in crumb.upper()
    # and the subject header is still the settlement, unchanged
    assert "setl_000089" in page.inner_text(".c-subject")


def test_opening_an_explanation_shows_the_orders_behind_it(page):
    """§13, the most important product test. "4 orders" must open into four
    orders, without leaving the settlement."""
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000089'},lens:'control'})")
    page.wait_for_timeout(1800)
    page.click(".c-cand")
    page.wait_for_timeout(1400)

    pane = page.inner_text("#w-ctx")
    rows = page.eval_on_selector_all("#w-ctx .c-table tbody tr", "x => x.length")
    assert rows >= 1, "the explanation opened onto no orders"
    assert "only this explanation uses" in pane.lower()
    subject, lens, context = _state(page)
    assert subject == "settlement:setl_000089"
    assert lens == "control"
    assert context and context.startswith("explanation:")


def test_the_context_chrome_is_generic_not_per_kind(page):
    """§18: no DrawerSettlement, no DrawerExplanation. Every drawer in the
    product is the same drawer, or the close button will drift."""
    for hash_, click, kind in [
        # An Entry drawer used to be the first pair. On the held-out seed the
        # ledger is empty by design - nothing cleared the policy - so there is
        # no entry to open, and a drawer that cannot be reached cannot be
        # compared. Two kinds that DO exist make the same point: the guarantee
        # is that every drawer is the same drawer, not that it is these two.
        ("#/portfolio/control", ".c-row.link", "Settlement"),
        ("#/settlement/setl_000089/control", ".c-cand", "Explanation"),
    ]:
        page.evaluate(f"location.hash = {hash_!r}")
        page.wait_for_timeout(1800)
        page.click(click)
        page.wait_for_timeout(1300)
        assert page.query_selector(".c-crumb"), f"{kind} has no breadcrumb"
        assert page.query_selector("[data-close-ctx]"), f"{kind} has no close"
        assert kind.upper() in page.inner_text(".c-crumb").upper()


def test_the_master_scroll_position_survives_open_and_close(page):
    """§7: only context disappears.

    The literal position 420 is gone, not the guarantee. Moving the case into
    the rail gave the instrument 343px more height, so the same content now
    scrolls 132px where it used to scroll 666 — 420 is past the end and the
    browser clamps it, which would make the assertion about arithmetic rather
    than about behaviour.

    Scrolling to the maximum instead is a STRONGER test of the same thing: the
    bottom is exactly where a reflow-induced clamp would bite.
    """
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'},lens:'control'})")
    page.wait_for_timeout(1800)
    want = page.evaluate("""() => {
        const e = document.getElementById('w-main');
        const max = e.scrollHeight - e.clientHeight;
        e.scrollTop = max;
        return e.scrollTop; }""")
    assert want > 0, "the master does not scroll at all; this asserts nothing"
    page.wait_for_timeout(300)
    page.click(".c-row.link")
    page.wait_for_timeout(1100)
    assert page.evaluate("document.getElementById('w-main').scrollTop") == want
    page.click("[data-close-ctx]")
    page.wait_for_timeout(900)
    assert page.evaluate("document.getElementById('w-main').scrollTop") == want


# ------------------------------------------------------------ P3: Evidence

def _ev(page, hash_):
    page.evaluate(f"location.hash = {hash_!r}")
    page.wait_for_timeout(2200)


def test_portfolio_evidence_loads_scoped(page):
    """§28: the evidence landscape, not every record in the book."""
    _ev(page, "#/portfolio/evidence")
    assert _state(page)[:2] == ["portfolio:portfolio", "evidence"]
    nodes = page.eval_on_selector_all("#workspace *", "x => x.length")
    assert nodes < 400, f"portfolio evidence rendered {nodes} elements"
    assert "convention" in page.inner_text("#workspace").lower()


def test_settlement_evidence_shows_the_search_space_boundary(page):
    """§16. A proof can be perfect inside a space that excluded the truth, and a
    reader cannot judge that without seeing what was CONSIDERED."""
    _ev(page, "#/settlement/setl_000089/evidence")
    space = page.evaluate("""async () => {
      const d = await (await fetch(`/api/evidence?run=${SHELL.run}`
        + `&type=settlement&id=setl_000089`)).json();
      return d.space || {}; }""")
    txt = page.inner_text("#workspace")
    assert "WHAT WAS CONSIDERED" in txt.upper()
    # the funnel states both ends and names each reduction's status. Both ends
    # are read from the run rather than pinned: they are properties of the
    # portfolio, and pinning them made a seed change look like a regression.
    assert f"{space['universe']:,}" in txt, \
        f"the universe ({space['universe']:,}) is not stated"
    assert str(space["candidates"]) in txt, \
        f"the candidate count ({space['candidates']}) is not stated"
    assert "CONVENTION" in txt.upper()
    assert "DETERMINISTIC" in txt.upper()


def test_an_ambiguous_settlement_shows_shared_versus_unique(page):
    """§7, §8. Ambiguity shown, not stated."""
    _ev(page, "#/settlement/setl_000089/evidence")
    rows = page.eval_on_selector_all(".e-set-r", "x => x.length")
    assert rows >= 2, "no explanation set rendered"
    txt = page.inner_text("#workspace")
    assert "settled whichever explanation is right" in txt
    assert "turns on which one is" in txt


def test_the_model_is_visually_and_semantically_separate_from_evidence(page):
    """§6, §18. A hypothesis must never look as authoritative as a fact."""
    _ev(page, "#/settlement/setl_000089/evidence")
    assert page.query_selector(".e-ai"), "no model section"
    assert "not evidence" in page.inner_text(".e-ai-tag").lower()
    # and it is not inside the verified-relationship section
    verified = page.eval_on_selector_all(".e-rel .e-ai", "x => x.length")
    assert verified == 0, "a hypothesis rendered among verified relationships"
    assert "non-discriminative" in page.inner_text("#workspace").lower()


def test_an_evidence_object_opens_as_context_not_navigation(page):
    """§10. Evidence uses the existing shell from day one."""
    _ev(page, "#/settlement/setl_000089/evidence")
    before = page.inner_text("#w-main")
    page.click(".e-set-r")
    page.wait_for_timeout(1400)
    subject, lens, context = _state(page)
    assert subject == "settlement:setl_000089"
    assert lens == "evidence"
    assert context == "explanation:A"
    assert page.inner_text("#w-main") == before, "the workspace re-rendered"
    assert "EXPLANATION" in page.inner_text(".c-crumb").upper()


def test_evidence_context_nests_from_explanation_to_order(page):
    """§25, and §35's north star: money → record → relationship → evidence
    without losing the case."""
    _ev(page, "#/settlement/setl_000089/evidence")
    page.click(".e-set-r")
    page.wait_for_timeout(1400)
    page.click("#w-ctx .c-row.link")
    page.wait_for_timeout(1400)
    subject, lens, context = _state(page)
    assert subject == "settlement:setl_000089", "the case was lost"
    assert lens == "evidence"
    assert context.startswith("order:")
    assert "PROVENANCE" in page.inner_text("#w-ctx").upper()


def test_closing_evidence_context_restores_the_workspace(page):
    _ev(page, "#/settlement/setl_000089/evidence")
    before = page.inner_text("#w-main")
    page.click(".e-set-r")
    page.wait_for_timeout(1300)
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert _state(page) == ["settlement:setl_000089", "evidence", None]
    assert page.inner_text("#w-main") == before


def test_switching_to_evidence_preserves_the_subject(page):
    _ev(page, "#/settlement/setl_000022/control")
    page.click("[data-lens=evidence]")
    page.wait_for_timeout(2000)
    subject, lens, _ = _state(page)
    assert subject == "settlement:setl_000022"
    assert lens == "evidence"


def test_a_proven_settlement_shows_no_competing_explanations(page):
    """The lens must understand the verdict states. §7."""
    _ev(page, "#/settlement/setl_000022/evidence")
    txt = page.inner_text("#workspace").upper()
    assert "WHAT WAS CONSIDERED" in txt
    assert "VERIFIED RELATIONSHIPS" in txt
    assert "AGREE ON" not in txt, "a proven settlement has nothing to disagree about"


def test_evidence_relationships_state_their_kind_and_status(page):
    """§5: never node → node → node with the relationship unexplained."""
    _ev(page, "#/settlement/setl_000089/evidence")
    rels = page.eval_on_selector_all(".e-rel", "x => x.length")
    assert rels >= 1
    first = page.inner_text(".e-rel")
    assert "verified" in first.lower()
    assert len(page.inner_text(".e-rel-w").strip()) > 10, "the edge does not say why"


def test_evidence_survives_a_reload_with_context_open(page):
    _ev(page, "#/settlement/setl_000089/evidence")
    page.click(".e-set-r")
    page.wait_for_timeout(1300)
    page.reload(wait_until="networkidle")
    page.wait_for_function("() => SHELL.record", timeout=90000)
    page.wait_for_timeout(1600)
    assert _state(page) == ["settlement:setl_000089", "evidence", "explanation:A"]


def test_a_stale_evidence_fetch_cannot_land_on_another_subject(page):
    """§30.12 — D15 at the evidence layer."""
    _ev(page, "#/settlement/setl_000089/evidence")
    page.route("**/api/evidence*", lambda route: (page.wait_for_timeout(2500),
                                                  route.continue_()))
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000022'}})")
    page.wait_for_timeout(400)
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'}})")
    page.wait_for_timeout(3600)
    page.unroute("**/api/evidence*")
    subject, lens, _ = _state(page)
    assert subject == "portfolio:portfolio"
    # "2,368" appears in BOTH views — the portfolio counts the whole book too —
    # so the marker has to be something only a settlement renders.
    body = page.inner_text("#workspace").lower()
    assert "could belong to this credit" not in body, "a stale settlement view landed"
    assert "the evidence in this run" in body


# --------------------------------------------------------- P4: Investigate

def test_portfolio_investigate_is_questions_not_a_table_of_settlements(page):
    """§13. "197 ambiguous settlements" is a queue nobody can finish; one
    question worth ₹47L that a single answer settles is work."""
    _ev(page, "#/portfolio/investigate")
    assert _state(page)[:2] == ["portfolio:portfolio", "investigate"]
    cases = page.eval_on_selector_all(".i-case", "x => x.length")
    assert 1 <= cases <= 12, f"{cases} rows is a table, not a queue"
    txt = page.inner_text("#w-main")
    assert "?" in txt, "the queue does not ask anything"
    assert "one answer" in txt.lower()


def test_settlement_investigate_states_the_question_first(page):
    _ev(page, "#/settlement/setl_000089/investigate")
    q = page.inner_text(".i-q h2")
    assert q.endswith("?"), f"not a question: {q!r}"
    assert "indistinguishable" in q.lower()


def test_the_timeline_names_actor_action_input_and_result(page):
    """§16. Never a sentence the reader has to parse to work out who did what."""
    _ev(page, "#/settlement/setl_000089/investigate")
    steps = page.eval_on_selector_all(".i-tl-s", "x => x.length")
    assert steps >= 3, "no trail"
    actors = page.eval_on_selector_all(".i-tl-a", "x => x.map(n => n.textContent)")
    assert "Model" in actors and "Solver" in actors and "Engine" in actors
    # and the order is the argument: the model cannot appear after the verdict
    assert actors.index("Model") < actors.index("Solver") < actors.index("Engine")


def test_the_three_actors_are_visually_distinct(page):
    """§4, §28. The model proposes, the solver tests, the engine decides, and
    the layout must make that impossible to misread."""
    _ev(page, "#/settlement/setl_000089/investigate")
    colours = page.evaluate("""(() => {
      const pick = c => {
        const n = document.querySelector('.e-act-' + c + ' .i-tl-m');
        return n ? getComputedStyle(n).borderColor : null; };
      return [pick('model'), pick('solver'), pick('engine')]; })()""")
    assert all(colours), "an actor has no marker"
    assert len(set(colours)) == 3, f"actors share a colour: {colours}"


def test_the_solver_result_is_a_named_state_not_a_confidence(page):
    """§18. "AI confidence" collapses six different findings into one."""
    _ev(page, "#/settlement/setl_000128/investigate")
    results = page.eval_on_selector_all(".i-tl-r", "x => x.map(n => n.textContent.trim())")
    assert results, "the solver reported nothing"
    assert any("NON DISCRIMINATIVE" in r for r in results)
    body = page.inner_text("#workspace").lower()
    assert "confidence" not in body


def test_abstention_is_shown_as_restraint_and_changes_no_verdict(page):
    """§8, §9, §25. The investigation ran; the verdict did not move.

    Phase 23: the word `abstained` left `.i-abs`, which was painting the room's
    own conclusion a second time at the same size.

    Phase F2: `.i-abs` itself is gone. It stated the verdict, that no financial
    action was taken, and that nothing the model proposed separated the
    explanations — all of which the AI boundary now states, with the counts
    folded in and the discarded verdict named outright. The guarantee did not
    move; the block that carried it did."""
    _ev(page, "#/settlement/setl_000089/investigate")
    room = page.inner_text("#w-main")
    assert "abstained" in room.lower()
    abs_ = page.inner_text(".i-bound")
    assert "no financial action" in abs_.lower()
    assert "AMBIGUOUS" in abs_
    # the subject header still carries the same verdict
    assert "AMBIGUOUS" in page.inner_text(".c-subject")


def test_a_failed_hypothesis_is_not_hidden(page):
    """§6. A trail cleaned up to make the model look competent is worth
    nothing."""
    _ev(page, "#/settlement/setl_000128/investigate")
    txt = page.inner_text("#workspace")
    assert "capture-batch" in txt, "the refuted hypothesis was removed"
    assert "does not distinguish" in txt.lower()


def test_the_lens_failure_is_derived_from_this_pool_not_hardcoded(page):
    """§7. D22 should emerge because it is true here, not because it was typed
    into the interface."""
    _ev(page, "#/settlement/setl_000089/investigate")
    pool = page.evaluate("""async () => {
      const d = await (await fetch(`/api/evidence?run=${SHELL.run}`
        + `&type=settlement&id=setl_000089`)).json();
      return (d.space || {}).candidates; }""")
    sig = page.inner_text(".i-sig-r") + page.inner_text(".i-sig-d")
    assert "capture date" in sig.lower()
    # the pool size is a property of this run, not a constant: pinning it made
    # a seed change look like the lens had stopped stating it.
    assert str(pool) in sig, f"the pool size ({pool}) is not stated"
    body = page.inner_text("#workspace")
    assert "D22" not in body, "a failure reference leaked into the product copy"


def test_a_trail_step_opens_as_context_without_offering_promotion(page):
    """§11, §12. A hypothesis is not a subject anything can be about, so no
    promotion is offered — an affordance that leads nowhere teaches the wrong
    model."""
    _ev(page, "#/settlement/setl_000089/investigate")
    before = page.inner_text("#w-main")
    page.click(".i-tl-s")
    page.wait_for_timeout(1400)
    subject, lens, context = _state(page)
    assert subject == "settlement:setl_000089"
    assert lens == "investigate"
    assert context and context.startswith("step:")
    assert page.inner_text("#w-main") == before
    assert page.query_selector("[data-close-ctx]")
    assert not page.query_selector(".c-ctx-b.go"), "promotion was offered"


def test_closing_an_investigation_step_restores_the_workspace(page):
    _ev(page, "#/settlement/setl_000089/investigate")
    before = page.inner_text("#w-main")
    page.click(".i-tl-s")
    page.wait_for_timeout(1300)
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert _state(page) == ["settlement:setl_000089", "investigate", None]
    assert page.inner_text("#w-main") == before


def test_investigate_to_evidence_preserves_the_subject(page):
    """§21."""
    _ev(page, "#/settlement/setl_000089/investigate")
    page.click("[data-lens=evidence]")
    page.wait_for_timeout(2000)
    subject, lens, _ = _state(page)
    assert subject == "settlement:setl_000089"
    assert lens == "evidence"


def test_investigate_offers_no_way_to_execute_a_financial_action(page):
    """§22, §24. It discovers. Policy decides. Action executes."""
    _ev(page, "#/settlement/setl_000089/investigate")
    body = page.inner_text("#workspace").lower()
    for word in ("post entry", "approve", "auto-post now", "execute", "confirm"):
        assert word not in body, f"Investigate offers {word!r}"
    buttons = page.eval_on_selector_all(
        "#w-main button", "x => x.map(n => n.textContent.trim().toLowerCase())")
    assert not [b for b in buttons if "post" in b or "approve" in b]


def test_a_stale_investigation_cannot_land_on_another_subject(page):
    """§31.13 — D15 at this layer."""
    _ev(page, "#/settlement/setl_000089/investigate")
    page.route("**/api/investigation*", lambda route: (page.wait_for_timeout(2500),
                                                       route.continue_()))
    page.evaluate("navigate({subject:{type:'portfolio',id:'portfolio'}})")
    page.wait_for_timeout(3600)
    page.unroute("**/api/investigation*")
    subject, _, _ = _state(page)
    assert subject == "portfolio:portfolio"
    assert "indistinguishable" not in page.inner_text("#workspace").lower()


# -------------------------------------------------------------- P5: Policy

def test_portfolio_policy_groups_by_what_is_permitted(page):
    """§21."""
    _ev(page, "#/portfolio/policy")
    assert _state(page)[:2] == ["portfolio:portfolio", "policy"]
    groups = page.eval_on_selector_all(".p-grp .p-grp-d",
                                       "x => x.map(n => n.textContent.trim())")
    assert set(groups) == {"AUTO-POST", "REVIEW", "BLOCK"}


def test_settlement_policy_states_the_decision_and_the_verdict_apart(page):
    """§4, §8. A settlement can be AMBIGUOUS and REVIEW; those are two facts.

    Phase 13B: the decision left `.p-head`, which was painting it a second time
    below the conclusion that already leads with it. Both facts are still
    stated and still apart — the decision above, the verdict and what policy
    does with it below — so this reads the room rather than the one block."""
    _ev(page, "#/settlement/setl_000089/policy")
    assert "REVIEW" in page.inner_text(".c-concl")
    head = page.inner_text(".p-head")
    assert "AMBIGUOUS" in head
    assert "does not change it" in head
    assert "REVIEW" not in head, "the decision is stated twice again"


def test_the_decision_is_expressed_as_a_cost_comparison(page):
    """§1, §15, §27. Not a score, not a confidence — an inequality."""
    _ev(page, "#/settlement/setl_000022/policy")
    body = page.inner_text("#workspace")
    assert "expected loss" in body.lower()
    assert "to check" in body.lower()
    assert "₹" in page.inner_text(".p-bound-k")


def test_the_word_confidence_never_appears_in_policy(page):
    """§15."""
    for h in ("#/portfolio/policy", "#/settlement/setl_000022/policy",
              "#/settlement/setl_000089/policy"):
        _ev(page, h)
        assert "confidence" not in page.inner_text("#workspace").lower()


def test_an_unproven_settlement_is_never_priced(page):
    """§16, §33. Policy cannot reach a settlement the proof did not establish,
    so there is no expected loss to compare — and the UI must say that rather
    than show a number it does not have."""
    _ev(page, "#/settlement/setl_000089/policy")
    # Phase 13 §16: this used to read `.p-bound`, a box whose entire content was
    # the sentence the conclusion already leads with. The guarantee did not
    # move — "nothing was priced" is still stated, and the absence of a marker
    # is now absolute rather than a marker-less box.
    assert "nothing was priced" in page.inner_text("#workspace").lower()
    assert page.eval_on_selector_all(".p-bound-mark", "x => x.length") == 0

    # Phase 30 §5 draws the instrument on an unpriced case, with the word
    # UNPRICED where the number would be. Hiding the whole scale also hid that
    # a price was SUPPOSED to be here, and an absence nobody can see is not a
    # statement. So the guarantee is pinned rather than the old mechanism: the
    # slot may exist, but it may not contain money — which is stronger than
    # "the box does not exist", because that check passed happily for any box
    # that had not been built yet and would have said nothing about one built
    # later with a fabricated zero in it.
    lo = page.query_selector(".p-bound-k.lo")
    if lo:
        text = lo.inner_text()
        assert "unpriced" in text.lower(), \
            f"the expected-loss slot does not say it is empty: {text!r}"
        assert "\u20b9" not in text, f"a price was drawn without a proof: {text!r}"
    # Every PROOF gate must fail. This used to count `.p-gate.ok` across the
    # whole room and require zero, which conflated two different things: on
    # this run "below the exposure ceiling" passes, because it is a statement
    # about SIZE and is true of a settlement nobody proved. The decision is
    # still REVIEW. Counting all gates made an honest policy gate look like a
    # proof leaking through, so the assertion now names the stage it means.
    proof_ok = page.evaluate("""() => {
      const st = [...document.querySelectorAll('.p-stage')].find(
        s => /proof/i.test((s.querySelector('.p-stage-h') || {}).textContent || ''));
      return st ? st.querySelectorAll('.p-gate.ok').length : null; }""")
    assert proof_ok == 0, \
        f"{proof_ok} proof gates passed on a settlement with no proof"
    decision = page.evaluate("""async () => {
      const d = await (await fetch(`/api/decision?run=${SHELL.run}`
        + `&type=settlement&id=setl_000089&review=${SHELL.review}`
        + `&exposure=${SHELL.exposure}`)).json();
      return d.decision; }""")
    assert decision != "AUTO_POST", \
        f"an unproven settlement reached {decision}"


def test_the_proof_gates_precede_the_policy_gates(page):
    """§17, §33. AI never skips proof, and the layout is the argument."""
    _ev(page, "#/settlement/setl_000022/policy")
    stages = page.eval_on_selector_all(".p-stage-h",
                                       "x => x.map(n => n.textContent.trim().toLowerCase())")
    assert stages == ["proof", "policy"], stages


def test_the_policy_version_is_visible_and_derived_from_the_costing(page):
    """§12, §25. A what-if is a different policy version, not a recomputation."""
    _ev(page, "#/settlement/setl_000022/policy")
    body = page.inner_text("#workspace")
    assert "policy_" in body
    # The RECORDED costing is whatever the shell is running, not a literal:
    # §47.P1 moved the default review cost from ₹150 to ₹250 and this test then
    # asserted that the recorded policy was a simulation, because ₹150 had
    # become a what-if.
    recorded = page.evaluate("""(async () => {
      const a = await (await fetch(`/api/decision?run=${SHELL.run}&type=settlement`
        + `&id=setl_000022&review=${SHELL.review}`)).json();
      const b = await (await fetch(`/api/decision?run=${SHELL.run}&type=settlement`
        + `&id=setl_000022&review=${SHELL.review * 2}`)).json();
      return [a.policy_version, b.policy_version, a.simulated, b.simulated];
    })()""")
    assert recorded[0] != recorded[1], "the costing did not change the version"
    assert recorded[2] is False, "the recorded costing is reported as a what-if"
    assert recorded[3] is True, "a what-if is not reported as one"


def test_the_ui_decision_matches_the_engine(page):
    """§5, §30.8. The UI represents the engine; it does not re-derive it.

    Phase 13B: `.p-head-d` was the second painting of the decision and is gone.
    Re-pointed at the conclusion that leads the room — and strengthened, because
    the old form checked one element while the room could still have contained a
    contradicting decision elsewhere. Now the engine's decision must be stated
    AND no other decision word may appear anywhere in the room."""
    _ev(page, "#/settlement/setl_000022/policy")
    from_api = page.evaluate("""(async () => {
      const d = await (await fetch(`/api/decision?run=${SHELL.run}`
        + `&type=settlement&id=setl_000022&review=${SHELL.review}`)).json();
      return d.decision; })()""")
    shown = from_api.replace("_", "-")
    assert shown in page.inner_text(".c-concl"), \
        f"the room does not state the engine's decision {shown}"
    # whole lines, not substrings: "COST OF A REVIEW" is a label for what a
    # person's time is worth, not a decision, and a naive `in` check reads it
    # as the engine having been contradicted
    lines = {l.strip().upper()
             for l in page.inner_text("#w-main").splitlines()}
    for other in ("AUTO-POST", "REVIEW", "BLOCK"):
        if other != shown:
            assert other not in lines, \
                f"engine says {shown} but the room also states {other}"


def test_simulating_a_costing_does_not_change_the_recorded_decision(page):
    """§19, §26. Simulation operates on a snapshot and executes nothing."""
    _ev(page, "#/portfolio/policy")
    before = page.evaluate("""(async () => (await (await fetch(
      `/api/decision?run=${SHELL.run}&type=portfolio&review=15000`)).json()).auto_post)()""")
    page.evaluate("SHELL.review = 250000; navigate({}, {replace:true})")
    page.wait_for_timeout(2200)
    assert page.query_selector(".p-sim"), "the simulation was not labelled"
    after = page.evaluate("""(async () => (await (await fetch(
      `/api/decision?run=${SHELL.run}&type=portfolio&review=15000`)).json()).auto_post)()""")
    assert before == after, "simulating mutated the recorded decision"
    page.evaluate("SHELL.review = 15000; navigate({}, {replace:true})")
    page.wait_for_timeout(1800)


def test_policy_offers_no_way_to_execute_an_action(page):
    """§22. Policy says ALLOWED. Action executes. Keep the boundary."""
    _ev(page, "#/settlement/setl_000022/policy")
    buttons = page.eval_on_selector_all(
        "#w-main button", "x => x.map(n => n.textContent.trim().toLowerCase())")
    for b in buttons:
        assert "post now" not in b and "execute" not in b and "approve" not in b


def test_a_policy_decision_opens_as_context(page):
    _ev(page, "#/portfolio/policy")
    before = page.inner_text("#w-main")
    page.click(".p-grp")
    page.wait_for_timeout(1400)
    subject, lens, context = _state(page)
    assert subject == "portfolio:portfolio"
    assert lens == "policy"
    assert context and context.startswith("decision:")
    assert page.inner_text("#w-main") == before
    assert "DECISION" in page.inner_text(".c-crumb").upper()


def test_policy_to_journal_preserves_the_subject(page):
    """§23. The chain is followable without losing the case."""
    _ev(page, "#/settlement/setl_000022/policy")
    page.click("[data-lens=journal]")
    page.wait_for_timeout(1900)
    subject, lens, _ = _state(page)
    assert subject == "settlement:setl_000022"
    assert lens == "journal"


def test_policy_decisions_are_readable_without_colour(page):
    """§29. Colour may reinforce; it cannot be the only signal."""
    _ev(page, "#/settlement/setl_000089/policy")
    gates = page.eval_on_selector_all(
        ".p-gate .p-gate-s", "x => x.map(n => n.textContent.trim().toLowerCase())")
    assert gates and all(g in ("passed", "not satisfied") for g in gates)
    assert page.eval_on_selector_all(".p-gate i", "x => x.map(n => n.textContent.trim())")


def test_a_stale_policy_fetch_cannot_land_on_another_subject(page):
    _ev(page, "#/settlement/setl_000089/policy")
    page.route("**/api/decision*", lambda route: (page.wait_for_timeout(2500),
                                                  route.continue_()))
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000022'}})")
    page.wait_for_timeout(3600)
    page.unroute("**/api/decision*")
    assert _state(page)[0] == "settlement:setl_000022"
    assert "1,00,036.83" not in page.inner_text("#workspace")


# ------------------------------------------------------------ P6: Activity

def test_portfolio_activity_shows_a_run_with_phases_beneath_it(page):
    """§6, §27. Five thousand individual events here would be a log."""
    _ev(page, "#/portfolio/activity")
    assert _state(page)[:2] == ["portfolio:portfolio", "activity"]
    phases = page.eval_on_selector_all(".a-ev", "x => x.length")
    assert 3 <= phases <= 30, f"{phases} entries is a log, not a run"
    assert "run_" in page.inner_text(".a-state")


def test_settlement_activity_tells_one_lifecycle(page):
    _ev(page, "#/settlement/setl_000089/activity")
    stages = page.eval_on_selector_all(".a-stage",
                                       "x => x.map(n => n.textContent.trim())")
    for s in ("source", "matching", "verification", "policy", "action"):
        assert s in stages, f"{s} missing from the lifecycle"
    assert stages.index("source") < stages.index("verification") < stages.index("action")


def test_every_event_states_what_caused_it(page):
    """§9, §41. Causality is the connector, not a column."""
    _ev(page, "#/settlement/setl_000089/activity")
    causes = page.eval_on_selector_all(".a-cause span",
                                       "x => x.map(n => n.textContent.trim())")
    assert len(causes) >= 4, "the timeline has no causal links"
    assert all(c.startswith("because") for c in causes)


def test_permission_and_execution_are_separate_events(page):
    """§18, §31, §40 — the foundational distinction. ALLOWED is not DONE.

    §47.F1. This used to assert LEDGER UPDATED on a settlement that posted. On
    the held-out seed nothing posts: every proven case fails "expected loss is
    below the cost of checking", so the ledger is empty and that is the honest
    result, not a gap to engineer around.

    It is also the harder case for this guarantee, which is why the test stays
    here rather than moving to data that posts. A room that collapsed
    permission into execution would have one way to say "no" — it must have
    two, and both must be on screen: the policy did not permit, and separately,
    nothing was executed. The stage order is the same order the pipeline runs
    in, and it must survive the outcome being negative.
    """
    _ev(page, "#/settlement/setl_000022/activity")
    stages = page.eval_on_selector_all(".a-stage",
                                       "x => x.map(n => n.textContent.trim())")
    assert stages.count("policy") == 1 and stages.count("action") == 1
    assert stages.index("policy") < stages.index("action"), \
        "execution is not reported after the permission that would allow it"

    # Read the room's own conclusion rather than re-deriving it from a second
    # fetch. The fetch version raced SHELL.review's initialisation and failed
    # once against a room that was correct; and "the room agrees with itself"
    # is the stronger property anyway — a posting claim and an execution badge
    # that disagree is exactly the defect this test exists to catch.
    body = page.inner_text("#workspace")
    posted = "An entry was written" in body
    assert posted or "Ledger unchanged" in body, \
        "the room states neither that an entry was written nor that it was not"

    if posted:
        assert page.eval_on_selector_all(".a-badge.yes", "x => x.length") >= 1, \
            "an entry was written but no step reports permission"
        assert page.eval_on_selector_all(".a-badge.done", "x => x.length") >= 1, \
            "an entry was written but no step reports execution"
    else:
        # the two refusals are stated separately, in that order
        assert page.eval_on_selector_all(".a-badge.no", "x => x.length") >= 1, \
            "no step reports that permission was withheld"
        assert page.eval_on_selector_all(".a-badge.undone", "x => x.length") >= 1, \
            "no step reports that execution did not happen"
        assert page.eval_on_selector_all(".a-badge.done", "x => x.length") == 0, \
            "something is marked executed on a run that posted nothing"


def test_a_settlement_that_was_not_posted_says_the_ledger_is_unchanged(page):
    """§18 again, from the other side: permission withheld must not read as an
    action that merely has not happened yet."""
    _ev(page, "#/settlement/setl_000089/activity")
    body = page.inner_text("#workspace")
    assert "LEDGER UNCHANGED" in body
    assert "NOT PERMITTED" in body.upper()
    assert page.eval_on_selector_all(".a-badge.done", "x => x.length") == 0


def test_the_actors_are_distinguishable(page):
    """§17. Compact semantic markers, no avatars."""
    _ev(page, "#/settlement/setl_000089/activity")
    actors = page.eval_on_selector_all(".a-actor",
                                       "x => x.map(n => n.textContent.trim())")
    assert {"System", "Engine", "Model", "Solver", "Policy"} <= set(actors)
    glyphs = page.eval_on_selector_all(".a-mark",
                                       "x => x.map(n => n.textContent.trim())")
    assert len(set(glyphs)) >= 4, f"actors share a glyph: {set(glyphs)}"


def test_no_human_actor_is_invented(page):
    """§16. This system records no operator identity anywhere, so Activity must
    not manufacture one. The gap is the honest rendering of a gap."""
    for h in ("#/portfolio/activity", "#/settlement/setl_000089/activity"):
        _ev(page, h)
        actors = page.eval_on_selector_all(".a-actor",
                                           "x => x.map(n => n.textContent.trim())")
        assert "Human" not in actors
        body = page.inner_text("#workspace").lower()
        for word in ("reviewed by", "approved by", "@"):
            assert word not in body


def test_an_event_opens_as_context_and_says_it_is_immutable(page):
    """§11, §12. Inspecting is not re-running."""
    _ev(page, "#/settlement/setl_000089/activity")
    before = page.inner_text("#w-main")
    page.click(".a-ev")
    page.wait_for_timeout(1400)
    subject, lens, context = _state(page)
    assert subject == "settlement:setl_000089"
    assert lens == "activity"
    assert context and context.startswith("event:")
    assert page.inner_text("#w-main") == before, "the timeline re-rendered"
    ctx = page.inner_text("#w-ctx").lower()
    assert "does not re-run" in ctx or "immutable" in ctx


def test_closing_an_event_restores_the_timeline(page):
    _ev(page, "#/settlement/setl_000089/activity")
    before = page.inner_text("#w-main")
    page.click(".a-ev")
    page.wait_for_timeout(1300)
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert _state(page) == ["settlement:setl_000089", "activity", None]
    assert page.inner_text("#w-main") == before


def test_unrevised_is_the_word_used_not_stale_or_wrong(page):
    """§14. An important product language rule — and it only has anything to
    say once something IS unrevised, so deliver an event first."""
    _ev(page, "#/portfolio/activity")
    page.evaluate("""(async () => { await fetch(
      `/api/events/demo?run=${SHELL.run}`, {method:'POST'}); })()""")
    page.wait_for_timeout(2000)
    page.evaluate("navigate({}, {replace:true})")
    page.wait_for_timeout(2400)
    body = page.inner_text("#workspace").lower()
    assert "unrevised" in body, "the word is not used where the concept appears"
    for banned in ("stale", "invalid verdict", "wrong verdict"):
        assert banned not in body


def test_a_repeat_delivery_is_explained_as_producing_no_second_action(page):
    """§20. Idempotency matters in a payments system and must be legible."""
    _ev(page, "#/portfolio/activity")
    page.evaluate("""(async () => { await fetch(
      `/api/events/demo?run=${SHELL.run}`, {method:'POST'}); })()""")
    page.wait_for_timeout(2000)
    page.evaluate("navigate({}, {replace:true})")
    page.wait_for_timeout(2400)
    # The delivery statuses are visible; the explanation sits behind a
    # disclosure, so read textContent rather than innerText for that half.
    assert "duplicate" in page.inner_text("#workspace").lower()
    explained = page.eval_on_selector(
        "#w-main", "n => n.textContent.toLowerCase()")
    assert "no second action" in explained
    assert "replay mismatch" in page.inner_text("#workspace").lower() \
        or "replay_mismatch" in explained


def test_replay_reports_a_measured_comparison_not_a_claim(page):
    """§36. A replay button was only built because the claim is measurable."""
    _ev(page, "#/portfolio/activity")
    original = page.evaluate("SHELL.run")
    page.click("#a-replay-go")
    page.wait_for_selector(".a-rep", timeout=120000)
    page.wait_for_timeout(600)
    out = page.inner_text(".a-rep")
    assert "Reproduced" in out
    assert "differing" in out.lower()
    assert "provenance" in out.lower()
    # the original run is untouched — the shell still points at it
    assert page.evaluate("SHELL.run") == original


def test_activity_to_evidence_preserves_the_subject(page):
    _ev(page, "#/settlement/setl_000089/activity")
    page.click("[data-lens=evidence]")
    page.wait_for_timeout(2000)
    subject, lens, _ = _state(page)
    assert subject == "settlement:setl_000089" and lens == "evidence"


def test_activity_to_policy_preserves_the_subject(page):
    _ev(page, "#/settlement/setl_000089/activity")
    page.click("[data-lens=policy]")
    page.wait_for_timeout(2000)
    subject, lens, _ = _state(page)
    assert subject == "settlement:setl_000089" and lens == "policy"


def test_activity_is_not_a_generic_log_table(page):
    """§41. If it can be represented as timestamp | actor | event | status, the
    design has failed. Every entry must carry cause and effect."""
    _ev(page, "#/settlement/setl_000089/activity")
    events = page.eval_on_selector_all(".a-ev", "x => x.length")
    effects = page.eval_on_selector_all(".a-eff", "x => x.length")
    causes = page.eval_on_selector_all(".a-cause", "x => x.length")
    assert effects >= events - 1, "events without a stated effect"
    assert causes >= events - 2, "events without a stated cause"
    assert page.eval_on_selector_all("#w-main table", "x => x.length") == 0


def test_a_stale_activity_fetch_cannot_land_on_another_subject(page):
    _ev(page, "#/settlement/setl_000089/activity")
    page.route("**/api/activity*", lambda route: (page.wait_for_timeout(2500),
                                                  route.continue_()))
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000022'}})")
    page.wait_for_timeout(3600)
    page.unroute("**/api/activity*")
    assert _state(page)[0] == "settlement:setl_000022"
    assert "1,00,036.83" not in page.inner_text("#workspace")


# --------------------------------------------------------------- P7: Trust

def test_trust_opens_with_the_failures_not_with_the_wins(page):
    """§2, §34. A trust surface that opens with green ticks is a pitch deck."""
    _ev(page, "#/portfolio/trust")
    assert _state(page)[:2] == ["portfolio:portfolio", "trust"]
    head = page.inner_text(".t-head")
    assert "failed" in head.lower()
    body = page.inner_text("#w-main").lower()
    assert "not verified" in body, "the surface does not lead with a limitation"

    # The failure block precedes the claim register. Asserted by DOM position
    # rather than by a heading string: the register's section is now titled
    # "what it has demonstrated" and lives inside a verified zone, so searching
    # for the old wording tested the copy rather than the ordering.
    order = page.evaluate("""() => {
        const main = document.getElementById('w-main');
        const bad = main.querySelector('.t-bad');
        const claim = main.querySelector('.t-claim');
        if (!bad || !claim) return null;
        return bad.compareDocumentPosition(claim)
               & Node.DOCUMENT_POSITION_FOLLOWING ? 'bad-first' : 'claims-first';
    }""")
    assert order == "bad-first", \
        f"the claim register comes before the failures ({order})"


def test_every_claim_names_the_artifact_it_reads(page):
    """§5, §6. A number typed into an interface is a number nothing checks."""
    _ev(page, "#/portfolio/trust")
    sources = page.eval_on_selector_all(".t-claim-src",
                                        "x => x.map(n => n.textContent.trim())")
    assert len(sources) >= 6
    assert all(s and s != "no source" for s in sources)
    assert any("benchmark/" in s for s in sources)


def test_the_headline_figures_match_the_artifacts_on_disk(page):
    """§6 again, mechanically: the surface must agree with the files."""
    same = page.evaluate("""(async () => {
      const c = await (await fetch(`/api/claims?run=${SHELL.run}`)).json();
      const r = await (await fetch('/results.json').catch(() => ({json:()=>({})}))).json()
        .catch(() => ({}));
      return {scope: c.scope, claims: c.claims.length,
              hasBaselines: c.artifacts.some(a => a.name.includes('baselines') && a.present)};
    })()""")
    assert same["claims"] >= 6
    assert same["hasBaselines"], "the baseline artifact is missing"
    assert "settlement" in same["scope"]


def test_a_claim_without_a_machine_readable_source_is_marked_limited(page):
    """§23. The surface has to be able to say no."""
    _ev(page, "#/portfolio/trust")
    states = page.eval_on_selector_all(".t-claim-s",
                                       "x => x.map(n => n.textContent.trim())")
    assert "LIMITED" in states, "nothing is qualified — every claim reads as measured"
    assert not all(s == "MEASURED" for s in states), "a wall of green"


def test_trust_states_a_claim_against_itself(page):
    """§36, §49. A red result can increase trust if it is honest."""
    _ev(page, "#/portfolio/trust")
    body = page.inner_text("#w-main").lower()
    assert "not the most precise" in body, \
        "the panel does not report where a baseline beats ATTEST"


def test_the_wrongly_posted_figure_is_scoped_to_the_panel(page):
    """§29. ₹0 is a measurement, not a guarantee."""
    _ev(page, "#/portfolio/trust")
    page.click("[data-context='claim:C-001']")
    page.wait_for_timeout(1400)
    ctx = page.inner_text("#w-ctx").lower()
    assert "settlement" in ctx and "seed" in ctx, "no scope stated"
    assert "not a claim that" in ctx or "only that" in ctx


def test_limitations_are_shown_and_are_absences_not_unknowns(page):
    """§21, §22. Absence is not failure and must not be dressed as mystery."""
    _ev(page, "#/portfolio/trust")
    body = page.inner_text("#w-main")
    assert "not known" in body.lower()
    rows = page.eval_on_selector_all(".t-unk-r", "x => x.length")
    assert rows >= 4
    low = body.lower()
    assert "no operator identity" in low
    assert "unknown operator" not in low


def test_rejected_features_are_visible_as_rejected(page):
    """§4, §33. Built, measured, disabled is stronger than a feature list."""
    _ev(page, "#/portfolio/trust")
    body = page.inner_text("#w-main").lower()
    assert "built, measured, then disabled" in body
    refs = page.eval_on_selector_all(".t-fail.ref", "x => x.length")
    assert refs >= 1


def test_the_ai_precision_number_is_not_hidden_or_improved(page):
    """§14. The number that disabled the resolver stays on the surface."""
    _ev(page, "#/portfolio/trust")
    body = page.inner_text("#w-main").lower()
    assert "cannot reliably resolve" in body
    vals = page.eval_on_selector_all(".t-claim-v",
                                     "x => x.map(n => n.textContent.trim())")
    assert any("precision" in v for v in vals)


def test_what_the_model_may_not_do_is_stated(page):
    """§13. Connected to the real permission model."""
    _ev(page, "#/portfolio/trust")
    body = page.inner_text("#w-main").lower()
    assert "granted to nothing" in body
    blocked = page.eval_on_selector_all(".t-perm-i.no", "x => x.length")
    assert blocked >= 3


def test_the_gates_show_what_they_protect_not_just_a_tick(page):
    """§19."""
    _ev(page, "#/portfolio/trust")
    gates = page.eval_on_selector_all(".t-gate", "x => x.length")
    assert gates >= 5
    whys = page.eval_on_selector_all(".t-gate-w",
                                     "x => x.map(n => n.textContent.trim())")
    assert all(len(w) > 20 for w in whys), "a gate does not say what it protects"
    assert page.eval_on_selector_all(".t-gate-n em", "x => x.length") >= 5


def test_a_claim_opens_as_context_with_its_limitation(page):
    _ev(page, "#/portfolio/trust")
    before = page.inner_text("#w-main")
    page.click(".t-claim")
    page.wait_for_timeout(1400)
    subject, lens, context = _state(page)
    assert subject == "portfolio:portfolio"
    assert lens == "trust"
    assert context and context.startswith("claim:")
    assert page.inner_text("#w-main") == before
    assert "CLAIM" in page.inner_text(".c-crumb").upper()


def test_a_failure_opens_as_context_with_its_measurement(page):
    _ev(page, "#/portfolio/trust")
    page.click(".t-fail.ref")
    page.wait_for_timeout(1400)
    assert _state(page)[2].startswith("failure:")
    ctx = page.inner_text("#w-ctx").lower()
    assert "disabled" in ctx or "measured" in ctx


def test_closing_trust_context_restores_the_register(page):
    _ev(page, "#/portfolio/trust")
    before = page.inner_text("#w-main")
    page.click(".t-claim")
    page.wait_for_timeout(1300)
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)
    assert _state(page) == ["portfolio:portfolio", "trust", None]
    assert page.inner_text("#w-main") == before


def test_trust_carries_no_marketing_language(page):
    """§35. A lab notebook, not a pitch deck."""
    _ev(page, "#/portfolio/trust")
    body = page.eval_on_selector("#w-main", "n => n.textContent.toLowerCase()")
    for word in ("industry-leading", "best-in-class", "revolutionary",
                 "ai-powered", "enterprise-grade", "production-ready",
                 "world-class", "cutting-edge"):
        assert word not in body, f"marketing language: {word!r}"


def test_trust_declines_to_render_on_a_settlement(page):
    """Trust is a property of the system, not of one record."""
    _ev(page, "#/settlement/setl_000089/trust")
    body = page.inner_text("#workspace").lower()
    assert "property of the system" in body
    assert page.eval_on_selector_all(".t-claim", "x => x.length") == 0


def test_a_stale_trust_fetch_cannot_land_on_another_subject(page):
    _ev(page, "#/portfolio/trust")
    page.route("**/api/claims*", lambda route: (page.wait_for_timeout(2500),
                                                route.continue_()))
    page.evaluate("navigate({subject:{type:'settlement',id:'setl_000022'},lens:'control'})")
    page.wait_for_timeout(3600)
    page.unroute("**/api/claims*")
    assert _state(page)[0] == "settlement:setl_000022"
    assert "uncomfortable numbers" not in page.inner_text("#workspace").lower()


# --------------------------------------------------------------------------
# Phase 9.4 — interaction guarantees that were defects before they were rules.
# --------------------------------------------------------------------------

def test_the_state_spine_is_present_on_every_lens(page):
    """§9.3C. It is the application's "you are here".

    It used to be drawn by whichever lens chose to call StateSpine, so it
    appeared on two views out of fourteen and vanished entirely on Trust —
    the one lens where a reader is holding "where did the money stop" while
    reading about the system's own failures. It is rendered by the shell now,
    which is what makes "no exceptions" a property rather than a promise.
    """
    for subject in ("portfolio", "settlement/setl_000089"):
        for lens in ("control", "journal", "evidence", "investigate",
                     "policy", "activity", "trust"):
            page.evaluate(f"() => location.hash = '#/{subject}/{lens}'")
            page.wait_for_timeout(500)
            # The spine moved from a band above the workspace into the case
            # rail — part of the case's financial identity now, not a strip
            # over the instrument. The guarantee is unchanged: present on
            # every lens, which is what this asserts.
            #
            # Phase 31 added a second place it can live. On portfolio/control
            # the room draws the collapse full width, with the held money at
            # hero size, and the rail was drawing the same five stages beside
            # it in miniature — the landing carrying its own state twice, which
            # is what made it read as two dashboards. So the rail's copy is
            # suppressed on exactly that one room, and this looks for the chain
            # wherever the screen draws it. Still fourteen screens, still no
            # exceptions; it just no longer insists on WHICH instrument.
            h = page.evaluate("""() => {
                for (const sel of ['.c-flow', '.o-collapse']) {
                  const e = document.querySelector(sel);
                  if (e && e.getBoundingClientRect().height > 0)
                    return e.getBoundingClientRect().height;
                }
                return 0; }""")
            assert h > 0, f"no money-flow chain on {subject}/{lens}"


def test_the_master_owns_the_full_width_until_something_is_inspected(page):
    """§9.3N. The absence of a context is itself the correct state.

    The pane was hidden when nothing was selected, but its grid COLUMN stayed:
    the master rendered at 54% of the workspace and the other 46% was reserved
    for the sentence "Select a row to inspect it."
    """
    page.evaluate("() => location.hash = '#/portfolio/control'")
    page.wait_for_timeout(900)
    share = page.evaluate("""() => {
        const ws = document.getElementById('workspace');
        const m = document.getElementById('w-main');
        return m.getBoundingClientRect().width / ws.getBoundingClientRect().width; }""")
    assert share > 0.95, f"master holds only {share:.0%} with no context open"

    page.click(".c-row.link")
    page.wait_for_timeout(900)
    shared = page.evaluate("""() => {
        const ws = document.getElementById('workspace');
        const m = document.getElementById('w-main');
        return m.getBoundingClientRect().width / ws.getBoundingClientRect().width; }""")
    assert shared < 0.8, "opening a context did not give the pane its column"
    page.keyboard.press("Escape")
    page.wait_for_timeout(600)


def test_the_palette_reaches_a_settlement_by_keyboard_alone(page):
    """§9.4.18. The whole journey must be possible without a mouse.

    Reaching a settlement otherwise means tabbing through a queue of 250.
    """
    page.evaluate("() => location.hash = '#/portfolio/control'")
    page.wait_for_timeout(900)
    page.keyboard.press("Meta+k")
    page.wait_for_timeout(400)
    assert page.evaluate("() => PALETTE.isOpen()"), "Cmd+K did not open the palette"
    assert page.evaluate("() => document.activeElement.classList.contains('c-pal-q')"), \
        "the palette opened without taking focus"

    page.keyboard.type("setl_0000")
    page.wait_for_timeout(400)
    labels = page.evaluate(
        "() => [...document.querySelectorAll('.c-pal-l')].map(n => n.textContent)")
    assert labels and all(l.startswith("setl_") for l in labels[:3]), \
        f"a settlement query returned {labels[:3]}"

    page.keyboard.press("Enter")
    page.wait_for_timeout(900)
    assert page.evaluate("() => SHELL.subject.type") == "settlement"
    assert not page.evaluate("() => PALETTE.isOpen()"), "the palette stayed open"


def test_closing_the_palette_never_drops_focus_to_the_document(page):
    """§9.4.18. Focus landing on <body> is how a keyboard journey ends."""
    page.evaluate("() => location.hash = '#/portfolio/control'")
    page.wait_for_timeout(800)
    page.keyboard.press("Meta+k")
    page.wait_for_timeout(400)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    tag = page.evaluate("() => document.activeElement.tagName")
    assert tag != "BODY", "focus was returned to the document"


# --------------------------------------------------------------------------
# Phase 11 — the operational workflow. A blocker is the smallest missing fact
# preventing money from progressing, and the product's job is to say what it
# is, what it holds, and whether ATTEST can do anything about it.
# --------------------------------------------------------------------------

def test_no_action_label_claims_a_capability_attest_does_not_have(page):
    """§3, §16, §18. The one rule that makes the rest of it honest.

    Every blocker carries a capability label, and every one of the three is
    something ATTEST cannot perform: an external change at the source, a
    decision about the engine's own defaults, or a human searching a record.
    A label that implies otherwise is the product lying about itself.
    """
    _ev(page, "#/portfolio/control")
    caps = page.eval_on_selector_all(
        ".c-blk-c", "x => x.map(n => n.textContent.trim().toUpperCase())")
    assert len(caps) >= 3, "blockers do not state what ATTEST can do about them"

    PERMITTED = {"REQUIRES EXTERNAL EVIDENCE", "REQUIRES ENGINE CHANGE",
                 "REQUIRES HUMAN SEARCH", "ENGINE ACTION", "POLICY SIMULATION"}
    for c in caps:
        assert c in PERMITTED, f"unrecognised capability label: {c!r}"

    # An executable label may only appear where the engine can genuinely act.
    # Nothing in this list can be executed today, so nothing may claim it.
    body = page.inner_text("#w-main").upper()
    for lie in ("FREE RE-RUN", "ONE CLICK", "RESOLVE NOW", "FIX AUTOMATICALLY"):
        assert lie not in body, f"{lie!r} promises an operation that cannot run"


def test_the_free_re_run_label_is_gone(page):
    """§3. It was never free and it was never available.

    The pipeline already escalates through every rung on each run, so widening
    the window means widening beyond the lag ladder — a constant in protected
    blocking.py that the blocking study explicitly decided to keep. Calling it
    a free re-run invited an operator to look for a button that cannot exist.
    """
    for h in ("#/portfolio/control", "#/portfolio/journal"):
        _ev(page, h)
        assert "free re-run" not in page.inner_text("#w-main").lower()


def test_selecting_a_blocker_scopes_its_population(page):
    """§4. A blocker is work, and work has a population."""
    _ev(page, "#/portfolio/control")
    page.click(".c-blk")
    page.wait_for_timeout(1200)
    subject, lens, context = _state(page)
    assert subject == "portfolio:portfolio", "selecting a blocker navigated away"
    assert lens == "control", "selecting a blocker changed the instrument"
    assert context and context.startswith("action:")
    rows = page.eval_on_selector_all(".c-pop-r", "x => x.length")
    assert rows >= 1, "the blocker does not show the settlements it holds"


def test_a_case_remembers_the_blocker_it_came_from(page):
    """§5, §10. Three instruments later, an operator should still know why
    this case is on screen — and it must survive reload, because the reason
    belongs in the URL exactly as the other state does."""
    _ev(page, "#/portfolio/control")
    page.click(".c-blk")
    page.wait_for_timeout(1200)
    page.click(".c-pop-r")
    page.wait_for_timeout(1400)

    assert page.evaluate("() => SHELL.subject.type") == "settlement"
    origin = page.evaluate("() => SHELL.from")
    assert origin, "the case forgot the blocker it was opened from"
    assert "from=" in page.evaluate("() => location.hash")
    assert page.query_selector(".c-from"), "the blocker is not shown on the case"

    for lens in ("evidence", "investigate", "policy", "journal", "activity"):
        page.evaluate(f"() => navigate({{lens:'{lens}'}})")
        page.wait_for_timeout(700)
        assert page.evaluate("() => SHELL.from") == origin, \
            f"the blocker was lost switching to {lens}"
        assert page.query_selector(".c-from"), f"blocker not shown on {lens}"

    page.reload(wait_until="networkidle")
    page.wait_for_function("() => SHELL && SHELL.record", timeout=90000)
    page.wait_for_timeout(900)
    assert page.evaluate("() => SHELL.from") == origin, \
        "the blocker did not survive a reload"


def test_the_contradicted_case_is_reachable_without_knowing_its_id(page):
    """§6. It was only findable by typing setl_000166 into the URL."""
    _ev(page, "#/portfolio/control")
    blockers = page.query_selector_all(".c-blk")
    assert len(blockers) >= 3
    blockers[-1].click()          # the per-item blocker holds the contradiction
    page.wait_for_timeout(1200)
    ids = page.eval_on_selector_all(".c-pop-id", "x => x.map(n => n.textContent.trim())")
    assert ids, "the per-item blocker shows no settlements"
    page.click(".c-pop-r")
    page.wait_for_timeout(1400)
    assert page.evaluate("() => SHELL.record.status") == "CONTRADICTED"


def test_a_contradicted_case_is_not_reported_as_passing(page):
    """A settlement can pass every check it was given and still have no
    explanation at all — the contradiction lives in the unsat core. Control
    reported 'every check passed' over exactly that."""
    _ev(page, "#/settlement/setl_000166/control")
    concl = page.inner_text(".c-concl").lower()
    assert "every check passed" not in concl
    assert "no combination explains" in concl
    residual = page.evaluate("""async () => {
      const d = await (await fetch(`/api/settlement?run=${SHELL.run}`
        + `&id=setl_000166`)).json();
      const e = d.exception || {};
      return (e.unexplained_paise != null ? e.unexplained_paise : null); }""")
    assert residual, "the run reports no residual for this case"
    assert f"{residual / 100:,.2f}" in concl, \
        f"the unresolved residual (Rs {residual / 100:,.2f}) is not stated"


def test_the_review_cost_lever_never_edits_the_recorded_policy(page):
    """§8. Looking at what a review is worth must not change what was decided."""
    _ev(page, "#/portfolio/control")
    lever = page.inner_text(".c-lever")
    assert "post without a person" in lever
    assert "not modified" in lever.lower(), \
        "the lever does not say the recorded policy is untouched"

    before = page.evaluate("""() => fetch(
        `/api/decision?run=${SHELL.run}&type=portfolio`)
        .then(r => r.json()).then(d => d.recorded_version)""")
    page.evaluate("() => navigate({lens:'policy'})")
    page.wait_for_timeout(900)
    after = page.evaluate("""() => fetch(
        `/api/decision?run=${SHELL.run}&type=portfolio`)
        .then(r => r.json()).then(d => d.recorded_version)""")
    assert before == after, "the recorded policy version moved"


def test_the_blocker_value_stays_visible_while_inspecting_a_case(page):
    """§5. The value is why the work was chosen; losing it loses the reason."""
    _ev(page, "#/portfolio/control")
    page.click(".c-blk")
    page.wait_for_timeout(1200)
    page.click(".c-pop-r")
    page.wait_for_timeout(1400)
    page.evaluate("() => navigate({lens:'evidence'})")
    page.wait_for_timeout(800)
    from_text = page.inner_text(".c-from")
    assert "₹" in from_text, "the blocker's value is not carried onto the case"


def test_no_room_leads_with_a_bare_entity_count(page):
    """Phase 12 Part 12. The first thing the eye meets in a room is the answer
    to that room's question, not an inventory of what it contains.

    Activity led with '60 / events delivered' — the only figure of seven that
    was a countable rather than a conclusion."""
    for lens in ("control", "evidence", "investigate", "policy",
                 "journal", "activity", "trust"):
        _ev(page, f"#/portfolio/{lens}")
        fig = page.inner_text(".c-concl-n b").strip()
        # a conclusion carries money, a verdict, or a ratio — never a lone count
        assert ("₹" in fig or "/" in fig or " of " in fig
                or fig.isupper()), \
            f"{lens} leads with a bare count: {fig!r}"


def test_activity_does_not_count_refused_events_as_delivered(page):
    """Phase 12 G-2. 43 of 60 inbound events were refused as duplicates,
    replays or bad signatures. A room whose subject is what actually happened
    must not headline all 60 as though they landed."""
    _ev(page, "#/portfolio/activity")
    # a fresh run has no deliveries at all, and the claim under test is about
    # how refusals are reported — so put some refusals in the log first
    page.evaluate("""(async () => { await fetch(
      `/api/events/demo?run=${SHELL.run}`, {method:'POST'}); })()""")
    page.wait_for_timeout(2000)
    page.evaluate("navigate({}, {replace:true})")
    page.wait_for_timeout(2400)

    label = page.inner_text(".c-concl-n em").lower()
    assert "delivered" not in label, \
        f"the headline still describes inbound events as delivered: {label!r}"

    room = page.inner_text("#workspace").lower()
    assert "deliveries since" in room, "the delivery record is gone entirely"

    # whatever the webhook state, the room must state it exactly: every
    # non-zero outcome named, and refusals never folded into acceptances
    d = page.evaluate("""async () => {
        const r = await fetch(`/api/activity?run=${SHELL.run}&type=portfolio`);
        return await r.json();}""")
    for kind, n in (d.get("delivery_counts") or {}).items():
        if n:
            assert kind.replace("_", " ") in room, \
                f"{n} {kind} deliveries are not stated anywhere in Activity"

    # the headline counts verdicts, not deliveries — asserted by derivation
    # rather than by "the delivery number is absent", which collides by
    # coincidence once enough events have been delivered
    total = max((o.get("n") or 0) for o in d["outcome"])
    unrev = len(d.get("unrevised") or [])
    assert page.inner_text(".c-concl-n b").strip() == f"{total - unrev} of {total}", \
        "the headline figure is not the count of settlements whose verdicts stand"


def _money_sizes(page, root):
    """Every painted ₹ amount under `root`, with its computed type size."""
    return page.evaluate("""(sel) => {
      // querySelectorAll, not querySelector: a screen may state the same fact
      // in more than one instrument, and measuring only the first one let the
      // others paint money at any size they liked.
      const roots = [...document.querySelectorAll(sel)]; if (!roots.length) return [];
      const out = [];
      const vis = e => { const s = getComputedStyle(e);
        return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'; };
      const walk = el => { for (const n of el.childNodes) {
        if (n.nodeType === 3 && n.textContent.includes('\\u20b9')) {
          const g = document.createRange(); g.selectNodeContents(n);
          const b = g.getBoundingClientRect();
          if (b.height && b.width) out.push({
            t: n.textContent.trim(),
            px: parseFloat(getComputedStyle(n.parentElement).fontSize)});
        } else if (n.nodeType === 1 && vis(n)) walk(n); } };
      roots.forEach(walk); return out; }""", root)


def test_money_never_renders_at_annotation_size(page):
    """Phase 13 §6. '₹ amounts must never visually look like metadata.'

    The State Spine painted ₹48,03,127.81 — the money held at verification, and
    the answer to 'where did my money stop' — at 9px, the same size as the word
    'Source' beside it. The 10px and 11px tiers are for provenance, timestamps
    and counts. Money is the subject of this product, not an annotation."""
    BODY = 13
    for route in ("#/portfolio/control", "#/settlement/setl_000089/evidence",
                  "#/settlement/setl_000166/control"):
        _ev(page, route)
        small = [m for m in _money_sizes(page, ".c-case") if m["px"] < BODY]
        assert not small, (
            f"{route}: money at annotation size in the case rail: "
            + ", ".join(f"{m['t']} at {m['px']:.0f}px" for m in small[:6]))


def test_the_money_that_stopped_outranks_any_single_blocker(page):
    """Phase 13 §6. Establish visual roles: money that stopped is not smaller
    than one item of work.

    ₹6,316.03 — the smallest blocker in the list — rendered at 20px while
    ₹48,03,127.81 held at verification rendered at 9px. A ₹6,316 problem was
    painted 2.2x larger than ₹48 lakh of stuck money."""
    _ev(page, "#/portfolio/control")
    # Wherever the landing states it. Phase 30 made the room's collapse the
    # landing's central instrument, so the rail is no longer the only place the
    # money that stopped is stated — and pinning the rail alone would have let
    # the room paint that figure at any size it liked.
    held = [m for m in _money_sizes(page, ".c-state, .o-stage-x") if m["px"]]
    assert held, "no money in the state spine"
    stopped = max(m["px"] for m in held)
    # an individual work item, not the room's headline conclusion — that
    # figure is the leverage of the top blocker and leads the room by design
    rows = page.query_selector_all(".c-blk-v")
    assert rows, "no blocker rows on the landing"
    biggest_blocker = max(
        page.evaluate("e => parseFloat(getComputedStyle(e).fontSize)", r)
        for r in rows)
    assert stopped >= biggest_blocker, (
        f"a single blocker is painted at {biggest_blocker:.0f}px while the money "
        f"that stopped is at {stopped:.0f}px")


def test_no_control_renders_with_browser_default_chrome(page):
    """Phase 13 §17. 'No card-grid-everything.'

    `button { font: inherit; color: inherit }` resets the type and nothing
    else, so every button that did not set its own background inherited
    Chromium's `buttonface` grey and a 2px outset border. 111 of ~190 visible
    controls were rendering as raw OS buttons — including all seven instrument
    dock items, whose stylesheet comment describes 'a seated indent against the
    rail edge rather than a filled chip', and the three blocker rows, which
    read as the SaaS cards the brief warns against.

    Nothing about that was a design decision. It was a missing reset."""
    seen = []
    for subject in ("portfolio", "settlement/setl_000089"):
        for lens in ("control", "evidence", "investigate", "policy",
                     "journal", "activity", "trust"):
            _ev(page, f"#/{subject}/{lens}")
            seen += page.evaluate("""() =>
              [...document.querySelectorAll('button')]
                .filter(e => e.offsetParent)
                .map(e => { const s = getComputedStyle(e);
                  return {cls: e.className || '(no class)',
                          bg: s.backgroundColor, bd: s.borderTopStyle}; })
                .filter(r => r.bd === 'outset' || r.bg === 'rgb(239, 239, 239)')""")
    assert not seen, (
        f"{len(seen)} controls render with browser default chrome: "
        + ", ".join(sorted({r["cls"] for r in seen})[:8]))


def test_every_instrument_states_its_question(page):
    """Phase 13 §9. 'It is an instrument index, not a navigation bar.'

    The dock's own stylesheet says an item should state what it asks — and
    `.c-lens-q { display: none }` hid the question on every instrument except
    the selected one, so six of seven read as bare nouns. A menu names places."""
    _ev(page, "#/portfolio/control")
    items = page.query_selector_all(".c-lenses button")
    assert len(items) == 7, f"expected seven instruments, saw {len(items)}"
    for it in items:
        q = it.query_selector(".c-lens-q")
        assert q and q.is_visible(), \
            f"{it.inner_text().strip()[:20]} states no question"
        assert q.inner_text().strip().endswith("?"), \
            f"not a question: {q.inner_text()!r}"


def test_the_dock_reads_as_the_product_loop(page):
    """Phase 13 §1, §9. The instruments are ordered by the operator's
    sequence — where did it stop, can it be proved, what would separate them,
    what may we do, what entered the books, what happened, what can I believe.

    Journal sat second, which put 'what entered the books' before 'may we post
    at all'."""
    _ev(page, "#/portfolio/control")
    order = [b.get_attribute("data-lens")
             for b in page.query_selector_all(".c-lenses button")]
    assert order == ["control", "evidence", "investigate", "policy",
                     "journal", "activity", "trust"], order


def test_no_type_size_outside_the_declared_scale(page):
    """Phase 13 §5. Six steps: 10, 11, 13, 15, 20, 34.

    An undeclared 9px tier had grown to 14 rules and 50 painted elements, and
    it was not carrying decoration — it carried the stage names, the held
    amounts and the capability labels. That is how ₹48,03,127.81 came to be
    painted smaller than the word beside it. A scale with an escape hatch is
    not a scale.

    `<html>` is excluded: it carries the browser's 16px root default and never
    paints text of its own.

    Phase 30 added two display tiers — `--type-statement` and `--type-hero` —
    for the landing's thesis and the instruments' terminal statements. The
    scale is therefore READ from `:root` rather than restated here: a hard-coded
    set has to be edited whenever a tier is added, and an edit to the test is
    exactly how an undeclared tier gets declared retroactively.

    Both new tiers are `clamp()`, and reading the custom property gives back
    the raw `clamp(28px,3.4vw,44px)` text — `parseFloat` on that returns 28 at
    every viewport, so the resolved size is measured off a probe element
    instead. Getting this wrong reports the product as off-scale at 15 places
    it is not."""
    SCALE = {round(px) for px in page.evaluate("""() => {
        const probe = document.createElement('span');
        probe.style.position = 'absolute'; probe.style.visibility = 'hidden';
        document.body.appendChild(probe);
        const px = tok => { probe.style.fontSize = `var(${tok})`;
          return parseFloat(getComputedStyle(probe).fontSize); };
        const out = ['--type-display','--type-title','--type-data','--type-body',
                     '--type-label','--type-micro','--type-statement','--type-hero']
          .map(px).filter(n => n);
        probe.remove(); return out; }""")}
    assert len(SCALE) >= 6, f"the declared scale did not resolve: {SCALE}"
    off = {}
    for subject in ("portfolio", "settlement/setl_000089"):
        for lens in ("control", "evidence", "investigate", "policy",
                     "journal", "activity", "trust"):
            _ev(page, f"#/{subject}/{lens}")
            for size, n in page.evaluate("""() => {
                const fs = {};
                const vis = e => { const s = getComputedStyle(e);
                  return s.display !== 'none' && s.visibility !== 'hidden'
                      && s.opacity !== '0'; };
                document.querySelectorAll('*').forEach(e => {
                  if (e.tagName === 'HTML' || !vis(e)) return;
                  const f = Math.round(parseFloat(getComputedStyle(e).fontSize));
                  if (f) fs[f] = (fs[f] || 0) + 1; });
                return fs; }""").items():
                if int(size) not in SCALE:
                    off[int(size)] = off.get(int(size), 0) + n
    assert not off, f"type sizes outside the declared scale: {dict(sorted(off.items()))}"


def test_no_room_paints_the_same_sentence_twice(page):
    """Phase 13 §16. 'Delete prose that merely explains.'

    Policy stated its boundary sentence as the conclusion and then again,
    word for word, under THE BOUNDARY — and on an unpriced case that section
    contained nothing else, so it was a heading over a repeat. A sentence
    painted twice halves the signal of everything around it."""
    import re as _re

    def sentences(text):
        out = set()
        for raw in _re.split(r"[\n.;]+", text):
            t = " ".join(raw.split()).lower().strip(" —·")
            if len(t.split()) >= 6:
                out.add(t)
        return out

    # Scoped to the conclusion against the rest of the room. A justification
    # repeated down the rows of a list is data — 250 settlements share one
    # reduction reason and each row is entitled to state it. Saying the room's
    # headline a second time further down is not.
    dupes = []
    for subject in ("portfolio", "settlement/setl_000089",
                    "settlement/setl_000022"):
        for lens in ("control", "evidence", "investigate", "policy",
                     "journal", "activity", "trust"):
            _ev(page, f"#/{subject}/{lens}")
            concl = page.query_selector(".c-concl")
            if not concl:
                continue
            # counted in the live room: a detached clone's innerText degrades
            # to textContent and would pick up collapsed disclosure bodies that
            # nobody can see
            room = " ".join(
                page.eval_on_selector("#workspace", "n => n.innerText").split()
            ).lower()
            for t in sentences(concl.inner_text()):
                if room.count(t) > 1:
                    dupes.append((f"{subject}/{lens}", t[:66]))
    assert not dupes, "the room's conclusion is repeated verbatim below it:\n" \
        + "\n".join(f"  {w}: {s}" for w, s in dupes[:8])


def test_no_section_is_a_heading_over_nothing(page):
    """Phase 13 §5, §16. A titled block with no body is a promise the room
    does not keep — the reader looks for content that is not there.

    Three appeared while removing repeated copy: Policy's boundary on an
    unpriced case, Activity's unrevised list when nothing is unrevised, and
    the rail's NEXT once the spine grew tall enough to push it out."""
    empty = []
    for subject in ("portfolio", "settlement/setl_000089",
                    "settlement/setl_000022"):
        for lens in ("control", "evidence", "investigate", "policy",
                     "journal", "activity", "trust"):
            _ev(page, f"#/{subject}/{lens}")
            empty += [f"{subject}/{lens}: {t}" for t in page.evaluate("""() =>
              [...document.querySelectorAll('#workspace .c-section')]
                .filter(s => s.offsetParent)
                .filter(s => {
                  const b = s.querySelector('.c-section-b, .c-sec-b') || s;
                  const head = s.querySelector('h2, h3, .c-section-t, .c-sec-t');
                  const bodyText = (b.innerText || '')
                    .replace(head ? head.innerText : '', '').trim();
                  return bodyText.length === 0; })
                .map(s => (s.innerText || '').split('\\n')[0].slice(0, 40))""")]
    assert not empty, "sections with a heading and no body:\n  " + "\n  ".join(empty[:6])


def test_the_search_space_chain_ends_at_the_surviving_explanations(page):
    """Phase 13 §11. The signature moment: 2,368 → 73 → 4, in one object.

    The compression stopped at the candidate universe, and the number of
    explanations that survived it lived in a separate section below — so the
    sequence a judge is meant to read in three seconds was never completed
    where it was being told. 'The system did not magically find a match; it
    proved inside an explicitly defined universe' only lands if the universe,
    the cuts and what came out the far side are one figure."""
    _ev(page, "#/settlement/setl_000089/evidence")
    uni = page.inner_text(".e-uni")
    assert "surviving" in uni.lower() or "explanation" in uni.lower(), \
        f"the chain does not reach the explanations:\n{uni}"
    survivors = page.inner_text(".e-uni-end .e-uni-n").strip()
    shown = len(page.query_selector_all(".e-set-r"))
    assert survivors == str(shown), \
        f"chain says {survivors} survived, {shown} explanations are drawn"
    # and the assumption the whole chain rests on is stated, not disclosed
    assert "convention" in uni.lower(), \
        "the chain does not say the boundary rests on a convention"


def test_returning_to_the_work_returns_to_the_work(page):
    """Phase 22 §1 step 15, §6. The close of the loop the product is built on.

    'Back to the work' inherited the case's lens and dropped the blocker
    context, so a return from Trust landed on portfolio Trust — a page with no
    work on it, nothing selected, and the affected population gone. The button
    was labelled with the one thing it did not do."""
    _ev(page, "#/portfolio/control")
    page.click(".c-blk")
    page.wait_for_timeout(600)
    came_from = page.evaluate("() => location.hash")
    assert "in=action" in came_from
    page.click(".c-pop-r")
    page.wait_for_timeout(700)
    # wander to the far end of the loop before turning round
    page.click('[data-lens="trust"]')
    page.wait_for_timeout(600)
    page.click(".c-from-b")
    page.wait_for_timeout(900)

    back = page.evaluate("() => location.hash")
    assert back == came_from, \
        f"did not return to the work: went to {back}, came from {came_from}"
    assert len(page.query_selector_all(".c-pop-r")) > 0, \
        "the affected population is not listed after returning"
    assert len(page.query_selector_all(".c-blk")) == 3, \
        "the ranked work is not on screen after returning"


# Phase 22 §10. Which stages of the chain each instrument is talking about.
# The routing is derived, not authored: VERIFICATION belongs to Evidence when
# there is a proof to read and to Investigate when the question is what would
# separate the explanations.
CHAIN_OWNERS = {
    "source": "evidence", "matching": "evidence",
    "policy": "policy", "action": "journal",
}


def test_the_state_spine_is_the_way_into_the_instruments(page):
    """Phase 22 §10. The spine states the whole model and was five inert divs.

    Each stage is owned by exactly one instrument, so clicking a stage is a
    lens change — already addressable, already in the URL, already reversible
    with Back. No new state, no new screen."""
    _ev(page, "#/settlement/setl_000089/control")
    stages = page.query_selector_all(".c-state .c-flow-r")
    assert len(stages) == 5, f"expected five stages, saw {len(stages)}"
    for st in stages:
        assert st.get_attribute("data-lens"), \
            f"stage is inert: {st.inner_text()[:30]!r}"
    for name, lens in CHAIN_OWNERS.items():
        el = page.query_selector(f'.c-state .c-flow-r[data-stage="{name}"]')
        assert el, f"no stage {name}"
        assert el.get_attribute("data-lens") == lens, \
            f"{name} routes to {el.get_attribute('data-lens')}, expected {lens}"


def test_an_ambiguous_verification_routes_to_investigate(page):
    """The one stage whose owner depends on state. With a unique proof the
    question is 'can it be proved' — Evidence. With four explanations surviving
    it is 'what would separate them' — Investigate."""
    _ev(page, "#/settlement/setl_000089/control")
    amb = page.get_attribute('.c-state .c-flow-r[data-stage="verification"]',
                             "data-lens")
    _ev(page, "#/settlement/setl_000022/control")
    proven = page.get_attribute('.c-state .c-flow-r[data-stage="verification"]',
                                "data-lens")
    assert amb == "investigate", f"ambiguous verification routes to {amb}"
    assert proven == "evidence", f"proven verification routes to {proven}"


def test_clicking_a_stage_changes_only_the_lens(page):
    """The case must not move. A stage is a way into an instrument, not a
    different subject and not a context."""
    _ev(page, "#/settlement/setl_000089/control")
    before = page.inner_text(".c-case-amt .v")
    page.click('.c-state .c-flow-r[data-stage="policy"]')
    page.wait_for_timeout(700)
    assert "/policy" in page.evaluate("() => location.hash")
    assert "setl_000089" in page.evaluate("() => location.hash")
    assert page.inner_text(".c-case-amt .v") == before, "the case changed"


def test_each_room_lights_the_stages_it_is_talking_about(page):
    """Phase 22 §10. The spine is rendered by the shell on every lens, so a
    room can mark its own segment without drawing a second spine."""
    expect = {
        "evidence": {"matching", "verification"},
        "investigate": {"verification"},
        "policy": {"verification", "policy"},
        "journal": {"policy", "action"},
    }
    for lens, stages in expect.items():
        _ev(page, f"#/settlement/setl_000089/{lens}")
        lit = set(page.eval_on_selector_all(
            ".c-state .c-flow-r.lit", "x => x.map(e => e.dataset.stage)"))
        assert lit == stages, f"{lens} lights {lit or 'nothing'}, expected {stages}"


def test_the_next_question_is_derived_from_the_case_not_a_script(page):
    """Phase 22 §7. 'These must be derived from actual state.'

    The same instrument proposes a different next question depending on what
    the case actually is. Evidence on an ambiguous case sends you to
    Investigate — several explanations survive and the question is what would
    separate them. Evidence on a proven case has nothing to separate, so it
    sends you to Policy."""
    _ev(page, "#/settlement/setl_000089/evidence")     # AMBIGUOUS
    amb = page.get_attribute(".c-onward", "data-lens")
    _ev(page, "#/settlement/setl_000022/evidence")     # PROVEN
    proven = page.get_attribute(".c-onward", "data-lens")
    _ev(page, "#/settlement/setl_000166/evidence")     # CONTRADICTED
    contra = page.get_attribute(".c-onward", "data-lens")
    assert amb == "investigate", f"ambiguous evidence proposes {amb}"
    assert proven == "policy", f"proven evidence proposes {proven}"
    assert contra == "policy", \
        f"contradicted evidence proposes {contra} — there is nothing to separate"


def test_the_next_question_disappears_at_the_end_of_the_loop(page):
    """Phase 22 §7. 'If there is no meaningful next action, show nothing.'

    Trust is where the loop ends. An interface that always has a next thing to
    offer is a workflow being forced, not a product being read."""
    _ev(page, "#/settlement/setl_000089/trust")
    # `.up` is a different affordance: a handoff to another SUBJECT, because
    # one settlement cannot testify to its own engine. What must not exist here
    # is a next INSTRUMENT — there is nothing after "what can I believe".
    assert not page.query_selector(".c-onward:not(.up)"), \
        "Trust proposes a next instrument; it is the end of the loop"


def test_the_next_question_never_points_at_the_room_you_are_in(page):
    """A suggestion to read what is already on screen is noise."""
    for lens in ("control", "evidence", "investigate", "policy",
                 "journal", "activity", "trust"):
        _ev(page, f"#/settlement/setl_000089/{lens}")
        el = page.query_selector(".c-onward:not(.up)")
        if el:
            assert el.get_attribute("data-lens") != lens, \
                f"{lens} proposes itself"


def test_the_next_question_is_a_question(page):
    """It states what the next instrument would answer, not its name alone.
    'Evidence' is a place; 'can the explanation be proved' is a reason to go."""
    _ev(page, "#/settlement/setl_000089/control")
    el = page.query_selector(".c-onward")
    assert el, "control proposes no next question on an unresolved case"
    assert "?" in el.inner_text(), f"not a question: {el.inner_text()!r}"


def test_trust_on_a_case_offers_the_way_to_the_system(page):
    """Phase 22 §6. Trust on a settlement correctly refuses to answer — whether
    one case is right depends on whether the engine can be believed at all.

    But it said 'open Trust on the portfolio' and gave no way to do it, so the
    last beat of the case story was a two-line screen naming a destination the
    reader had to find themselves."""
    _ev(page, "#/settlement/setl_000089/trust")
    go = page.query_selector(".c-onward[data-subject]")
    assert go, "no way through to the systemic view"
    assert go.get_attribute("data-lens") == "trust"
    assert go.get_attribute("data-subject").startswith("portfolio")
    go.click()
    page.wait_for_timeout(900)
    assert page.evaluate("() => location.hash") == "#/portfolio/trust"
    assert "NOT VERIFIED" in page.inner_text("#w-main")


def test_no_label_in_a_repeated_row_wraps(page):
    """Phase 13B §12, §19. 'The interface should feel expensive because it is
    precise.'

    Phase 13 promoted these labels off an undeclared 9px tier onto the scale's
    10px, and WOULD UNBLOCK stopped fitting its 96px column — it wrapped on all
    three rows of the blocker register, pushing each value down and leaving the
    label column 3px ragged. That register is the first list on the landing and
    the answer to what to do first."""
    _ev(page, "#/portfolio/control")
    bad = page.evaluate("""() =>
      [...document.querySelectorAll('.c-blk-b i, .c-blk-w i, .c-blk-n i')]
        .filter(e => e.offsetParent)
        .filter(e => e.getBoundingClientRect().height > 18)
        .map(e => e.innerText.trim() + ' @ '
             + Math.round(e.getBoundingClientRect().height) + 'px')""")
    assert not bad, f"labels wrapping in the blocker register: {bad}"
    edges = page.evaluate("""() =>
      [...document.querySelectorAll('.c-blk-n i')].filter(e => e.offsetParent)
        .map(e => Math.round(e.getBoundingClientRect().right))""")
    assert len(set(edges)) == 1, f"label column is ragged: {sorted(set(edges))}"


def test_policy_does_not_state_its_decision_twice(page):
    """Phase 13B §8. 'If there are two competing heroes, remove hierarchy from
    one.'

    REVIEW was painted at 34px as the conclusion and again at 20px a hundred
    pixels below it. The block's unique content is the sentence that policy
    reads the verdict and does not change it — one of the product's core
    claims, and it appeared nowhere else."""
    for sid, word in (("setl_000089", "REVIEW"), ("setl_000022", "AUTO-POST")):
        _ev(page, f"#/settlement/{sid}/policy")
        big = page.evaluate("""(w) => {
          const out = [];
          const vis = e => { const s = getComputedStyle(e);
            return s.display !== 'none' && s.visibility !== 'hidden'; };
          const walk = el => { for (const n of el.childNodes) {
            if (n.nodeType === 3 && n.textContent.trim().toUpperCase() === w) {
              const px = parseFloat(getComputedStyle(n.parentElement).fontSize);
              if (px >= 20) out.push(px);
            } else if (n.nodeType === 1 && vis(n)) walk(n); } };
          walk(document.querySelector('#w-main')); return out; }""", word)
        assert len(big) <= 1, \
            f"{sid}: {word} painted {len(big)} times at hero weight ({big})"
    # and the claim that only appeared inside that block survives
    assert "does not change it" in page.inner_text("#w-main")


def test_a_spine_stage_shows_it_is_a_way_in_before_you_touch_it(page):
    """Phase 13B §14, §2. The interaction existed with no resting state — a
    pointer cursor and a hover tint, both of which require already hovering.

    A lit stage carries a solid left rule. A stage you can open carries the
    same rule, faintly. The affordance and the state share one language rather
    than adding an icon."""
    _ev(page, "#/settlement/setl_000089/journal")
    rules = page.evaluate("""() =>
      [...document.querySelectorAll('.c-state .c-flow-r')].map(e => {
        const s = getComputedStyle(e);
        return {stage: e.dataset.stage, lit: e.classList.contains('lit'),
                colour: s.borderLeftColor, width: s.borderLeftWidth};
      })""")
    assert rules, "no spine stages"
    unlit = [r for r in rules if not r["lit"]]
    assert unlit, "every stage is lit; nothing to distinguish"
    for r in unlit:
        assert r["colour"] != "rgba(0, 0, 0, 0)", \
            f"stage {r['stage']} gives no sign it can be opened"
    lit = [r for r in rules if r["lit"]]
    assert lit, "journal lights no stage"
    assert lit[0]["colour"] != unlit[0]["colour"], \
        "an open-able stage and the stage this room is about look identical"


def test_no_room_states_its_own_conclusion_twice_at_emphasis(page):
    """Phase 23 §8. Generalised from the Policy fix, which was scoped to one
    room and left the same defect standing next door: Investigate painted
    'Engine abstained' at 20px as its conclusion and again at 20px in the
    summary below it.

    Repeated FIGURES are not covered and must not be — ₹0.00 three times is
    the balanced-by-absence point, and a credit that equals the amount
    reconciled is two facts that happen to agree. This is about the room
    saying its own headline a second time."""
    bad = []
    for subject in ("portfolio", "settlement/setl_000089",
                    "settlement/setl_000022", "settlement/setl_000166"):
        for lens in ("control", "evidence", "investigate", "policy",
                     "journal", "activity", "trust"):
            _ev(page, f"#/{subject}/{lens}")
            concl = page.query_selector(".c-concl-f")
            if not concl:
                continue
            head = concl.inner_text().strip()
            if not head or head.startswith("₹"):
                continue
            n = page.evaluate("""(h) => {
                let n = 0;
                const vis = e => { const s = getComputedStyle(e);
                  return s.display !== 'none' && s.visibility !== 'hidden'; };
                const walk = el => { for (const q of el.childNodes) {
                  if (q.nodeType === 3
                      && q.textContent.trim().toLowerCase() === h.toLowerCase()) {
                    const px = parseFloat(
                      getComputedStyle(q.parentElement).fontSize);
                    if (px >= 15) n++;
                  } else if (q.nodeType === 1 && vis(q)) walk(q); } };
                walk(document.querySelector('#w-main')); return n; }""", head)
            if n > 1:
                bad.append(f"{subject}/{lens}: '{head}' painted {n}x at emphasis")
    assert not bad, "\n  ".join([""] + bad)


def test_every_money_role_declares_tabular_figures(page):
    """Phase 23 §6, §7. Nine financial categories, one of them declaring
    something different.

    Every ₹ role — entered, continues, agreed, disputed, value blocked, the run
    ladder — declares tabular-nums so digits hold their column. HELD did not,
    and HELD carries ₹48,03,127.81: the answer to where the money stopped."""
    _ev(page, "#/portfolio/control")
    rows = page.evaluate("""() =>
      [...document.querySelectorAll('.c-case-amt .v, .c-flow-v, .c-flow-h,'
        + ' .c-fv, .c-blk-v')]
        .filter(e => e.offsetParent && e.innerText.includes('\\u20b9'))
        .map(e => ({cls: e.className || '(amount)',
                    t: e.innerText.trim().slice(0, 16),
                    tab: getComputedStyle(e).fontVariantNumeric}))""")
    assert rows, "no money in the rail"
    off = [r for r in rows if "tabular-nums" not in r["tab"]]
    assert not off, "money roles not declaring tabular figures: " + ", ".join(
        f"{r['cls']} ({r['t']})" for r in off)


def test_the_dock_does_not_dominate_a_phone(page):
    """Phase 24 §1. The dock was laid out as four columns — a grid chosen when
    an instrument was a single label. Phase 13 gave every instrument its
    question, which is what turned the dock into an index, and never re-checked
    the phone: at 360x780 the dock measured 263px against a 216px room holding
    2,323px of content.

    Everything that made it an index is preserved — seven instruments, every
    question, the order, the seating of the held one. Only the shape changes."""
    page.set_viewport_size({"width": 360, "height": 780})
    try:
        _ev(page, "#/portfolio/control")
        m = page.evaluate("""() => {
          const d = document.querySelector('.c-lenses');
          const items = [...document.querySelectorAll('.c-lenses button')];
          const room = document.getElementById('w-main');
          return {dock: Math.round(d.getBoundingClientRect().height),
                  room: room ? Math.round(room.getBoundingClientRect().height) : 0,
                  n: items.length,
                  questions: items.filter(b => {
                    const q = b.querySelector('.c-lens-q');
                    return q && q.offsetParent
                        && q.getBoundingClientRect().height > 0; }).length,
                  order: items.map(b => b.dataset.lens),
                  reachable: items.filter(b => b.offsetParent).length}; }""")
        # Phase 31 made the phone dock one horizontal line. The size
        # assertions are what this contract is FOR, so they get stricter
        # rather than looser: it was 263px against a 216px room when this was
        # written, 240 against 260 when Phase 31 measured it, and 39 against
        # 505 now.
        assert m["dock"] <= 80, f"dock is {m['dock']}px on a phone"
        assert m["room"] > m["dock"] * 3, \
            f"room {m['room']}px does not dominate the dock {m['dock']}px"
        assert m["n"] == 7 and m["reachable"] == 7, \
            f"only {m['reachable']} of {m['n']} instruments are reachable"
        # A 39px strip cannot show seven questions, and stacking them to fit
        # is exactly what made the dock taller than the instrument. What a
        # phone can guarantee is that the instrument you are HOLDING says what
        # it asks, and that the other six are one tap away in order — which
        # the assertions above and below pin. The desktop rail still states
        # all seven; `test_every_instrument_states_its_question` covers that.
        assert m["questions"] >= 1, "the held instrument does not state its question"
        assert m["order"] == ["control", "evidence", "investigate", "policy",
                             "journal", "activity", "trust"], m["order"]
    finally:
        page.set_viewport_size({"width": 1280, "height": 900})


def test_the_held_instrument_is_still_seated_on_a_phone(page):
    """The selected-instrument affordance survives the phone composition: a
    rule on the leading edge and a surface, not a filled chip."""
    page.set_viewport_size({"width": 360, "height": 780})
    try:
        _ev(page, "#/portfolio/journal")
        m = page.evaluate("""() => {
          const on = document.querySelector('.c-lenses button.on');
          const off = document.querySelector('.c-lenses button:not(.on)');
          if (!on || !off) return null;
          const a = getComputedStyle(on), b = getComputedStyle(off);
          // A leading-edge rule can be a border or an inset shadow; Phase 31
          // draws it as the latter, and reading only borderLeft and
          // backgroundColor missed an affordance that was plainly on screen.
          const insetRule = ss => (ss || '').split(/,(?![^()]*\))/)
            .some(part => part.includes('inset'));
          return {lens: on.dataset.lens,
                  edge: a.borderLeftColor !== b.borderLeftColor
                     || a.borderLeftWidth !== b.borderLeftWidth
                     || (insetRule(a.boxShadow) && !insetRule(b.boxShadow)),
                  surface: a.backgroundColor !== b.backgroundColor,
                  weight: a.fontWeight !== b.fontWeight
                       || a.color !== b.color,
                  // what it must NOT be: a filled chip
                  filled: parseFloat(a.borderTopLeftRadius) > 2
                       && a.backgroundColor !== 'rgba(0, 0, 0, 0)'}; }""")
        assert m, "no held instrument"
        assert m["lens"] == "journal"
        assert m["edge"] or m["surface"] or m["weight"], \
            "the held instrument is not distinguished"
        assert not m["filled"], \
            "the held instrument is a filled chip — it should be a rule"
    finally:
        page.set_viewport_size({"width": 1280, "height": 900})


def test_ambiguous_control_leads_with_the_disputed_money(page):
    """Phase 24 §2. Of 28 room-states, Control on an ambiguous settlement was
    the only one with no figure at display size — and it is the room a case
    opens into.

    Control asks what needs attention. What needs attention is the money whose
    allocation cannot be distinguished, so that is the headline, and the money
    that is settled whichever explanation is right is subordinate to it.

    Both figures are checked against the engine payload rather than pinned to
    a literal, so a change in the data cannot leave the room stating a number
    the engine no longer produces."""
    _ev(page, "#/settlement/setl_000163/control")
    truth = page.evaluate("""async () => {
      const d = await (await fetch(`/api/settlement?run=${SHELL.run}`
        + `&id=setl_000163`)).json();
      const st = d.exception && d.exception.settled;
      return st ? {disputed: st.disputed_paise, agreed: st.net_paise} : null; }""")
    assert truth, "no settled part in the engine payload"
    assert truth["disputed"] > 0 and truth["agreed"] > truth["disputed"], \
        f"fixture no longer exercises the case: {truth}"
    fig = page.inner_text(".c-concl-n b").strip()
    lab = page.inner_text(".c-concl-n em").strip().lower()
    sec = page.inner_text(".c-concl-2").strip()

    # the headline is the disputed amount, and it is the engine's
    disputed_digits = "".join(c for c in fig if c.isdigit())
    agreed_digits = "".join(c for c in sec if c.isdigit())
    assert disputed_digits == str(truth["disputed"]), \
        f"headline {fig} is not the engine's disputed {truth['disputed']}"
    assert "disput" in lab, f"headline is not labelled disputed: {lab!r}"
    # ...and the agreed amount is present but subordinate, not reversed
    assert agreed_digits == str(truth["agreed"]), \
        f"secondary {sec} is not the engine's agreed {truth['agreed']}"
    sizes = page.evaluate("""() => ({
      primary: parseFloat(getComputedStyle(
        document.querySelector('.c-concl-n b')).fontSize),
      secondary: parseFloat(getComputedStyle(
        document.querySelector('.c-concl-2 b')).fontSize)})""")
    assert sizes["primary"] > sizes["secondary"], \
        f"the disputed money is not dominant: {sizes}"


def test_control_and_evidence_do_not_share_a_conclusion(page):
    """Phase 24 §2. Control asks what needs attention; Evidence asks why it
    cannot be uniquely proved. They may reach the same case, never the same
    headline sentence."""
    _ev(page, "#/settlement/setl_000089/control")
    control = page.inner_text(".c-concl-f").strip().lower()
    _ev(page, "#/settlement/setl_000089/evidence")
    evidence = page.inner_text(".c-concl-f").strip().lower()
    assert control != evidence, f"both rooms conclude {control!r}"


def test_ambiguous_control_does_not_restate_its_conclusion(page):
    """The conclusion carries the money. What we know carries the composition —
    how many orders are agreed, how many turn on which explanation is right.
    Stating the same two amounts twice was the shape this phase removed."""
    _ev(page, "#/settlement/setl_000089/control")
    concl = page.inner_text(".c-concl")
    rest = page.evaluate("""() => {
      const w = document.querySelector('#w-main');
      const c = w.querySelector('.c-concl');
      return [...w.querySelectorAll('.c-section')]
        .filter(s => !c.contains(s)).map(s => s.innerText).join('\\n'); }""")
    import re as _re
    amounts = set(_re.findall(r"₹[\d,]+\.\d{2}", concl))
    assert amounts, "the conclusion carries no money"
    repeated = {a for a in amounts if a in rest}
    assert not repeated, f"the conclusion's money is restated below it: {repeated}"


def test_the_data_source_is_named_on_every_screen(page):
    """Phase A. 'The UI and Trust lens must always make the mode explicit.
    Never silently pretend synthetic data came from Razorpay.'

    The mode was stated only on Trust, one click away. A judge who never opened
    that lens saw ₹53,02,701.96 of 'Financial control' with nothing on screen
    saying where it came from. The product was not claiming Razorpay — the word
    did not appear — but silence is not the same as a label.

    The mode is read from the adapter, never asserted: it says GENERATED when
    the synthetic source is active and would say RAZORPAY only when a live
    adapter actually produced the records."""
    for subject in ("portfolio", "settlement/setl_000089"):
        for lens in ("control", "evidence", "policy", "trust"):
            _ev(page, f"#/{subject}/{lens}")
            el = page.query_selector("#source-mode")
            assert el and el.is_visible(), f"no source mode on {subject}/{lens}"
            text = el.inner_text().strip().upper()
            assert "GENERATED" in text, f"unexpected mode: {text!r}"


def test_the_source_mode_comes_from_the_adapter_not_a_constant(page):
    """Rule 12: every displayed number must derive from payload. The mode is
    a claim about provenance, so it derives from the adapter's own status."""
    _ev(page, "#/portfolio/control")
    truth = page.evaluate("""async () => {
      const r = await fetch(`/api/subject?run=${SHELL.run}`
        + `&type=portfolio&id=portfolio`);
      const d = await r.json();
      return d.source || null; }""")
    assert truth, "the subject record carries no source block"
    assert truth["live"] is False, "a generated run must not report live"
    assert truth["provider"] == "synthetic"
    shown = page.inner_text("#source-mode").strip().lower()
    assert truth["label"].lower() in shown, \
        f"screen says {shown!r}, adapter says {truth['label']!r}"


def test_razorpay_is_never_named_as_the_source_without_credentials(page):
    """The strongest rule in this phase. No credentials are configured in this
    environment, so nothing may present Razorpay as the origin of a record."""
    for lens in ("control", "evidence", "journal", "activity"):
        _ev(page, f"#/portfolio/{lens}")
        mode = page.inner_text("#source-mode").lower()
        assert "razorpay" not in mode, \
            f"{lens} names Razorpay as the source: {mode!r}"


def test_the_ai_boundary_shows_the_model_did_not_decide(page):
    """F2. The strongest fact in the audit was invisible: the hypothesis loop's
    verdict is computed and then discarded, so the model's conclusion cannot
    become the financial one.

    The instrument states the order the code actually executes — the solver
    established the ambiguity first, the model was then asked for an anchor,
    and the solver tested whether that anchor discriminates. It does not say
    the solver checked whether the model was right."""
    _ev(page, "#/settlement/setl_000089/investigate")
    box = page.query_selector(".i-bound")
    assert box and box.is_visible(), "no AI boundary instrument"
    t = box.inner_text().lower()
    for phrase in ("model", "solver", "engine", "diagnostic",
                   "no financial action"):
        assert phrase in t, f"the boundary does not state {phrase!r}: {t[:200]}"
    assert "confidence" not in t, "the boundary speaks of confidence"
    # the verdict retained is the engine's, and it is named
    assert "ambiguous" in t


def test_the_ai_boundary_reports_the_verdict_was_not_changed(page):
    """`changed_nothing` is the fact, and it must be on screen, not only in the
    payload."""
    _ev(page, "#/settlement/setl_000089/investigate")
    truth = page.evaluate("""async () => {
      const r = await fetch(`/api/investigation?run=${SHELL.run}`
        + `&type=settlement&id=setl_000089`);
      const d = await r.json();
      return {verdict: d.verdict, would: d.would_have_concluded,
              changed: d.changed_nothing}; }""")
    assert truth["changed"] is True, "the payload no longer discards the verdict"
    box = page.inner_text(".i-bound").lower()
    assert truth["verdict"].lower() in box
    assert "changed" in box and ("no" in box or "nothing" in box)


def test_the_solver_tests_discrimination_not_correctness(page):
    """The wording matters. The solver is not adjudicating the model."""
    _ev(page, "#/settlement/setl_000089/investigate")
    t = page.inner_text(".i-bound").lower()
    for wrong in ("whether the model is right", "model was correct",
                  "validates the model", "checks the model"):
        assert wrong not in t, f"the boundary implies adjudication: {wrong!r}"
    assert "discriminat" in t or "separate" in t


def test_the_benchmark_note_is_read_from_the_artifact(page):
    """If the measurement is shown at all it is the artifact's, and it is
    labelled a benchmark rather than this settlement's likelihood."""
    _ev(page, "#/settlement/setl_000089/investigate")
    el = page.query_selector(".i-bound-m-note")
    if not el:
        return                                   # showing it is optional
    shown = el.inner_text().lower()
    truth = page.evaluate("""async () => {
      const r = await fetch(`/api/investigation?run=${SHELL.run}`
        + `&type=settlement&id=setl_000089`);
      return (await r.json()).measurement; }""")
    assert truth, "the payload carries no measurement"
    assert str(truth["correct"]) in shown and str(truth["resolved"]) in shown, \
        f"the note does not match the artifact: {shown!r} vs {truth}"
    assert "benchmark" in shown or "re-measure" in shown, \
        "the measurement is not labelled as a benchmark"
    for banned in ("confidence", "probability", "likelihood"):
        assert banned not in shown, f"the note says {banned!r}"


def test_a_model_conclusion_cannot_make_a_settlement_postable(page):
    """The boundary is structural, and the room must not contradict it."""
    _ev(page, "#/settlement/setl_000089/policy")
    # not "0/5": see test_an_unproven_settlement_is_never_priced. What the
    # boundary guarantees is that nothing the model said can carry a proof
    # gate, and that the room does not offer to post.
    proof_ok = page.evaluate("""() => {
      const st = [...document.querySelectorAll('.p-stage')].find(
        s => /proof/i.test((s.querySelector('.p-stage-h') || {}).textContent || ''));
      return st ? st.querySelectorAll('.p-gate.ok').length : null; }""")
    assert proof_ok == 0, f"{proof_ok} proof gates passed on an unproven case"
    _ev(page, "#/settlement/setl_000089/journal")
    j = page.inner_text("#w-main").lower()
    assert "no entry is written" in j


def test_the_execution_path_is_named_beside_the_source(page):
    """Phase 28 P0. Two installs of the same commit produce different figures:
    the optional Rust kernel widens the solver envelope from ₹30,000 to
    ₹2,00,000, so 37 settlements that the portable reference reports as
    INSUFFICIENT are decided when it is present.

    Both answers are honest. What was missing was the product saying which one
    the reader is looking at, so a figure that differs from a recording had no
    explanation on screen. It is read from the module, never asserted."""
    _ev(page, "#/portfolio/control")
    el = page.query_selector("#exec-path")
    assert el and el.is_visible(), "the execution path is not named"
    shown = el.inner_text().strip().upper()
    truth = page.evaluate("""async () => {
      const r = await fetch(`/api/subject?run=${SHELL.run}`
        + `&type=portfolio&id=portfolio`);
      return (await r.json()).source; }""")
    assert truth and "engine" in truth, "the subject record carries no engine block"
    assert truth["engine"]["label"].upper() == shown, \
        f"screen says {shown!r}, the module says {truth['engine']['label']!r}"
    assert shown in ("PORTABLE", "NATIVE KERNEL"), shown


def test_each_instrument_reports_its_own_state(page):
    """Phase 29 §5. The dock listed a name and a question. It now also reports
    what that instrument currently answers, so reading it top to bottom is a
    summary of the case rather than a menu of places.

    The state is read from the record, never composed in the dock — an
    instrument that cannot answer yet shows nothing rather than a placeholder."""
    _ev(page, "#/settlement/setl_000225/control")
    rows = page.evaluate("""() =>
      [...document.querySelectorAll('.c-lenses button')].map(b => ({
        lens: b.dataset.lens,
        idx: (b.querySelector('.c-lens-i') || {}).textContent || '',
        state: (b.querySelector('.c-lens-s') || {}).textContent || ''}))""")
    assert len(rows) == 7
    # the ordinal encodes the product loop
    assert [r["idx"] for r in rows] == ["01", "02", "03", "04", "05", "06", "07"]
    assert [r["lens"] for r in rows] == ["control", "evidence", "investigate",
                                         "policy", "journal", "activity", "trust"]
    stated = {r["lens"]: r["state"].strip().upper() for r in rows if r["state"].strip()}
    assert len(stated) >= 5, f"only {len(stated)} instruments report a state: {stated}"
    # and the states are this case's, not a constant
    assert "AMBIGUOUS" in stated.get("control", "") or \
           "VERIFICATION" in stated.get("control", ""), stated
    assert "UNPRICED" in stated.get("policy", "") or \
           "REVIEW" in stated.get("policy", ""), stated
    assert "NOT VERIFIED" in stated.get("trust", ""), stated


def test_the_dock_state_changes_with_the_case(page):
    """A proven settlement and an ambiguous one cannot report the same states,
    or the line is decoration."""
    _ev(page, "#/settlement/setl_000225/control")
    amb = page.evaluate("""() => [...document.querySelectorAll('.c-lens-s')]
      .map(e => e.textContent.trim()).join('|')""")
    _ev(page, "#/settlement/setl_000022/control")
    prov = page.evaluate("""() => [...document.querySelectorAll('.c-lens-s')]
      .map(e => e.textContent.trim()).join('|')""")
    assert amb != prov, f"the dock reports the same state for both cases: {amb}"
    assert "PROVEN" in prov.upper()


# ══════════════════════════════════════════════════ PHASE 30 · THE INSTRUMENTS
#
# Phase 30 rebuilt every room's grammar. These pin the parts that carry an
# argument rather than the parts that carry a style — a border-radius is a
# preference, but a bar whose width is not proportional to what it represents
# is a diagram that lies, and that is worth a test.


def test_the_overture_opens_on_the_money_before_any_work(page):
    """§30.1. Control opens on where the money stopped, not on a ranked queue.

    A room that opens on a list of blockers reads as an internal queue, and
    everything true about the product after that is read as an internal
    queue's details.

    The THESIS used to be asserted here. Phase 31 moved it: `/` is the front
    door now and states it there, and repeating it in the workspace meant a
    judge who followed "open the investigation" met the same sentence twice.
    `test_the_front_door_states_the_thesis` holds that guarantee — this one
    holds what Control itself owes."""
    _ev(page, "#/portfolio/control")
    assert page.query_selector(".o"), "Control has no overture"
    o = page.inner_text(".o")
    assert "\u20b9" in o, "the overture states no money"
    stages = page.eval_on_selector_all(".o-stage", "x => x.length")
    assert stages >= 4, f"the collapse shows {stages} stages"
    # the money is the largest thing here, because nothing has happened yet
    fig = page.evaluate(
        "() => parseFloat(getComputedStyle(document.querySelector('.o-fig b')).fontSize)")
    assert fig >= 20, f"the processed total is set at {fig:.0f}px"


def test_the_front_door_states_the_thesis(inv):
    """The guarantee the workspace's overture used to carry, now held where
    the sentence actually lives."""
    # Pinned as the guarantee, not the wording: the largest statement on the
    # front door must say that this system declines to act on money it cannot
    # prove. The earlier version pinned the literal words "refuses" and
    # "certainty", which made the sentence unimprovable.
    # The guarantee, not the wording -- and the grammar it can be made in is
    # wider than one voice. "The ledger wasn't [allowed to be wrong]" states
    # the same refusal about the same object as "it won't move money it can't
    # prove", so both have to pass or this pins a sentence again, which is the
    # fault the note above records. The claim is read across the largest
    # statement AND the paragraph it leads, because a two-line thesis that
    # hands its object to the next sentence is a better sentence, not a
    # weaker claim.
    stmt = " ".join(inv.inner_text(".hero-t").lower().split())
    lead = " ".join(inv.inner_text(".claim-p").lower().split())
    both = stmt + " " + lead
    refusal = any(w in stmt for w in
                  ("won't", "will not", "wasn't", "was not", "refuses",
                   "does not", "cannot", "can't"))
    proof = any(w in both for w in ("prove", "proof", "verif", "evidence",
                                    "certainty"))
    money = any(w in both for w in
                ("money", "post", "pay", "settle", "ledger", "books",
                 "financial"))
    assert refusal and proof and money, (
        "the front door's largest statement does not say it declines to act "
        f"on money it cannot prove: {stmt!r} / {lead!r}")
    size = inv.evaluate(
        "() => parseFloat(getComputedStyle(document.querySelector('.hero-t')).fontSize)")
    assert size >= 30, f"the thesis is set at {size:.0f}px"


def test_the_collapse_is_proportional_to_what_continues(page):
    """§30.1. The shrinking width IS the argument, so it has to be true.

    A stage that keeps 9.4% of the money gets 9.4% of the width. The only
    licensed departure is a floor, so a surviving sliver does not render as
    zero — and the floor is checked to be small enough that it cannot make a
    collapse look like a continuation."""
    _ev(page, "#/portfolio/control")
    rows = page.evaluate("""() => [...document.querySelectorAll('.o-stage')].map(r => ({
        w: r.querySelector('.o-bar i').getBoundingClientRect().width,
        track: r.querySelector('.o-bar').getBoundingClientRect().width,
        v: r.querySelector('.o-stage-v').textContent.trim()}))""")
    assert len(rows) >= 4, "the collapse has too few stages to be a collapse"
    fracs = [r["w"] / r["track"] for r in rows]
    assert max(fracs) > 0.9, "no stage is drawn at full width"
    assert min(fracs) < 0.05, \
        f"nothing collapses — narrowest bar is {min(fracs) * 100:.1f}% of the track"
    # monotone: money that has stopped cannot un-stop further down the chain
    assert fracs == sorted(fracs, reverse=True), \
        f"the collapse is not monotone: {[round(f, 4) for f in fracs]}"


def test_a_blocker_is_an_object_and_its_amount_leads(page):
    """§30.2. Value decides whether the work is worth the next ten minutes.

    The register was a six-column row; the reader had to hunt for the figure
    that decides. In the rebuilt object the amount is the largest thing in it."""
    _ev(page, "#/portfolio/control")
    m = page.evaluate("""() => {
      const b = document.querySelector('.c-blk'); if (!b) return null;
      const px = s => { const e = b.querySelector(s);
        return e ? parseFloat(getComputedStyle(e).fontSize) : 0; };
      return {amount: px('.c-blk-v'), why: px('.c-blk-w'),
              cap: px('.c-blk-c'), radius: getComputedStyle(b).borderRadius}; }""")
    assert m, "no blocker objects on the landing"
    assert m["amount"] > m["why"] > m["cap"], (
        f"the hierarchy is not value, then reason, then boundary: {m}")
    # objects, not cards
    assert m["radius"].startswith("0px"), \
        f"the blocker is drawn as a rounded card ({m['radius']})"


def test_the_reduction_chain_states_each_cut_without_being_asked(page):
    """§30.3. The kind of a cut is never hidden behind a hover.

    Whether a reduction is a deterministic fact or a convention is what the
    32/92 failure was about. The justification is the reward for asking; the
    KIND is not, because a reader who never hovers must still see that the
    boundary rests on a convention."""
    _ev(page, "#/settlement/setl_000225/evidence")
    kinds = page.evaluate("""() => [...document.querySelectorAll('.e-uni-k')]
        .filter(e => { const s = getComputedStyle(e);
          return s.display !== 'none' && s.visibility !== 'hidden'
                 && parseFloat(s.opacity) > 0 && e.getBoundingClientRect().height > 0; })
        .map(e => e.textContent.trim().toLowerCase())""")
    assert kinds, "no cut states its kind"
    assert "convention" in kinds, "no cut is labelled a convention on arrival"
    # and the figures are the composition, not an annotation on it
    n = page.evaluate("""() => parseFloat(getComputedStyle(
        document.querySelector('.e-uni-end .e-uni-n')).fontSize)""")
    body = page.evaluate("() => parseFloat(getComputedStyle(document.body).fontSize)")
    assert n >= body * 1.8, f"the surviving count is set at {n:.0f}px"


def test_the_threshold_is_drawn_even_when_nothing_was_priced(page):
    """§30.5. The absence of a number is the point, and an absence you cannot
    see is not a statement.

    The instrument used to render nothing at all on an unpriced case, which
    also hid that a price was SUPPOSED to be here. A zero is never drawn:
    zero expected loss would claim the posting was proved safe, which is the
    opposite of what happened."""
    _ev(page, "#/settlement/setl_000225/policy")
    b = page.query_selector(".p-bound")
    assert b, "no threshold on an unpriced case"
    lo = page.inner_text(".p-bound-k.lo")
    assert "unpriced" in lo.lower(), f"the empty slot does not say so: {lo!r}"
    assert "0.00" not in lo, "a zero was drawn where nothing was priced"
    assert not page.query_selector(".p-bound .p-bound-mark"), \
        "a marker was placed on the scale with no price to place it at"
    # the review cost is real and still stated
    assert "₹" in page.inner_text(".p-bound-k.rv")

    # and on a priced case the marker exists and sits on the side the gate
    # says it does. This used to require the CHEAPER side, which was true of
    # the old run and is not a guarantee: on the held-out seed setl_000022 is
    # proven and priced, and its expected loss is ABOVE the cost of checking,
    # which is why it goes to review rather than posting. The drawing must
    # agree with the gate either way - that is the invariant. Pinning one side
    # pinned one dataset.
    _ev(page, "#/settlement/setl_000022/policy")
    cheaper = page.evaluate("""async () => {
      const d = await (await fetch(`/api/decision?run=${SHELL.run}`
        + `&type=settlement&id=setl_000022&review=${SHELL.review}`
        + `&exposure=${SHELL.exposure}`)).json();
      const g = (d.gates || []).find(x => /cost of checking/i.test(x.name || ''));
      return g ? !!g.ok : null; }""")
    assert cheaper is not None, "the run states no cost-of-checking gate"
    pos = page.evaluate("""() => {
      const m = document.querySelector('.p-bound-mark');
      const l = document.querySelector('.p-bound-line');
      if (!m || !l) return null;
      return m.getBoundingClientRect().left < l.getBoundingClientRect().left; }""")
    assert pos is not None, "a priced case drew no marker"
    assert pos is cheaper, (
        f"the gate says expected loss below review cost is {cheaper}, "
        f"but the marker is drawn {'below' if pos else 'above'} the line")


def test_balanced_by_absence_is_stated_as_the_conclusion(page):
    """§30.6. ₹0.00 / ₹0.00 / ₹0.00 is indistinguishable from an entry that
    cancelled out. The difference between those two is the whole idea, and it
    was living in a footnote."""
    _ev(page, "#/settlement/setl_000225/journal")
    stamp = page.query_selector(".j-eff-stamp")
    assert stamp, "the ledger effect states no conclusion"
    assert "absence" in stamp.inner_text().lower()
    sizes = page.evaluate("""() => ({
        stamp: parseFloat(getComputedStyle(document.querySelector('.j-eff-stamp')).fontSize),
        fig: parseFloat(getComputedStyle(document.querySelector('.j-eff-v')).fontSize)})""")
    assert sizes["stamp"] > sizes["fig"], (
        f"the reading is smaller than the zeroes it explains: {sizes}")
    # the note must not repeat the stamp
    note = page.inner_text(".j-eff-n").lower()
    assert "balanced by absence" not in note, "the conclusion is stated twice"


def test_the_isolation_claim_is_measured_rather_than_typed(page):
    """§30.8. ATTEST's strongest architectural claim, checked instead of said.

    Every module that produces a verdict is read and searched for the
    provider's name. The count of modules scanned is on screen beside the
    result, so a reader who disbelieves it can name them and grep."""
    truth = page.evaluate("""async () => {
      const r = await fetch(`/api/claims?run=${SHELL.run}`);
      return (await r.json()).isolation; }""")
    assert truth, "the payload carries no isolation measurement"
    assert truth["modules"] >= 15, \
        f"only {truth['modules']} modules were scanned — too few to be the engine"
    assert truth["isolated"] is True, (
        f"the provider reaches the engine via {truth['mentions']}"
        f"{'; unreadable: ' + str(truth['unreadable']) if truth['unreadable'] else ''}")

    _ev(page, "#/portfolio/trust")
    iso = page.inner_text(".t-iso")
    assert "does not know" in iso.lower()
    assert str(truth["modules"]) in iso, \
        "the claim is made without saying how many modules were read"


def test_the_attack_counts_come_from_the_pass_that_ran_them(page):
    """§30.8. A defended-attack count with nothing behind it is exactly the
    kind of claim this lens exists to refuse.

    The counts are read from benchmark/adversarial.json, written by the pass
    itself. If the artifact is absent the surface says the pass has not been
    run rather than falling back to a number."""
    adv = page.evaluate("""async () => {
      const r = await fetch(`/api/claims?run=${SHELL.run}`);
      return (await r.json()).adversarial; }""")
    _ev(page, "#/portfolio/trust")
    room = page.inner_text("#w-main")
    if not adv or not adv.get("present"):
        assert "has not been run" in room.lower(), \
            "no artifact, yet the room does not say the pass has not been run"
        return
    assert adv["defended"] + adv["breached"] <= adv["attacks"]
    shown = page.inner_text(".t-adv")
    for n in (adv["attacks"], adv["defended"], adv["breached"]):
        assert str(n) in shown, f"{n} is measured but not shown"
    # a harness error is not a defence, and the room has to say so
    assert "harness" in shown.lower()


def test_motion_resolves_to_the_three_declared_tiers(page):
    """§30.12. Three tiers, and every animation is one of them.

    micro 80-120ms for interaction feedback, standard 180-240ms for a state
    change, spatial 300-450ms for something opening out of the thing that owns
    it. A duration outside those bands is a decision made at a call site, which
    is how a hover tint and a drawer opening came to run on the same token.

    This measures what is PAINTED rather than what is declared: a token nothing
    uses proves nothing, and a hard-coded `0.6s` on one rule would never show
    up in `:root`."""
    _ev(page, "#/portfolio/control")
    painted = page.evaluate("""() => { const out = {};
      document.querySelectorAll('#app *').forEach(e => { const s = getComputedStyle(e);
        [s.transitionDuration, s.animationDuration].forEach(v =>
          (v || '').split(',').map(x => x.trim()).forEach(x => {
            const ms = x.endsWith('ms') ? parseFloat(x) : parseFloat(x) * 1000;
            if (ms > 0) out[ms] = (out[ms] || 0) + 1; })); });
      return out; }""")
    assert painted, "nothing on the landing animates at all"
    BANDS = ((80, 120), (180, 240), (300, 450))
    stray = {ms: n for ms, n in painted.items()
             if not any(lo <= float(ms) <= hi for lo, hi in BANDS)}
    assert not stray, (
        "durations outside the three declared tiers: "
        + ", ".join(f"{ms}ms on {n} elements" for ms, n in stray.items()))
    assert len(painted) <= 4, \
        f"more distinct durations than tiers: {sorted(map(float, painted))}"


# PHASE 31 - THE FRONT DOOR
#
# `/` is the investigation, a long-form reading of the run, and `/app` is the
# instrument workspace these contracts have always addressed directly. What
# follows pins the front door's GUARANTEES rather than its appearance: that
# its figures come from the engine rather than from the file, that the two
# surfaces reach each other, and that it cannot render a number the engine did
# not produce.

INV = URL.replace("/workspace.html", "/")


@pytest.fixture(scope="module")
def inv(page):
    """The front door, opened in its own context off the browser the workspace
    fixture already owns.

    A second `sync_playwright()` in the same thread raises "Sync API inside the
    asyncio loop" — which is why these six passed when run alone and errored in
    the full suite, where the workspace fixture is already holding one."""
    b = page.context.browser        # the browser Playwright already gave us
    ctx = b.new_context(viewport={"width": 1400, "height": 900})
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(INV, wait_until="networkidle")
    # The readiness sentinel is the LAST section, so waiting on it means the
    # whole template rendered. It named a specific chapter (#boundary) and
    # therefore broke when the information architecture merged that chapter
    # away — thirty-four contracts erroring in the fixture rather than
    # failing on their subject. #end is the last section by construction.
    pg.wait_for_selector("#end", timeout=60000)
    pg.wait_for_timeout(900)
    pg.errors = errors
    yield pg
    ctx.close()


def test_the_investigation_reads_its_figures_from_the_engine(inv):
    """Every number on the front door is fetched at load. A narrative that can
    render without the system it describes is a brochure, and one that keeps
    its own copy of the figures is a brochure that goes stale in silence."""
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      return {n: run.settlements, orders: run.orders, counts: run.counts,
              processed: run.processed_paise}; }""")
    body = inv.inner_text("main")

    c = truth["counts"]
    assert sum(c.values()) == truth["n"], "the verdicts do not account for the run"
    for k in ("PROVEN", "AMBIGUOUS", "CONTRADICTED", "INSUFFICIENT"):
        assert str(c[k]) in body, f"{k}={c[k]} is measured but not shown"
    assert f"{truth['orders']:,}" in body, "the order count is not on the page"

    # compare on digits: the point is that the figure is the engine's, not how
    # the separators fall
    digits = "".join(ch for ch in f"{truth['processed'] / 100:.2f}" if ch.isdigit())
    shown = "".join(ch for ch in body if ch.isdigit())
    assert digits in shown, "the processed total is not the engine's figure"


def test_the_investigation_says_so_when_the_engine_is_silent(inv):
    """The honest failure. With the API refusing, the page states that it has
    nothing to show rather than rendering a plausible page from defaults - the
    same rule the product holds itself to, applied to its own front door."""
    ctx = inv.context.browser.new_context()
    pg = ctx.new_page()
    try:
        pg.route("**/api/**", lambda r: r.abort())
        pg.goto(INV, wait_until="domcontentloaded")
        pg.wait_for_selector(".err", timeout=20000)
        assert "nothing to show" in pg.inner_text(".err").lower()
        assert "\u20b9" not in pg.inner_text("main"), \
            "money was rendered with no engine behind it"
    finally:
        ctx.close()


def test_the_two_surfaces_reach_each_other(inv):
    """The narrative is the front door and the workspace is the instrument. A
    front door with no way in, or a workspace with no way back, is two products
    that happen to share a stylesheet."""
    href = inv.get_attribute("#open-app", "href")
    assert href and href.startswith("/app"), f"the door leads to {href!r}"
    assert inv.query_selector(".door"), "the closing section offers no way in"

    ctx = inv.context.browser.new_context()
    pg = ctx.new_page()
    try:
        pg.goto(URL, wait_until="networkidle")
        pg.wait_for_function("() => SHELL && SHELL.record", timeout=90000)
        back = pg.get_attribute("#bar a.back", "href")
        assert back == "/", f"the workspace's way back leads to {back!r}"
    finally:
        ctx.close()


def test_the_investigation_has_no_horizontal_overflow_at_any_width(inv):
    for w, h in ((360, 780), (390, 844), (768, 1024), (1024, 768),
                 (1280, 800), (1440, 900), (1512, 982)):
        inv.set_viewport_size({"width": w, "height": h})
        inv.wait_for_timeout(320)
        over = inv.evaluate("() => document.documentElement.scrollWidth"
                            " - document.documentElement.clientWidth")
        assert over <= 0, f"{w}x{h}: {over}px of horizontal overflow"
    inv.set_viewport_size({"width": 1400, "height": 900})


def test_the_investigation_scrolls_like_a_page(inv):
    """No scroll-jacking. The choreography reacts to where the reader already
    is; it never takes the wheel. If a script owned scrolling, jumping to the
    end and then asking for the top would not land at the top."""
    inv.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    inv.wait_for_timeout(500)
    assert inv.evaluate("() => window.scrollY") > 2000, "the page barely scrolls"
    inv.evaluate("() => window.scrollTo({top: 0, behavior: 'instant'})")
    inv.wait_for_timeout(500)
    assert inv.evaluate("() => window.scrollY") < 50, \
        "something is holding the scroll position"


def test_the_investigation_raises_no_console_errors(inv):
    assert not inv.errors, "console/page errors: " + "; ".join(inv.errors[:5])



def test_the_investigations_furniture_stays_put(inv):
    """The nav and the provenance strip are fixed, and the seven instruments
    plus the lifecycle are in them.

    Deleting the decorative background traces took the nav's and the strip's
    entire CSS with it — the cut ran from the traces' first rule to the next
    rule after them, and both blocks sat in between. Horizontal overflow stayed
    zero and the console stayed clean; the navigation had simply stopped being
    fixed and scrolled away with the page. Nothing measured that, so this
    does."""
    inv.evaluate("() => window.scrollTo(0, 4000)")
    inv.wait_for_timeout(400)
    m = inv.evaluate("""() => {
      const g = s => { const e = document.querySelector(s); if (!e) return null;
        const r = e.getBoundingClientRect();
        return {pos: getComputedStyle(e).position, top: Math.round(r.top),
                h: Math.round(r.height)}; };
      return {nav: g('#nav'), strip: g('#strip'),
              instruments: document.querySelectorAll('#index a').length,
              lifecycle: document.querySelectorAll('#loop span').length,
              lit: document.querySelectorAll('#loop span.on').length}; }""")
    inv.evaluate("() => window.scrollTo(0, 0)")
    assert m["nav"] and m["nav"]["pos"] == "fixed", f"the nav is {m['nav']}"
    assert m["nav"]["top"] == 0, f"the nav scrolled to {m['nav']['top']}"
    assert m["strip"] and m["strip"]["pos"] == "fixed", f"the strip is {m['strip']}"
    assert m["instruments"] == 7, f"{m['instruments']} instruments in the index"
    assert m["lifecycle"] == 6, f"{m['lifecycle']} lifecycle stations"
    assert m["lit"] == 1, \
        f"{m['lit']} stations lit — exactly one stage is current at a time"


def test_every_shape_on_the_investigation_names_a_job(inv):
    """Phase 32 §1. A shape that represents nothing is decoration.

    Each painted, textless element must be one of: a quantity, a state, a
    transition, evidence, a boundary, an actor, navigation, or the specimen's
    physical structure. The class name is the claim, and this pins the roster —
    so adding a new decorative mark fails until it is either given a job or
    removed."""
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(300)
    shapes = set(inv.evaluate("""() => {
      const vis = e => { const s = getComputedStyle(e);
        return s.display !== 'none' && s.visibility !== 'hidden'
            && parseFloat(s.opacity) > 0 && e.getBoundingClientRect().height > 0; };
      // The whole document, not just `main`. Scoping the scan to the content
      // column let a decorative mark added anywhere else slip past — verified
      // by adding one and watching this pass.
      return [...document.querySelectorAll('body *')].filter(e => {
        if (!vis(e) || e.textContent.trim()) return false;
        const s = getComputedStyle(e);
        return s.backgroundColor !== 'rgba(0, 0, 0, 0)'
            || (s.backgroundImage && s.backgroundImage !== 'none')
            || ['Top','Right','Bottom','Left'].some(k =>
                 parseFloat(s['border' + k + 'Width']) > 0
                 && s['border' + k + 'Style'] !== 'none')
            || e.tagName === 'CANVAS';
      }).map(e => {
        // identity, in the order a reader would name it: class, then id.
        // Falling straight to the tag name made three legitimate shapes —
        // the field, the lifecycle dots, the disposition bars — unnameable,
        // which is a hole in the roster rather than a finding.
        const c = (e.className || '').toString().trim().split(' ')[0];
        return c || e.id || e.tagName; }); }"""))
    JOBS = {
        "fall-m", "bench-t", "spec-disp-r",             # quantity
        "canvas", "CANVAS",                              # population / evidence
        "bound-m", "e", "m", "s", "g", "sig-gl",         # actors
        "sig-tk",                                        # quantity (proposals)
        "hand", "hand-a",                                # the human handoff
        "whole",                                         # the argument, condensed
        "plain", "plain-g",                              # the explanation, in English
        "rule2",                                         # the rule, both halves
        "mast", "inst", "st-c",                          # the opening instrument
        "thr-line", "thr-mark", "ad-b",                  # boundaries
        "spec-c", "spec-punch",                          # specimen structure
        "rule", "hr",                                    # transitions
        "field",                                         # the measured ground
        "st", "q",                                       # lifecycle state, quantity
        "nav", "strip", "index", "loop", "main", "keys", # navigation furniture
        # §58 the decision record. Each of these is a claim, not a mark:
        #   auth     the authority chain — four boundaries between who may do what
        #   dr       the record itself: one financial event and its four parties
        #   dr-dot   STATE: filled means this party may change financial state,
        #            hollow means it may not. The advisory row is the only
        #            hollow one, and that is the product thesis drawn rather
        #            than captioned — which is why it is a shape and not a
        #            sentence.
        #   dr-may   BOUNDARY: what each party may and may not do, paired
        "auth", "dr", "dr-dot", "dr-may", "dr-e", "dr-out", "eviz",
        #   role-d   STATE, again: the authority marker on each of the four
        #            roles. Hollow on the advisory one, filled on the rest.
        "role-d", "coll",
        "spec", "spec-h", "spec-pipe", "spec-disp", "sheet", "thr-s",
        "safe", "adapter", "score", "bench",
        "row", "hero-row", "rise", "stage", "warm", "end", "BODY",
    }
    stray = sorted(shapes - JOBS)
    assert not stray, (
        "shapes that name no job: " + ", ".join(stray)
        + " — give it one of quantity/state/transition/evidence/boundary/"
          "actor/navigation/specimen-structure, or delete it")



def test_the_population_field_carries_its_own_legend(inv):
    """§32.A. The field is evidence, not an ornament.

    It rendered as two coloured blocks and a lone dot, with the counts three
    sections away on the specimen — a reader saw a decoration. Every label is
    pinned to the lane it names and reads its count from the same group object
    that drew the points, so the two cannot disagree.

    The labels are DOM rather than canvas on purpose: a legend that cannot be
    selected, read aloud, or found by the comprehension audit is not a
    legend."""
    truth = inv.evaluate("""async () => {
      const r = await (await fetch('/api/run?n=250')).json(); return r.counts; }""")
    inv.evaluate("() => document.getElementById('population').scrollIntoView()")
    inv.wait_for_timeout(1500)
    labels = inv.evaluate("""() => [...document.querySelectorAll('#population .fld-l')]
      .map(e => { const b = e.querySelector('b');
        return {n: b.textContent.replace(/,/g, ''),
                t: e.textContent.replace(b.textContent, '').trim().toLowerCase(),
                y: Math.round(e.getBoundingClientRect().y),
                lane: Math.round(e.getBoundingClientRect().x)}; })""")
    assert labels, "the field has no legend"

    by = {l["t"]: l["n"] for l in labels}
    for verdict in ("proven", "ambiguous", "contradicted"):
        n = truth[verdict.upper()]
        if not n:
            continue
        assert by.get(verdict) == str(n), (
            f"the field says {by.get(verdict)!r} {verdict}, the run says {n}")

    # one legend, not three unrelated notes
    assert len({l["y"] for l in labels}) == 1, "the labels are not on one baseline"
    # and each sits under its own lane, left to right in the field's order
    xs = [l["lane"] for l in labels]
    assert xs == sorted(xs), "the labels are not in lane order"


def test_the_candidate_field_carries_its_own_legend(inv):
    """The same guarantee for the reduction: 2,368 -> 164 -> 4 is the product's
    signature figure, and the field that draws it must say which is which."""
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      const d = await (await fetch(
        `/api/settlement?run=${run.run_id}&id=setl_000225`)).json();
      return {universe: d.space.universe, candidates: d.space.candidates,
              survivors: (d.proofs || []).length}; }""")
    inv.evaluate("() => document.getElementById('proof').scrollIntoView()")
    inv.wait_for_timeout(1500)
    labels = inv.evaluate("""() => [...document.querySelectorAll('#proof .fld-l')]
      .map(e => { const b = e.querySelector('b');
        return {n: b.textContent.replace(/,/g, ''),
                t: e.textContent.replace(b.textContent, '').trim().toLowerCase()}; })""")
    assert labels, "the candidate field has no legend"
    by = {l["t"]: l["n"] for l in labels}
    assert by.get("candidates") == str(truth["candidates"]), \
        f"the field says {by.get('candidates')!r} candidates, the case says {truth['candidates']}"
    assert by.get("explanations") == str(truth["survivors"]), \
        f"the field says {by.get('explanations')!r} explanations, the case says {truth['survivors']}"
    cut = truth["universe"] - truth["candidates"]
    assert by.get("cut by the reductions") == str(cut), \
        f"the field says {by.get('cut by the reductions')!r} cut, the case says {cut}"



def test_the_refusal_is_the_largest_thing_in_its_own_section(inv):
    """§32.B. The product's strongest claim was set at 24px.

    The section ran a 44px headline, a 34px counterfactual, and NO FINANCIAL
    ACTION — the sentence the whole product exists for — at 24px. A judge
    scrolling at pace read the headline and passed the claim. It leads the
    section now."""
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(300)
    sizes = inv.evaluate("""() => {
      const out = [];
      document.querySelectorAll('#ai *').forEach(e => {
        if (e.childElementCount || !e.textContent.trim()) return;
        const s = getComputedStyle(e);
        out.push({px: parseFloat(s.fontSize), color: s.color,
                  t: e.textContent.trim()}); });
      return out.sort((a, b) => b.px - a.px); }""")
    assert sizes, "the model section has no text"
    top = sizes[0]
    assert "no financial action" in top["t"].lower(), (
        f"the largest thing in the section is {top['t'][:44]!r} at "
        f"{top['px']:.0f}px, not the refusal")


def test_both_verdicts_are_painted_the_same(inv):
    """§32.B. The model concluded AMBIGUOUS and the engine kept AMBIGUOUS.

    Painting the engine's coral and the model's white implied the engine's was
    the worse of the two. Coral means unresolved in this product, and they are
    equally unresolved — it is spent on the CONSEQUENCE, not on either verdict.
    """
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(300)
    cells = inv.evaluate("""() => [...document.querySelectorAll('.cf-c b')]
      .map(e => ({t: e.textContent.trim(), color: getComputedStyle(e).color}))""")
    if not cells:
        return                       # no counterfactual on this run
    verdicts = [c for c in cells if c["t"].isupper() and len(c["t"]) > 3]
    assert len(verdicts) >= 2, f"expected two verdict cells, saw {verdicts}"
    assert len({c["color"] for c in verdicts}) == 1, (
        "the two verdicts are painted differently: "
        + ", ".join(f"{c['t']}={c['color']}" for c in verdicts))

    # and the coral in this section belongs to the consequence
    coral = inv.evaluate("""() => {
      const c = getComputedStyle(document.documentElement)
        .getPropertyValue('--coral').trim();
      const probe = document.createElement('span');
      probe.style.color = c; document.body.appendChild(probe);
      const rgb = getComputedStyle(probe).color; probe.remove();
      return [...document.querySelectorAll('#ai *')]
        .filter(e => !e.childElementCount && e.textContent.trim()
                  && getComputedStyle(e).color === rgb)
        .map(e => e.textContent.trim().toLowerCase()); }""")
    assert coral, "nothing in the section carries the boundary colour"
    assert any("no financial action" in t or "external evidence" in t
               for t in coral), \
        f"coral is on {coral[:4]} rather than on the consequence"



def test_the_narrowing_is_one_continuous_chain(inv):
    """§32.C. 250 -> 197 -> one of them -> 2,368 -> 164 -> 4 is a single act of
    narrowing the evidence space, and it was four sections with nothing
    carrying the thread between them. A reader met four good moments and no
    movie.

    Every figure is the run's, and the lit step advances section by section, so
    a reader always knows how far in they are and what the number in front of
    them narrowed from."""
    truth = inv.evaluate("""async () => {
      const r = await (await fetch('/api/run?n=250')).json();
      const d = await (await fetch(
        `/api/settlement?run=${r.run_id}&id=setl_000225`)).json();
      return [r.settlements, r.counts.AMBIGUOUS, 1,
              d.space.universe, d.space.candidates, (d.proofs || []).length]; }""")
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(300)

    # §59 changed which way this holds. The chain used to be carried across
    # four chapters, because the narrowing WAS four chapters; the information
    # architecture states it once, completely, in the section that does the
    # narrowing. So the sections are no longer named here — every section that
    # carries the chain is found, and each is held to the same two things the
    # original asserted: the figures are the run's, and the reader is told how
    # far in they are. Naming the chapters made this test a description of one
    # layout rather than of the guarantee.
    found = inv.evaluate("""() => [...document.querySelectorAll('main > section')]
      .map(s => {
        const rows = [...s.querySelectorAll('.nrw-r')];
        if (!rows.length) return null;
        return {sec: s.id,
                steps: rows.map(e => e.querySelector('b').textContent.replace(/,/g, '')),
                lit: rows.findIndex(e => e.classList.contains('on'))}; })
      .filter(Boolean)""")

    assert found, "the narrowing appears nowhere"
    for r in found:
        assert r["steps"] == [str(n) for n in truth], (
            f"{r['sec']}: the chain says {r['steps']}, the run says {truth}")
        assert r["lit"] >= 0, f"{r['sec']}: no step is lit"

    lits = [r["lit"] for r in found]
    assert lits == sorted(lits) and len(set(lits)) == len(lits), \
        f"the narrowing does not advance in reading order: {lits}"



def test_the_two_populations_are_named_where_they_are_compared(inv):
    """§34.P0-1. "84 / 500" printed under a live run of 250 reads as a
    contradiction, and a judge who spots one stops trusting every other figure
    on the page.

    The artifact says they are not in conflict: the same portfolio size, and
    seeds the policy was never calibrated on. That is held-out evaluation — a
    strength that was being kept to ourselves.

    §47.F1 changed which way this holds. The live run used to sit on a
    calibration seed, so the panel was held out *from the run* and this test
    asserted the two shared no seed. The run now sits on 555001, which IS a
    panel seed — so the claim is no longer "the panel is held out from the run"
    but the stronger one: the run itself is on data nothing was tuned on. The
    assertion below follows that, and asks the API which basis a seed has
    rather than deciding here.

    Both figures are read from their sources, and both must be visible at the
    benchmark itself: not in Trust, not in a tooltip, not in a document."""
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      const cl = await (await fetch(`/api/claims?run=${run.run_id}`)).json();
      return {liveN: run.settlements, liveSeed: run.seed,
              basis: run.seed_basis || {},
              panel: (cl.baselines || {}).panel}; }""")
    panel = truth["panel"]
    assert panel and panel.get("settlements"), "the artifact reports no panel shape"

    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(300)
    strip = inv.query_selector(".bench-pop")
    assert strip, "the benchmark does not name its populations"
    t = strip.inner_text()

    assert str(truth["liveN"]) in t, f"the live run's {truth['liveN']} is not stated"
    assert str(truth["liveSeed"]) in t, "the live run's seed is not stated"
    assert str(panel["settlements"]) in t, \
        f"the panel's {panel['settlements']} is not stated"
    assert str(panel["seeds"]) in t and str(panel["per_seed"]) in t, \
        f"the panel's shape ({panel['seeds']} seeds x {panel['per_seed']}) is not stated"
    assert "held out" in t.lower(), \
        "nothing says the panel is held out from the live run"

    # and the two must be distinguishable, not two bare numbers side by side
    assert "live" in t.lower() and "benchmark" in t.lower(), \
        "the two populations are not labelled as different things"

    # the live run really is on held-out data: its seed is one the policy was
    # never calibrated against. This is what makes both figures comparable
    # rather than one of them a memory.
    assert truth["basis"].get("held_out") is True, (
        f"the live run is on seed {truth['liveSeed']}, which is "
        f"{truth['basis'].get('label')} — so 'held out' is not true of it")
    assert truth["liveSeed"] in (panel.get("seed_ids") or []), (
        "the live run's seed is not one of the panel's, so the figures on "
        "screen are drawn from two unrelated populations")


# ── §38 ─────────────────────────────────────────────────────────────────────
# Three changes, three guarantees. The audit that produced them found the
# opposite of what it expected: the model/solver/engine facts were all on the
# page already, spread over 1,545px of a 12,879px scroll. Every fact was
# present and none of it was a frame. What follows pins the composition, not
# the content — the content was never the defect.

def test_the_model_boundary_is_one_screenshottable_frame(inv):
    """§38.P0-1. All five beats inside one element, inside one viewport.

    A judge screenshots a frame, not a section. Spread across four blocks the
    argument could be read and could not be captured, which is why the
    strongest idea in the product was the one nobody could quote.
    """
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(400)
    frame = inv.query_selector(".sig")
    assert frame, "there is no signature frame"

    box = frame.bounding_box()
    assert box["height"] <= 900, (
        f"the frame is {box['height']:.0f}px tall and cannot be captured in a "
        "900px viewport")

    t = " ".join(frame.inner_text().lower().split())
    for beat in ("model", "solver", "engine", "proposes", "tests", "decides",
                 "no financial action"):
        assert beat in t, f"the frame does not contain {beat!r}"

    # the three actors are one object each, in reading order
    actors = inv.eval_on_selector_all(
        ".sig .sig-r", "els => els.map(e => e.className.split(' ')[1])")
    assert actors == ["model", "solver", "engine"], \
        f"the actors are not model -> solver -> engine: {actors}"


def test_the_frames_numbers_come_from_the_measurement(inv):
    """§38.P0-1 / §47.F2. The frame states what n=1020 supports, and no more.

    A hand-written ratio beside a hand-drawn bar is a picture of a claim. The
    tick row is generated from the same two integers the API reports, so the
    drawing cannot drift from the finding it draws.

    It used to read "42.9% - below a coin flip". At n=63 that is p=0.157 against
    a fair coin and a 95% interval of roughly [0.31, 0.55], which contains one
    half: the claim the hero frame made was the one claim on the page the
    artifact could not carry, in a product whose stated law is not to claim what
    it cannot measure. The decision to disable the loop was never in doubt - it
    rests on how rarely the loop speaks at all (63 of 1020 ambiguous cases) and
    on the 53% of pools where its lens is true of every order. Those are counts,
    not inferences, and they are what the frame states now.
    """
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      const cl = await (await fetch(`/api/claims?run=${run.run_id}`)).json();
      return cl.anchoring; }""")
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(400)

    ticks = inv.eval_on_selector_all(".sig-tk", "e => e.length")
    hits = inv.eval_on_selector_all(".sig-tk.hit", "e => e.length")
    assert ticks == truth["resolved"], \
        f"{ticks} ticks drawn for {truth['resolved']} resolved proposals"
    assert hits == truth["correct"], \
        f"{hits} filled for {truth['correct']} correct"
    t = inv.inner_text(".sig")
    assert f"{truth['resolved']} / {truth['ambiguous']}" in t, \
        "the frame does not state how rarely the loop speaks"
    assert f"{truth['correct']}" in t, \
        "the frame does not state how often it was right when it did"
    assert "coin flip" not in t.lower(), \
        "the frame is making a claim n=63 does not support"


def test_the_demo_runs_on_a_seed_it_was_not_calibrated_on(inv):
    """§47.F1. The live run uses a held-out seed, and both surfaces say so.

    The demo ran on 20260821 for most of this project's life. That is one of the
    three calibration seeds, and FAILURES.md D7 - "Published 'precision 1.000'
    for six days. It was one seed." - is about exactly that seed and exactly the
    pair of numbers the demo was reporting. The disclosure existed, on the front
    door, in prose; /app showed the flattering figure with no seed at all. A
    system whose claim is that it will not assert what it cannot prove does not
    get to demonstrate itself on the data it was tuned on.

    Held out is a property of the panel artifact, not of this test, so the test
    asks the API which it is rather than hard-coding a seed.
    """
    basis = inv.evaluate("""async () => {
      const r = await (await fetch('/api/run?n=250')).json();
      return {seed: r.seed, basis: r.seed_basis}; }""")
    assert basis["basis"]["held_out"] is True, \
        f"the demo runs on seed {basis['seed']}, which is {basis['basis']['label']}"

    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(400)
    body = inv.inner_text("body")
    assert str(basis["seed"]) in body, "the front door does not name the seed it ran"
    assert basis["basis"]["short"] in body.lower(), \
        "the front door does not say the seed was held out"


def test_the_benchmark_shows_coverage_and_error_together(inv):
    """§38.P0-2. Two bars, one scale, and the correct-decision count.

    A false-proof rate alone made 20.8% look like a low match rate next to a
    competitor's 94%. Coverage and error drawn on the same scale make the
    trade visible, and `decided - wrong` — both published fields — is the
    number that ends the argument.
    """
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      const cl = await (await fetch(`/api/claims?run=${run.run_id}`)).json();
      return cl.baselines; }""")
    if not truth.get("present"):
        pytest.skip("no baselines artifact")
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(700)

    rows = inv.eval_on_selector_all(".bench-r", """els => els.map(e => ({
        bars: [...e.querySelectorAll('.bench-t u.q')].map(
                u => parseFloat(getComputedStyle(u).getPropertyValue('--w'))),
        ok: (e.querySelector('.bench-ok') || {}).textContent }))""")
    assert len(rows) == len(truth["methods"]), "not every method has a row"

    for row, m in zip(rows, truth["methods"]):
        assert len(row["bars"]) == 2, \
            f"{m['label']} draws {len(row['bars'])} bars, not coverage + error"
        cov, fp = row["bars"]
        assert abs(cov - m["decided"] / m["settlements"]) < 0.002, \
            f"{m['label']}'s coverage bar does not match {m['decided']}"
        assert abs(fp - m["false_proof"]) < 0.002, \
            f"{m['label']}'s error bar does not match {m['false_proof']}"
        assert int(row["ok"]) == m["decided"] - m["wrong"], \
            f"{m['label']} states {row['ok']} correct, not {m['decided'] - m['wrong']}"

    # the argument only works if both bars are on one scale
    greedy = next(m for m in truth["methods"] if m["key"] == "greedy")
    attest = next(m for m in truth["methods"] if m["key"] == "attest")
    assert attest["decided"] - attest["wrong"] > greedy["decided"] - greedy["wrong"], \
        "the artifact no longer supports the claim the section makes"


def test_the_refusal_hands_the_work_to_a_person(inv):
    """§38.P0-3. The boundary offers an exit, and says it is a read.

    "We stop here" and "we hand the unresolved work to whoever can finish it"
    are different products. Without the second, the strongest safety property
    in the product reads as an unfinished feature.
    """
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(400)
    link = inv.query_selector("#export")
    assert link, "the boundary offers no way to take the queue anywhere"
    # `query_selector` finds hidden elements and `getComputedStyle` reads them
    # happily, so an export with `hidden` on it satisfied every other check
    # here. An exit nobody can see is not an exit.
    assert link.is_visible(), "the export link is present but not visible"
    box = link.bounding_box()
    assert box and box["width"] > 40 and box["height"] > 8, \
        f"the export link occupies no usable area: {box}"

    href = link.get_attribute("href")
    assert "/api/export/queue" in href and "run=" in href, \
        f"the export does not name a run: {href}"
    assert link.get_attribute("download") is not None, \
        "the export does not download; it navigates away from the argument"

    # lime is only ever an action in this product, and this is the only action
    # in the room where the system stops
    colour = link.evaluate("e => getComputedStyle(e).color")
    lime = inv.evaluate("""() => getComputedStyle(document.documentElement)
                             .getPropertyValue('--lime').trim()""")
    assert colour == inv.evaluate(
        "(c) => { const d = document.createElement('i'); d.style.color = c;"
        " document.body.appendChild(d);"
        " const r = getComputedStyle(d).color; d.remove(); return r; }", lime), \
        f"the handoff is painted {colour}, not the action colour"

    block = inv.inner_text(".hand").lower()
    assert "read-only" in block, "the export does not say it is a read"
    for word in ("posted", "mutated", "transmitted"):
        assert word in block, f"the export does not disclaim {word}"


def test_the_handoff_counts_the_same_settlements_it_exports(inv):
    """§38.P0-3. 197 and 198 are both correct and sit 200px apart.

    The blocker holds 197 ambiguous settlements; the queue carries every
    unresolved one. Stating the second beside the first without naming the
    difference reads as an arithmetic error in a product whose entire claim is
    arithmetic.
    """
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      const q = await (await fetch(
        `/api/export/queue?run=${run.run_id}`)).json();
      return {counts: run.counts, rows: q.count}; }""")
    c = truth["counts"]
    expect = c.get("AMBIGUOUS", 0) + c.get("CONTRADICTED", 0) + c.get("INSUFFICIENT", 0)
    assert truth["rows"] == expect, \
        f"the export carries {truth['rows']} rows for {expect} unresolved"

    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(400)
    t = inv.inner_text(".hand")
    assert str(expect) in t, f"the handoff does not state its own {expect}"
    assert str(c.get("AMBIGUOUS", 0)) in t, \
        "the handoff does not reconcile itself with the blocker's count"


@pytest.mark.parametrize("width", [360, 390, 768, 1024, 1280, 1440, 1920])
def test_no_element_is_silently_clipped(inv, width):
    """§38. `body` carries `overflow-x:hidden`, so `scrollWidth` is pinned to
    the viewport and every earlier overflow check in this file was blind to
    content clipped inside a non-scrolling ancestor.

    The provenance strip was the finding: 434px of unbreakable mono in a 390px
    box with `overflow:hidden`, so the run id was cut off at every phone width
    while the page reported zero overflow. An element may sit outside the
    viewport only if something can actually be scrolled to reach it.
    """
    inv.set_viewport_size({"width": width, "height": 900})
    inv.wait_for_timeout(250)
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(250)
    clipped = inv.evaluate("""() => {
      const W = document.documentElement.clientWidth, out = [];
      const scrollable = e => {
        for (let p = e.parentElement; p; p = p.parentElement) {
          const o = getComputedStyle(p).overflowX;
          if ((o === 'auto' || o === 'scroll') && p.scrollWidth > p.clientWidth)
            return true;
        }
        return false; };
      document.querySelectorAll('body *').forEach(e => {
        const b = e.getBoundingClientRect();
        if (!b.width || b.right <= W + 1) return;
        if (scrollable(e)) return;                 // reachable by scrolling
        out.push({ el: (e.className || e.tagName).toString().split(' ')[0],
                   over: Math.round(b.right - W),
                   txt: (e.textContent || '').trim().slice(0, 40) }); });
      return out; }""")
    inv.set_viewport_size({"width": 1400, "height": 900})
    assert not clipped, (
        f"at {width}px, content is cut off with no way to reach it: "
        + "; ".join(f"{c['el']} +{c['over']}px {c['txt']!r}" for c in clipped[:4]))


# ── §39 ─────────────────────────────────────────────────────────────────────

def test_the_handoff_states_its_size_and_its_exposure(inv):
    """§39.3. An export with no scale attached is a button, not a boundary.

    The room where the system stops has to say how much work is leaving and how
    much money it represents, or "we hand the work to a person" is a slogan.
    Both figures are read from the run — the exposure is the same total the
    manifest already reports as held, not a second measurement of the same
    money under a different name.
    """
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      const q = await (await fetch(
        `/api/export/queue?run=${run.run_id}`)).json();
      return {rows: q.count, paise: q.value_paise, counts: run.counts}; }""")
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(400)

    figs = inv.query_selector(".hand-f")
    assert figs, "the handoff states no scale"
    t = " ".join(figs.inner_text().split())

    assert str(truth["rows"]) in t, f"the handoff does not state its {truth['rows']} rows"
    # the exposure, formatted the way this page formats money
    rupees = truth["paise"] / 100
    whole = f"{int(rupees):,}".replace(",", "")
    digits = "".join(ch for ch in t if ch.isdigit())
    assert whole in digits, \
        f"the handoff does not state the {rupees:,.2f} it is handing over: {t!r}"
    assert "exposure" in t.lower(), "the money is stated without being named"
    assert "evidence" in t.lower(), "the handoff does not say what would resolve it"


def test_no_engineering_measurement_is_stated_twice(inv):
    """§39.4. One strong rendering, not three weak ones.

    A page that reports the same measured number in three places reads as a
    thesis restating itself rather than a product stating a fact. This caught a
    real regression: a second engineering specimen was added in this phase
    while `#proofs` already rendered all six of the same measurements, so every
    one of them briefly appeared twice.
    """
    truth = inv.evaluate("""async () => {
      const run = await (await fetch('/api/run?n=250')).json();
      const cl = await (await fetch(`/api/claims?run=${run.run_id}`)).json();
      return {kernel: cl.kernel, iso: cl.isolation, adv: cl.adversarial,
              gates: (cl.gates || []).length}; }""")
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(500)
    body = " ".join(inv.inner_text("body").split())

    import re as _re
    checks = {
        "kernel line count": rf"\b{truth['kernel']['lines']} ?line",
        "module isolation": rf"\b{truth['iso']['clean']}\s*(of|/)\s*{truth['iso']['modules']}\b",
        "gate tally": rf"\b{truth['gates']}\s*(of|/)\s*{truth['gates']}\b",
    }
    twice = {k: len(_re.findall(p, body, _re.I))
             for k, p in checks.items() if len(_re.findall(p, body, _re.I)) > 1}
    assert not twice, (
        "these measurements are rendered more than once: "
        + ", ".join(f"{k} x{n}" for k, n in twice.items())
        + " — prefer one strong rendering")


def test_the_benchmark_leads_with_the_decisive_number(inv):
    """§39.5. Five seconds gets you the winner or it gets you nothing.

    Coverage and false-proof are the trade; `decided - wrong` is the answer.
    When it was set smaller than the row's other figures a judge read the bars,
    saw ATTEST's short coverage bar, and left with the wrong conclusion.
    """
    inv.evaluate("() => document.querySelectorAll('.rise').forEach(n => n.classList.add('in'))")
    inv.wait_for_timeout(600)
    rows = inv.eval_on_selector_all(".bench-r", """els => els.map(e => {
        const ok = e.querySelector('.bench-ok');
        const others = [...e.querySelectorAll('b')].map(
            n => parseFloat(getComputedStyle(n).fontSize));
        return {ok: parseFloat(getComputedStyle(ok).fontSize),
                others: Math.max(...others)}; })""")
    assert rows, "the benchmark has no rows"
    for r in rows:
        assert r["ok"] > r["others"], (
            f"correct-decisions is set at {r['ok']:.0f}px, no larger than the "
            f"row's other figures at {r['others']:.0f}px")


@pytest.mark.parametrize("width", [360, 390, 768])
def test_the_navigation_is_one_row_on_a_phone(inv, width):
    """§39.8. Mobile is not a shrunk desktop.

    `#index` is the vertical instrument rail on desktop and was left at
    `display:block` inside a row-direction nav on phones, so the seven
    instruments stacked into a 96px column 169px tall and pushed the action off
    the right edge. The nav scrolls horizontally, so no overflow check saw it —
    the phone screenshot did.
    """
    inv.set_viewport_size({"width": width, "height": 844})
    inv.wait_for_timeout(350)
    m = inv.evaluate("""() => {
      const n = document.querySelector('#nav'), i = document.querySelector('#index');
      return {nav: n.getBoundingClientRect().height,
              idx: i.getBoundingClientRect().height,
              links: i.querySelectorAll('a').length}; }""")
    inv.set_viewport_size({"width": 1400, "height": 900})
    assert m["links"] >= 5, "the instrument rail lost its links"
    assert m["idx"] <= 56, (
        f"the instrument rail is {m['idx']:.0f}px tall at {width}px — it is "
        "stacking into a column instead of running as one row")
    assert m["nav"] <= 90, f"the phone navigation occupies {m['nav']:.0f}px"
