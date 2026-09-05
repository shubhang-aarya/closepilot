# Failure → regression map

Every significant failure in this project, and the test that would catch it
coming back.

**A failure is not fixed because the benchmark number looks unchanged.** It is
fixed when all five of these exist:

1. a reproduction
2. a fix
3. a regression test
4. the regression fails against the old behaviour
5. the regression passes against the new behaviour

A number that did not move is consistent with a fix and equally consistent with
never having measured the thing that broke. The `CURRENT STATUS` line below says
which of the five a failure actually has, and several say *fewer than five* —
those entries are the useful ones, because they are where this project is
claiming less than it might appear to.

The `REGRESSION TEST` lines are machine-checked:
`test_every_test_named_in_the_failure_map_exists` parses this file, extracts
every backticked `test_*` identifier, and fails if one does not exist in the
suite. A renamed or deleted test breaks the build rather than rotting here.

Statuses used:

| Status | Meaning |
|---|---|
| **FIXED** | all five conditions above |
| **FIXED, COVERED INDIRECTLY** | fixed, but the regression is an assertion inside a test aimed at something else — it would catch the failure, but nothing says so by name |
| **REJECTED** | built, measured, and deliberately not shipped. The regression is that the rejection stays visible |
| **BOUNDED** | not a defect. A limit that is recorded rather than removed |
| **SURFACE REMOVED** | the fix is gone because the code it fixed is gone |
| **NO REGRESSION** | fixed, but nothing would catch it coming back |

---

## D23 — adapter ingestion, six defects in the reader

- **WHAT BROKE** — a recon row read twice doubled its settlement; `int(10.5)`
  truncated money to 10; a non-dict row raised `AttributeError` and lost the
  whole page; `str(None)` produced the truthy key `"None"`, so every row without
  a `payment_id` shared one identity and collapsed into a single record; an
  unset webhook secret meant nothing was verified and nothing said so; a
  malformed webhook body raised past the boundary that exists to stop it.
- **HOW IT WAS FOUND** — running an adversarial pass against the adapter rather
  than reading it. The `str(None)` defect was found by an existing regression
  test failing after the first fix, which is the only reason it was caught.
- **REGRESSION TEST** — `test_001_identical_row_twice_is_counted_once`,
  `test_001_overlapping_pages_do_not_double_a_settlement`,
  `test_001_rows_without_any_identity_are_kept`,
  `test_001_a_row_naming_itself_twice_differently_is_refused`,
  `test_002_inexact_or_unreadable_is_refused`,
  `test_002_unit_is_declared_not_inferred`,
  `test_003_rejections_are_records_not_a_counter`,
  `test_wh_absent_secret_refuses_ingestion`,
  `test_wh_malformed_body_is_rejected_on_the_record`,
  `test_a_rejected_order_never_shrinks_the_settlement_target`,
  `test_integration_ten_fifty_traced_through_every_layer`
- **CURRENT STATUS** — FIXED. All five conditions; each test was written against
  the observed old behaviour and watched to fail before the fix landed.
- **WHY IT MATTERS** — the adapter is the only part of ATTEST with no proof
  obligation attached to it. An independent kernel checks every proof; nothing
  checks that the numbers the prover was handed are the numbers Razorpay sent.
  Every one of these six changes a verdict invisibly.

## CORE-001 — postable failed open without search-space provenance

- **WHAT BROKE** — `Finding.postable` returned `True` when no search space was
  recorded. A proof was postable *because* it omitted the evidence it would have
  been judged on.
- **HOW IT WAS FOUND** — attacking the property encoding rather than reading the
  predicate: constructing a finding with the search space stripped and asking
  whether it could post.
- **REGRESSION TEST** —
  `test_core001_a_proof_without_search_space_provenance_cannot_post`,
  `test_core001_a_fabricated_space_that_is_not_a_record_cannot_post`,
  `test_core001_a_space_recording_no_universe_cannot_post`,
  `test_core001_a_proof_with_no_solver_provenance_cannot_post`,
  `test_core001_a_compromised_space_still_cannot_post`,
  `test_core001_a_legitimate_proof_still_posts`
- **CURRENT STATUS** — FIXED. `attest/verdict.py` is protected by the pre-commit
  hook; the change was made only after being authorised as human-owned. Measured
  impact on legitimate proofs: none — 52 postable before and after, six gates
  +0.0000. Reproduction: `reports/CORE-001-postable-fails-open.md`.
