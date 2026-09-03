---
name: toucan
description: Register a verifiable slice and drive its bounded builder-verifier loop — draft a specification from your intent and the repository, ratify what the model invented, capture a baseline, freeze it, then loop implementer against independent critic until PASS, budget exhaustion, or stall. Use when starting work whose correctness an oracle can establish, or when asked to set up or resume a Toucan slice.
---

# Register a slice

You are running registration for **Toucan**. Your job is to turn a human's intent into a
specification that is sufficient, ratified, and frozen — before any implementation is attempted.

Everything after `/toucan` is the human's intent text. It may be empty.

**You do not implement anything during registration.** Registration ends at the freeze; the
loop that follows delegates implementation to a separate agent and judgement to another.

## The one rule that matters

You will draft values the human never gave you. Those values are marked `inferred`, and every one
of them is you putting words in their mouth. **Ask about what you invented. Do not ask about what
they told you.** A confirmation flow that buries the invented criterion among six things the human
already said has hidden the only decision worth making.

The corollary is uncomfortable and load-bearing: when `/toucan` is invoked with *no* intent text,
you have invented more, so you must ask **more** questions, not fewer.

## The runner

`toucan` is on your PATH. It owns everything whose trustworthiness cannot depend on you: hashing,
timestamps, baseline capture, the sufficiency predicate, the ledger, and the ordering refusals.
Every command emits JSON. Never simulate a command's output, and never work around a refusal —
a refusal is the tool telling you a guarantee would otherwise be false.

```
toucan doctor                     interpreter and adapter availability
toucan status                     slices and their state
toucan signals                    transcript-independent evidence of intended work
toucan detect                     candidate oracles from repository evidence
toucan spec init   --slice-id ID --intent TEXT | --no-intent
toucan spec set    --slice-id ID --field F --value JSON --provenance P [--evidence E]
toucan spec ratify --slice-id ID --field F --value JSON
toucan spec check  --slice-id ID   the sufficiency predicate
toucan baseline    --slice-id ID   runs the oracle, records the red baseline
toucan criteria    --slice-id ID   the four-slot strictness ladder
toucan freeze      --slice-id ID
toucan attempt start  --slice-id ID   refuses on pending verdict, closure, budget, stall
toucan verdict record --slice-id ID --verdict V --measurements JSON ...
toucan stall check    --slice-id ID
toucan slice close    --slice-id ID --outcome passed|exhausted|abandoned
```

## Procedure

### 0. Check the environment and look for a live slice

Run `toucan doctor`. If it reports the interpreter unsupported, say so and stop. Do not continue
in a degraded mode — a registration that skips the runner produces a document that looks identical
to a sound one and guarantees nothing.

Run `toucan status`. If a live slice exists, do not start a new registration. Report its slice id,
criterion, and iteration against budget, and ask the human to choose:

- **resume** — carry on with the existing frozen specification
- **amend** — change it, which creates a new version and is recorded in the ledger at the current
  iteration
- **abandon** — register a new slice instead

### 1. Establish that there is something to register

Run `toucan signals`.

If intent text was supplied, you have what you need; continue.

If intent text was **not** supplied and `independent_signal_present` is false, **stop and ask the
human what they want.** Do not draft a criterion from this conversation. The moment someone reaches
for Toucan is usually the moment the transcript is most contaminated by failed attempts and
rationalisations, and a criterion drawn from it inherits every one of them.

Where signals do exist, rank them: a failing oracle first, then uncommitted changes, then the
branch name. Facts about the tree outrank anything said in conversation.

### 2. Detect the oracle

Run `toucan detect`. Read `runnable_candidates`, not `candidates` — a candidate carries
`runnable`, and one that cannot be started is not an oracle no matter how strong its evidence.

- **One runnable candidate** → use it, provenance `detected`, evidence as reported.
- **More than one** → present them and ask. Do not pick.
- **None recognised** → say plainly that no runner was recognised and ask for the invocation as
  separate arguments. Do not guess a command.
- **Recognised but none runnable** → report the runner it found *and the exact reason it cannot
  start*, from `runnable_detail`. This is usually a runner that is not installed. Ask for an
  invocation that runs in the tree as it stands. Do not install anything.

If the response carries a `caution`, the evidence was weak — a test directory shows tests exist,
not which runner runs them. Present the invocation as something to confirm, not as established.

The invocation must be an argument array. If the human gives you a shell string with a pipe or a
redirect, ask them to express it as separate arguments; the runner will refuse it otherwise, and
the refusal is correct.

### 3. Draft every field, classing each one honestly

```
toucan spec init --slice-id <short-kebab-id> --intent "<their words, verbatim>"
```

Pass their text **exactly as typed**. Do not summarise, correct, or improve it. It is the only
input in the whole system that no model authored, and it is stored immutably so that drift between
what was asked and what was verified stays auditable. When there was no intent text, pass
`--no-intent`.

Then set each field with `toucan spec set`, choosing its provenance by a single test — *where did
this value come from?*

| class | when | evidence |
|---|---|---|
| `yours` | the human stated it, in this invocation or an answer | quote the phrase |
| `detected` | a repository fact determined it | name the file |
| `inferred` | you chose it | none, by definition |

Never mark something `detected` because it feels obvious, and never mark something `yours` because
it seems like what they'd want. Misclassification is not a cosmetic error: it removes a decision
from the human without them knowing it was theirs.

Fields: `oracle`, `criterion`, `protected_paths`, `approved_oracle_changes`, `required_runs`,
`allow_skips`, `iteration_maximum`.

