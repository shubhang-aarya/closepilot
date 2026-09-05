# The one diagram

Used in README, slides, demo and submission. There is one, and this is it.

```
   SOURCE                Razorpay recon rows · webhooks · CSV
     │                   payment_id · settlement_id · refund_id · fee · UTR
     ▼
   NORMALIZATION         parse_amount — integer paise, exactly or refused
     │                   deduplicate by SOURCE identity, never by amount
     ▼                   unreadable rows → Rejection(index, reason, identity)
   BLOCKING              settlement calendar · amount ceiling · already claimed
     │
     ▼
   SEARCH SPACE          2,328 ──▶ 23        every removal recorded, with
     │                                       whether it was a CONVENTION
     ▼                                       or DETERMINISTIC
   SOLVER                counting DP over the amount axis
     │                   L1 exact ▸ L2 anchored ▸ L3 subset-sum ▸ L4 packing
     ▼
   PROOF CERTIFICATE     order ids · gross · fee · net · residual · tolerance
     │                   ├── re-derived by a 35-line INDEPENDENT KERNEL
     │                   │   that shares no code with the solver
     │                   └── postable ⟺ members ⊆ recorded universe
     ▼                                ∧ space integrity ≠ COMPROMISED
   POLICY ENGINE         P(error) × cost(error)  <  cost(review)
     │                   Wilson UPPER bound, rounded toward review
     ▼                   no proof ⟹ UNPRICED, never a fabricated zero
   ACTION                capability checked at CONFIGURATION time
     │                   POST_ENTRY is held by NO agent
     ▼
   LEDGER                double entry, balanced to the paisa, or a stated refusal


   ┌─────────────────────────── the model sits outside ────────────────────────┐
   │                                                                           │
   │    LLM ──▶ HYPOTHESIS ──▶ SOLVER ──▶ ACCEPT / REFUTE ──▶ ENGINE decides   │
   │     ◇          ◇             ○              ○                ●            │
   │                                                                           │
   │  The model may PROPOSE an anchor. It may not verify one, price one, or    │
   │  post one. Every arrow out of the model leads into the solver, and the    │
   │  solver's answer is arithmetic. On setl_000225 the model proposed a       │
   │  capture-batch anchor, the solver returned NON-DISCRIMINATIVE, and the    │
   │  engine ABSTAINED — verdict_changed: false.                               │
   │                                                                           │
   │  This is enforced, not drawn: attest/agents.py refuses to CONSTRUCT an    │
   │  agent holding a write capability, so there is no call site to forget.    │
   └───────────────────────────────────────────────────────────────────────────┘
```

## Reading it

**Left column is the deterministic path.** Money moves only along it. Every stage
records what it did to the search space, so a verdict can be re-derived rather
than trusted.

**The box is the model.** It touches the path at exactly one point — proposing a
hypothesis for the solver to test — and the solver's verdict is arithmetic, not
judgement. The three marks are the product's visual grammar throughout:
**◇ model** proposes, **○ solver** tests, **● engine** decides.

**Two gates decide whether money moves.** The independent kernel re-derives every
proof from source records, and `postable` requires the cited orders to *belong*
to the recorded candidate universe — cardinality is not membership, which is
what CORE-002 was.