- **WHY IT MATTERS** — the last gate before money moves. Failing open there means
  the safest-looking finding is the one with the least evidence.

## CORE-002 — cardinality was not membership

- **WHAT BROKE** — condition 4 of `postable` compared the *size* of the cited
  proof against the size of the candidate universe. A forged proof citing two
  invented order ids passed against a universe of five candidates, because two is
  less than five.
- **HOW IT WAS FOUND** — one membership attack, run deliberately after CORE-001:
  citing `("X", "Y")` — orders that exist nowhere — against a real search space.
- **REGRESSION TEST** —
  `test_core002_cited_orders_must_belong_to_the_candidate_universe`,
  `test_core002_a_single_foreign_order_is_enough_to_refuse`,
  `test_core002_a_space_recording_no_members_cannot_post`,
  `test_core002_every_engine_proof_sits_inside_its_recorded_members`
- **CURRENT STATUS** — FIXED. `SearchSpace` now records `members`, populated at
  the single construction site in `blocking.py`. Reproduction:
  `reports/CORE-002-cardinality-not-membership.md`.
- **WHY IT MATTERS** — counting is not belonging. A check that counts can be
  satisfied by anything of the right size, which is the same shape of error as
  the search-space integrity failure below: a property that holds inside a
  restricted space and is reported as if it held generally.

## Search-space integrity — uniqueness inside a restricted space is not uniqueness

- **WHAT BROKE** — the solver found a unique explanation among 32 candidates and
  reported it as unique. The real candidate universe was 92; blocking had
  removed 60 of them. Uniqueness inside a restricted space is not uniqueness.
- **HOW IT WAS FOUND** — a property test asserting soundness discovered the
  engine was sound for a narrower reason than the one stated (D10).
- **REGRESSION TEST** — `test_local_uniqueness_is_never_reported_as_global`,
  `test_compromised_space_never_posts`,
  `test_reductions_account_for_every_excluded_order`,
  `test_pipeline_refuses_a_compromised_search_space_even_when_proven`
- **CURRENT STATUS** — FIXED. Every reduction must account for the orders it
  excluded, and a space that cannot is `COMPROMISED` and cannot post.
- **WHY IT MATTERS** — this is the failure the whole product is shaped around.
  It is the reason a verdict carries its search space, and the reason CORE-001
  and CORE-002 were worth attacking.

## D4 — cross-settlement propagation produced false proofs

- **WHAT BROKE** — constraint propagation across settlements resolved 20.8% more
  cases and manufactured proofs that were wrong. An order excluded from one
  settlement's pool because another settlement claimed it is only excluded if
  that other claim was correct.
- **HOW IT WAS FOUND** — measured it, then measured the false-proof rate.
- **REGRESSION TEST** — `test_local_uniqueness_is_never_reported_as_global`,
  `test_rejected_features_are_visible_as_rejected`
- **CURRENT STATUS** — REJECTED. Built, measured at 20.8%, shipped off. Recorded
  as claim C-101 and rendered in the Trust lens as a rejected feature, so the
  rejection is visible in the product rather than only in a log.
- **WHY IT MATTERS** — the most dangerous features are the ones that improve the
  headline number. Coverage went up and correctness went down, and only measuring
  both caught it.

## D5 — the amount-ceiling envelope was measured, then widened

- **WHAT BROKE** — an hour spent optimising a search that was never running,
  because the amount ceiling excluded the cases the optimisation was for.
- **HOW IT WAS FOUND** — measuring the envelope instead of assuming it.
- **REGRESSION TEST** — `test_amount_ceiling_is_deterministic_and_calendar_is_not`
- **CURRENT STATUS** — REJECTED, then widened. Claim C-102 at 14.8%.
- **WHY IT MATTERS** — the ceiling is deterministic and the calendar is not, and
  conflating the two is how an envelope silently becomes a filter.

## D7 — "precision 1.000" was one seed, published for six days

- **WHAT BROKE** — a headline precision figure measured on a single seed and
  reported as if it were the system's precision.
- **HOW IT WAS FOUND** — running the panel on more than one seed.
- **REGRESSION TEST** — `test_the_canonical_panel_is_the_held_out_seeds`,
  `test_the_baseline_panel_uses_the_evaluation_seeds`,
  `test_no_percentage_in_the_readme_is_unaccounted_for`
- **CURRENT STATUS** — FIXED. The canonical panel is the held-out seeds
  (`PANEL[3:]`), calibration uses `PANEL[:3]`, and the two cannot be confused
  without a test failing.