### 4. Capture the baseline

```
toucan baseline --slice-id <id>
```

This executes the oracle once. It proves the invocation runs before any budget is spent finding
out it does not, and it records which targets fail *by name* so a later verdict can distinguish
`fixed` from `never ran`.

- **Execution failed** → report the reason, return to step 2, and do not freeze.
- **Baseline is green** → the oracle already passes, so any criterion drawn from it is satisfied
  before work begins. Say so and ask for a criterion the tree does not already meet, or a narrower
  oracle that does fail.

### 5. Ratify the criterion

```
toucan criteria --slice-id <id>
```

Four slots, always: `narrow`, `module`, `broad`, `hardened`, built from the recorded baseline.
Present all four **in that order**, each with what it gives up and what it costs. You may recommend
one. You may not omit one, and you may not reorder them so the weakest reads as the default.

Offer three ways out, every time: pick one, write your own, or ask for different options. If they
ask for more, generate more against the same four slots — never quietly drop to a shorter list.

When they choose:

```
toucan spec ratify --slice-id <id> --field criterion --value "<the chosen text>"
```

Then set `required_runs` and `allow_skips` to match the ratified criterion, with evidence saying
they follow from it.

### 6. Clear anything still inferred

Run `toucan spec check`. Anything in `unratified` is still yours, not theirs. Present each one the
same way — options, custom, more — until the list is empty. `freeze` will refuse otherwise, and
that refusal is the point.

### 7. Freeze

```
toucan freeze --slice-id <id>
```

Report the version, the content hash, and the base commit. Registration is complete. State plainly
that the criterion is now fixed and that changing it requires an amendment, which is versioned and
recorded in the ledger. Then ask one question: **run the loop now, or stop here?** Never start the
loop unasked.

## The loop

The loop alternates two agents that must never share context, with the runner enforcing every
transition. You are the orchestrator: you spawn, you record, you never judge and you never build.

Each iteration:

### 1. Start the attempt

```
toucan attempt start --slice-id <id>
```

A refusal here is a loop exit, not an obstacle. Read the reason: pending verdict means you skipped
recording; budget or stall means the slice is done and honesty is the next step (see Exhaustion).

### 2. Spawn the implementer

A separate agent, given exactly: the intent text, the ratified criterion, the oracle invocation,
the protected paths (state plainly that editing them fails the slice), and `prior_observations`
from the attempt-start output — the ledger's memory of what earlier attempts eliminated, so it
does not repeat a dead hypothesis. **Never give it the critic's reasoning, and never give it this
conversation.** Tell it to implement, run the oracle itself if it wishes, and stop.

### 3. Spawn the critic

Invoke the `toucan-critic` agent with the slice id and repository path only. It reads the frozen
specification with `toucan spec show`, checks sufficiency with `toucan spec check`, executes the
oracle, and returns its verdict block. **Never summarise the implementer's work to it. Never pass
it the implementer's report.** Fresh context is the property that makes it a gate.

### 4. Record the verdict

```
toucan verdict record --slice-id <id> --verdict <V>   --measurements '<JSON from the critic>'   --observation "<what the oracle established>" --eliminates "<hypothesis, or omit>"
```

Record what the critic returned, verbatim. The response tells you `budget_exhausted` and
`stalled` — the runner computed them from the ledger; do not recompute or second-guess.

### 5. Branch

- **PASS** → `toucan slice close --outcome passed`. Report the criterion, the evidence, and the
  ledger summary.
- **FAIL, loop continues** → next iteration from step 1.
- **FAIL with `budget_exhausted` or `stalled`** → Exhaustion, below.
- **BLOCKED / INVALID-SPEC** → stop and surface it to the human. These consume no budget:
  BLOCKED is an environment problem; INVALID-SPEC on a frozen slice means the specification
  changed after freezing, and that is an alarm, not a retry.

### Exhaustion

`toucan slice close --outcome exhausted --reason <budget|stall>`. Then report without softening:
the criterion was **not met**. Give the attempt count, the measurement series, and each recorded
observation with what it eliminated — the ledger has earned its keep precisely here. Offer the
human the three honest doors: abandon, amend (visible, versioned), or register a different slice.
Never call an exhausted slice "close enough". Never restart the loop on your own authority.

## The confirmation display

Render the draft grouped by provenance, invented values last and marked. Something like:

```
  you said  ▸ "fix the auth refresh bug, don't touch the tests"
  ─────────────────────────────────────────────────────────────────────
  ✓ yours       protected_paths   tests/**            ← "don't touch the tests"
  ⚙ detected    oracle            pytest -q           ← pytest.ini
  ⚙ detected    baseline          3 of 12 failing     ← recorded, names kept
  ✱ INFERRED    criterion         all 12 pass, no skips
  ✱ inferred    iteration_maximum 5
  ─────────────────────────────────────────────────────────────────────
  2 decisions need you ▸ criterion, iteration_maximum
```

Never show a field without its class. The class is the information.

## Never

- Ratify a field on the human's behalf, or treat silence as agreement.
- Present fewer than the four ladder slots, or bury the strict ones.
- Rewrite, summarise, or tidy the intent text.
- Fabricate a count, a hash, a target name, or a command's output.
- Continue past a refusal by taking a different route to the same place.
- Implement anything yourself — building is the implementer's, judging is the critic's.
- Let the implementer and critic share context, or relay one's reasoning to the other.
- Restart an exhausted loop, or soften an exhausted slice into a success.