- **WHY IT MATTERS** — a number measured on the data that tuned it is not a
  measurement. This is the failure that produced the held-out panel.

## D13 / D7 — benchmark and document drift

- **WHAT BROKE** — README claimed ₹99,571 recovered where the artifact said
  ₹40,464; ₹1,786 wrongly posted where the artifact said ₹0; 7.4% where the
  artifact said 2.2%. Documentation had been written by hand and had drifted
  from the measurements it described.
- **HOW IT WAS FOUND** — building the what-changed engine and pointing it at a
  claim the project makes about itself.
- **REGRESSION TEST** — `test_the_readme_blocks_match_the_artifacts`,
  `test_no_percentage_in_the_readme_is_unaccounted_for`,
  `test_every_registered_claim_reads_from_its_artifact`
- **CURRENT STATUS** — FIXED. Every percentage in README is generated from an
  artifact through the claim register, and a claim that cannot read its artifact
  fails the suite.
- **WHY IT MATTERS** — a project whose documentation overstates its results by
  2.5× has not made a documentation error. Every number here is now derived or
  marked as not measured.

## D14 — policy simulation mutated the recorded decision

- **WHAT BROKE** — the policy simulator's first frontier was flat, and the
  obvious fix made it worse. Simulating a different costing changed the decision
  that had actually been recorded.
- **HOW IT WAS FOUND** — building the simulator and reading the frontier.
- **REGRESSION TEST** — `test_simulating_a_costing_does_not_change_the_recorded_decision`,
  `test_threshold_moves_with_the_review_cost`,
  `test_uncalibrated_policy_posts_nothing`
- **CURRENT STATUS** — FIXED. A simulation is a question, not an edit.
- **WHY IT MATTERS** — a what-if that rewrites the record destroys the thing it
  was asked about. The recorded decision is evidence.

## D9 — the policy under-priced its own risk by five times

- **WHAT BROKE** — expected loss computed from the point estimate rather than an
  upper bound, under-pricing risk roughly fivefold. Separately, the loss was
  rounded *down*, which is the unsafe direction.
- **HOW IT WAS FOUND** — comparing the priced risk against the realised rate.
- **REGRESSION TEST** — `test_risk_is_priced_above_the_point_estimate`,
  `test_expected_loss_rounds_toward_checking_not_toward_posting`,
  `test_no_deciding_path_computes_money_in_floating_point`
- **CURRENT STATUS** — FIXED. Wilson upper bound, and rounding that breaks
  toward review rather than toward posting.
- **WHY IT MATTERS** — `P(error) × Cost(error) < Cost(review)` is only as honest
  as the `P`. A point estimate is the number you get when you decline to price
  your own uncertainty.

## D15 — a stale result could land on a subject that had moved

- **WHAT BROKE** — an in-flight request for one subject resolved after the user
  had navigated to another, and its result rendered under the new subject's
  header. The screen showed one settlement's identity above another's data.
- **HOW IT WAS FOUND** — holding a request open in the browser and navigating
  during it.
- **REGRESSION TEST** — `test_a_result_is_discarded_when_the_subject_moved_during_the_request`,
  `test_a_stale_evidence_fetch_cannot_land_on_another_subject`,
  `test_a_stale_investigation_cannot_land_on_another_subject`,
  `test_a_stale_policy_fetch_cannot_land_on_another_subject`,
  `test_a_stale_activity_fetch_cannot_land_on_another_subject`,
  `test_a_stale_trust_fetch_cannot_land_on_another_subject`
- **CURRENT STATUS** — FIXED. `AsyncResourceGuard` is keyed on subject, lens and
  context, and every lens that fetches has its own named contract — six of them,
  one per lens, because a guard that protects five lenses and misses the sixth is
  the bug wearing a fix's clothes.
- **WHY IT MATTERS** — the wrong number under the right heading is worse than an
  error, because nothing about it looks wrong.

## D18 — idempotency on the event id alone would have been wrong

- **WHAT BROKE** — nothing shipped broken. Designing the event log, an id-only
  duplicate check would have waved through a replay whose body had been mutated.
- **HOW IT WAS FOUND** — asking what a provider that reuses an id with different
  content would do to the check.
- **REGRESSION TEST** — `test_duplicate_event_is_not_processed_twice`,
  `test_same_id_different_body_is_a_contradiction_not_a_duplicate`,
  `test_signature_verifies_over_raw_bytes`,
  `test_blast_radius_is_scoped_to_named_entities`,
  `test_wh_same_id_different_body_is_a_contradiction`
- **CURRENT STATUS** — FIXED. Keyed on id **and** payload hash; same id with a
  different body is `REPLAY_MISMATCH`, a contradiction rather than a duplicate.
- **WHY IT MATTERS** — the two cases need different answers. Treating a
  contradiction as a duplicate silently discards the delivery that disagreed.

## D19 — agent permissions enforced at configuration time

- **WHAT BROKE** — nothing shipped broken. A capability checked at call time can
  be reached by a path that forgets to check.
- **HOW IT WAS FOUND** — asking where a write capability could be granted.
- **REGRESSION TEST** — `test_no_agent_can_be_configured_with_a_write_capability`,
  `test_no_agent_in_the_roster_holds_a_write_capability`,
  `test_pipeline_refuses_a_write_at_the_capability_stage`,
  `test_pipeline_stops_at_the_first_refusal`,
  `test_a_model_verdict_cannot_pass_the_agent_pipeline`,
  `test_no_model_output_can_reach_a_posting_without_the_deterministic_chain`
- **CURRENT STATUS** — FIXED. No agent can be *configured* with a write
  capability, so there is no call site to forget.
- **WHY IT MATTERS** — this is the AI action boundary. "AI proposes, ATTEST
  proves, policy decides" is a slogan unless the proposing half is structurally
  unable to act.

## D8 / D17 — the AI investigation loop, measured twice and shipped disabled

- **WHAT BROKE** — the loop's hypotheses were not accurate enough to act on.
  D17 then found that D8's conclusion is true of our generated data and *false*
  of Razorpay's, whose recon rows carry anchors ours does not.
- **HOW IT WAS FOUND** — measuring hypothesis precision (0.429), then reading the
  Razorpay API's actual fields.
- **REGRESSION TEST** — `test_the_hypothesis_loop_cannot_return_a_proof_the_solver_did_not_make`,
  `test_no_model_output_can_reach_a_posting_without_the_deterministic_chain`,
  `test_the_ai_precision_number_is_not_hidden_or_improved`
- **CURRENT STATUS** — FIXED, and BOUNDED. The loop cannot produce a proof; the
  precision figure is published rather than buried. The D17 finding is a boundary:
  the measurement is honest about our data and does not generalise to a live
  account, and no live account has been exercised.
- **WHY IT MATTERS** — a disabled feature with a published number is more useful
  than an enabled one with a hidden number.

## D22 — the AI loop proposed the same non-discriminative anchor three times

- **WHAT BROKE** — the hypothesis loop proposed an identical anchor on three
  consecutive rounds, because a **uniqueness** refutation names no rejected
  orders and so fed nothing back. The number that disabled the feature (D8) was
  measured under that loop, which means it was measured under a defect.
- **HOW IT WAS FOUND** — building the Investigate lens meant running the loop
  live and printing what it did, which made the repetition visible.
- **REGRESSION TEST** — `test_the_model_is_visually_and_semantically_separate_from_evidence`
  asserts the string `non-discriminative` reaches the Evidence lens, so a loop
  that stopped reporting non-discriminative anchors would fail it.
- **CURRENT STATUS** — FIXED, COVERED INDIRECTLY. There is no test named for this
  failure. The assertion above lives inside a contract about visual separation of
  model output, and it would catch the regression only because the string happens
  to be asserted there. Conditions 1, 2 and 5 hold; 3 and 4 do not — nothing was
  written against the old behaviour and watched to fail.
- **WHY IT MATTERS** — an AI loop that cannot tell it is repeating itself will
  burn its budget confirming its first idea, and any metric measured under it is
  a measurement of the defect.

## D16 — a wrong rule set, and what it costs

- **WHAT BROKE** — nothing shipped broken. Separating rules from the engine
  raised the question of what a wrong rule costs, and the answer is a wrong fee,
  hence a wrong net, hence a wrong verdict.
- **HOW IT WAS FOUND** — deliberately perturbing the rule set and measuring.
- **REGRESSION TEST** — `test_rules_agree_with_the_frozen_fee_model`,
  `test_a_changed_rule_changes_the_version`,
  `test_a_foreign_rule_set_is_refused_rather_than_absorbed`,
  `test_upi_is_zero_mdr`
- **CURRENT STATUS** — FIXED. Rules are content-hashed; a changed rule changes
  the version, and a foreign rule set is refused rather than absorbed.
- **WHY IT MATTERS** — rules are beliefs, not facts. A run that cannot say which
  beliefs produced it cannot be re-checked later.

## D3 — the settlement calendar was inverted, deleting 2/7 of the data

- **WHAT BROKE** — `business_days_before` written by hand and inverted, silently
  removing two sevenths of the dataset.
- **HOW IT WAS FOUND** — the data volume did not match expectation.
- **REGRESSION TEST** — `test_amount_ceiling_is_deterministic_and_calendar_is_not`
- **CURRENT STATUS** — FIXED, COVERED INDIRECTLY. The named test asserts the
  calendar's non-determinism property rather than the specific inversion. A
  reintroduced inversion would change the generated dataset and move the gates,
  but no test asserts the calendar direction by name.
- **WHY IT MATTERS** — silent data loss during generation makes every downstream
  measurement a measurement of the wrong population.

## D10 / D11 — soundness held for a narrower reason than stated

- **WHAT BROKE** — a property test asserted the engine was sound and established
  that it is sound for a narrower reason. D11 then found the signal for the
  unsearchable failure class was already sitting in an array the solver had.
- **HOW IT WAS FOUND** — property testing, then reading the solver's own
  intermediate state.
- **REGRESSION TEST** — `test_proven_is_correct_when_the_truth_was_reachable`,
  `test_every_false_proof_has_an_attributable_cause`,
  `test_ambiguous_never_carries_one_explanation`,
  `test_contradicted_and_insufficient_carry_no_proof`
- **CURRENT STATUS** — FIXED. Every false proof must have an attributable cause,
  which is the property that turned an unsearchable class into a measurable one.
- **WHY IT MATTERS** — coincidence risk is not eliminable, so it has to be
  priced. The array was already there; nobody had asked it a question.

## D12 — CP-SAT set packing, benchmarked and rejected

- **WHAT BROKE** — nothing. An alternative solver formulation benchmarked against
  the greedy cascade and rejected.
- **HOW IT WAS FOUND** — building both and measuring.
- **REGRESSION TEST** — `test_rejected_features_are_visible_as_rejected`
- **CURRENT STATUS** — REJECTED. `eval/cpsat_study.py` is retained as the
  evidence; deleting it would leave the decision unexplained.
- **WHY IT MATTERS** — the rejected implementations are the part of this
  repository that shows what it decided *not* to keep.

## D20 — gates that fail on safety rather than accuracy

- **WHAT BROKE** — nothing shipped broken. A build that fails on a dropped
  accuracy metric teaches you to tune the metric.
- **HOW IT WAS FOUND** — deciding what the gates should defend.
- **REGRESSION TEST** — `test_the_gates_show_what_they_protect_not_just_a_tick`,
  `test_expected_loss_rounds_toward_checking_not_toward_posting`
- **CURRENT STATUS** — FIXED. Exact-set match may fall; the false-proof rate may
  not rise, and money wrongly auto-posted may not rise at all.
- **WHY IT MATTERS** — an asymmetric gate is the difference between a build that
  protects users and one that protects the headline.

## D1 / D24 — `dataclass(slots=True)` exploded on import, and still did

- **WHAT BROKE** — macOS ships Python 3.9 as `python3`; `slots=` landed in 3.10.
- **HOW IT WAS FOUND** — it crashed on import in 2026-08-21. Then it crashed on
  import again on 2026-08-22, on a clean clone, exactly as before.
- **REGRESSION TEST** — none that runs in the wrong interpreter, because a test
  suite that cannot start cannot report. The defence is executable instead:
  `attest/__init__.py` refuses below 3.11 with the command to fix it.
- **CURRENT STATUS** — was NO REGRESSION and was **wrong about its own
  defence**. This entry used to read "the defence is the pinned version in
  `ci/gates.yml` and the interpreter check in `docs/REPRODUCE.md`" — and
  `docs/REPRODUCE.md` did not exist. A pinned CI version protects CI; it does
  nothing for a person on a Mac. `requires-python` does not help either: the pip
  that ships with 3.9 installs anyway. Now fixed at the only place that runs
  before anything else can fail.
- **WHY IT MATTERS** — the map itself claimed a defence that was not there, and
  only performing the reproduction rather than describing it caught that. This
  is the entry that argues for the whole document.

## D24 — the reproduction, and the three things that did not work

- **WHAT BROKE** — `pip install -e .` failed on a clean checkout (setuptools
  refusing flat-layout discovery with `eval/`, `native/`, `reports/` and
  `contracts/` beside `attest/`); D1 reproduced verbatim; and
  `attest.eval.gate` rewrote `benchmark/results.json` on every run, which is
  what generates README's figures — so *checking* the gates republished the
  headline numbers, and on a machine with no Rust toolchain would have moved
  "value accounted for" from 66.7% to 23.6% unasked.
- **HOW IT WAS FOUND** — cloning into an empty directory and running the
  documented commands instead of writing them.
- **REGRESSION TEST** —
  `test_running_the_gates_does_not_republish_the_numbers_they_check`
- **CURRENT STATUS** — FIXED for the gate side, all five conditions, confirmed
  red against the old behaviour. The packaging and interpreter fixes have no
  unit test — both are conditions a running test suite cannot observe, since
  they decide whether the suite runs at all. `ci/verify.sh` on a clean clone is
  their check, and `docs/REPRODUCE.md` records the commands.
- **WHY IT MATTERS** — the gates are the part of this project that exists to
  check the rest, and they were mutating what they checked. None of the three
  was visible from inside the development environment, because that environment
  was configured before the conditions that break them existed.

## D2 — meet-in-the-middle was the wrong algorithm

- **WHAT BROKE** — nothing shipped. The PRD specified meet-in-the-middle; the
  data said counting DP over the amount axis immediately.
- **HOW IT WAS FOUND** — measuring against real pool sizes.
- **REGRESSION TEST** — none. The counting DP is the only implementation; there
  is nothing to regress *to*.
- **CURRENT STATUS** — REJECTED before shipping. Recorded in `docs/DECISIONS.md`
  and `native/` benchmarks.
- **WHY IT MATTERS** — a plan written before the data is a hypothesis about the
  data.

## D6 — the adversarial sweep

- **WHAT BROKE** — a batch of generated adversarial cases (`_bundle`,
  `_collide`) probing the solver from outside the normal generator.
- **HOW IT WAS FOUND** — subclassing `Generator` in a scratch file specifically
  to construct cases the main generator would not produce.
- **REGRESSION TEST** — `test_kernel_rejects_a_fabricated_proof`,
  `test_kernel_rejects_a_duplicated_order`,
  `test_every_proof_survives_the_independent_kernel`,
  `test_nothing_posts_without_a_unique_kernel_checked_explanation`
- **CURRENT STATUS** — FIXED. The 35-line independent kernel shares no code with
  the prover, so a bug in the prover cannot hide in the checker.
- **WHY IT MATTERS** — a self-checking prover checks its own assumptions. The
  point of the kernel is that it does not share them.

## D21 — the keyboard could not rearrange the drag board

- **WHAT BROKE** — the dashboard could only be arranged with a pointer. A
  keyboard-driven click on the grip also arrived as a pointer event, starting a
  drag that stranded the card under a cursor that never moved.
- **HOW IT WAS FOUND** — trying to use the board with a keyboard.
- **REGRESSION TEST** — none, and none is possible. The drag board lived in
  `board-widgets.js`, deleted on 2026-08-22 with the rest of the sixteen-screen
  UI. The Case Desk has no drag surface.
- **CURRENT STATUS** — SURFACE REMOVED. This entry is kept because deleting it
  would make the repository's accessibility history look cleaner than it was, and
  because the general lesson outlived the widget: `:focus-visible` is never
  suppressed anywhere in the Case Desk, and `prefers-reduced-motion` collapses
  transition durations rather than removing feedback.
- **WHY IT MATTERS** — the fix is gone because the feature is gone, which is not
  the same as the failure never having happened. A map that quietly dropped this
  row would be the document drift D13 is about.

## Responsive and contrast behaviour

- **WHAT BROKE** — nothing currently. Contrast and horizontal-overflow behaviour
  were measured at 360–1512px during P2.6 and reported clean.
- **HOW IT WAS FOUND** — a measurement script run against the live page.
- **REGRESSION TEST** — none. The 90 browser contracts assert text, geometry and
  behaviour; none asserts a contrast ratio or a horizontal-overflow width, and
  none runs at a narrow viewport.
- **CURRENT STATUS** — NO REGRESSION. The measurement was real and is not
  re-run by the suite, so nothing would catch a regression. Recorded here rather
  than claimed as covered.
- **WHY IT MATTERS** — this is the largest untested surface in the product, and
  the CSS audit during dead-code removal showed why it matters: all 38
  apparently-unused classes were built at runtime, and the contracts assert text
  and geometry rather than colour, so a broken verdict colour would pass the
  entire suite.
