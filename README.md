# Toucan

A bounded builder–verifier loop with an executable oracle.

Toucan gates correctness by **running your project's oracle** — its test suite, build, type
checker, linter, or benchmark — and judging the result against a criterion registered *before*
the work was attempted. It is built for the failure mode where an agent reports success and the
report is the only evidence.

**Uncertainty is never PASS.**

## Install

```
/plugin marketplace add fluxscale/toucan
/plugin install toucan@fluxscale
```

Or from the command line:

```
claude plugin marketplace add fluxscale/toucan
claude plugin install toucan@fluxscale
```

To try it without installing:

```
claude --plugin-dir /path/to/toucan
```

## Usage

```
/toucan fix the token refresh bug, don't touch the tests
```

Everything after `/toucan` is your own words, and they are stored verbatim in the frozen
specification so that drift between what you asked for and what got verified stays auditable.
The argument is optional — with none, Toucan drafts from the repository alone and asks you more,
because it invented more.

Registration probes the repo, runs your oracle once to record a red baseline, and shows you a
draft in which every field is marked with where it came from:

```
  you said  ▸ "fix the token refresh bug, don't touch the tests"
  ──────────────────────────────────────────────────────────────────────────
  ✓ yours       protected_paths   tests/**, **/conftest.py    ← "don't touch the tests"
  ⚙ detected    oracle            pytest -q                   ← pytest.ini
  ⚙ detected    baseline          1 of 3 failing              ← recorded, name kept
  ✱ INFERRED    criterion         full suite passes, no skips
  ✱ inferred    iteration_maximum 5
  ──────────────────────────────────────────────────────────────────────────
  2 decisions need you ▸ criterion, iteration_maximum
```

**You are only asked about the starred rows.** What you said is not re-litigated, and what the
repository determined is shown for correction rather than interrogation. The rule is that you
spend attention on what the model invented, nothing else.

The criterion always comes as four slots, weakest first, each naming what it gives up:

| slot | example | gives up |
|---|---|---|
| `narrow` | the failing targets pass | collateral breakage elsewhere |
| `module` | the containing module passes, no skips | regressions outside that module |
| `broad` | the full oracle passes, no new skips | nothing; costs a full run |
| `hardened` | broad, twice, no retries | nothing; costs two full runs |

Pick one, write your own, or ask for different options. The slots are fixed by the runner and
filled from the recorded baseline, so a strict option is always on the table.

Then it freezes: a content hash, a timestamp, the base commit, and the baseline result. Changing a
frozen specification afterwards is an amendment — a new version, a recorded diff, and a ledger
entry naming the iteration it happened at.

### Permissions

The first `/toucan` prompts to approve the `toucan` runner, like any other command. To silence it,
add one line to `.claude/settings.json`:

```json
{ "permissions": { "allow": ["Bash(toucan:*)"] } }
```

A plugin cannot ship this on your behalf, which is why it is a documented step rather than a
default.

## What ships today

**`toucan-critic`** — an independent verification agent. Invoke it after an implementer claims a
slice is complete. It executes the registered oracle itself, checks that the oracle was not
weakened to produce the result, establishes that the required work actually ran, applies the
criterion literally, and returns one of four verdicts:

| Verdict | Meaning |
|---|---|
| `PASS` | Criterion met literally, oracle intact, execution positively evidenced |
| `FAIL` | Criterion contradicted, unverifiable, flaky, or the oracle was changed without approval |
| `BLOCKED` | Verification cannot run for reasons external to the candidate |
| `INVALID-SPEC` | The frozen contract is missing or insufficient to decide |

Three properties make it a gate rather than a rubber stamp:

- **Fresh context.** The critic never reads the implementer's reasoning. It judges three
  artifacts: the registered specification, the diff from baseline, and the oracle result.
- **Oracle integrity is checked first.** An unapproved change that weakens, bypasses, narrows, or
  replaces the oracle is `FAIL` regardless of a green result — and the finding is the change
  itself. Untracked files are included, because a new `conftest.py` is the most convenient place
  to hide an override.
- **Execution is proven, not assumed.** Exit status zero is insufficient. The critic establishes
  that the registered targets were collected and ran, under the registered conditions, against
  the current candidate rather than a cache or a stale build.

**`/toucan`** — slice registration, described above.

**`toucan`** — the runner behind both, on your `PATH` while the plugin is enabled. It owns
everything whose trustworthiness cannot rest on a model behaving well: hashing, timestamps,
baseline execution, the sufficiency predicate, the hash-chained ledger, and the ordering refusals.
`toucan freeze` refuses without a recorded baseline; `toucan attempt start` refuses without a
freeze. The happens-before relationship the critic depends on is a property of the tool, not a
promise in a prompt.

Registration and the critic share **one** sufficiency predicate. Registration cannot terminate on a
specification the critic would reject — so an `INVALID-SPEC` verdict on a frozen slice means the
specification changed after freezing, which is worth alarming on.

## What does not ship yet

The loop itself: spawning implementers, iteration accounting beyond `attempt start`, and automatic
verdict handling. Registration and verification are both complete; orchestrating them is manual for
now.

Adapter coverage is **pytest** only. Outside it, Toucan says it could not detect an oracle and asks
you for the invocation, rather than guessing one.

Detection verifies that a candidate invocation can actually start before offering it, and
distinguishes strong evidence (a config file naming the runner) from weak (a `tests/` directory,
which shows tests exist but not which runner runs them). A recognised-but-uninstalled runner is
reported with the reason it cannot start, not proposed and then discovered broken at baseline.

## Relationship to Gauntlet Loop

Toucan and [Gauntlet Loop](https://github.com/robonuggets/gauntlet-loop) are complementary.
Gauntlet gates comparative quality by blind comparison against a named reference — designs,
essays, research output, anything taste-driven. Toucan gates correctness by a preregistered
executable criterion. A deliverable with both objective and subjective requirements wants both.

The builder–critic split, fresh critic context, per-piece iteration, and binary judgment all have
direct precedent in Gauntlet Loop. Toucan's distinct contribution is executable evidence,
oracle-integrity checking, bounded retries, and durable failure memory.

## Requirements

Claude Code, and Python 3.8+ for the runner — standard library only, nothing to install. The
runner ships on your `PATH` automatically while the plugin is enabled.

`toucan doctor` reports whether the interpreter and adapters are available. Where Python is
missing, Toucan says so and stops rather than falling back to a prompt-only mode that would look
identical while guaranteeing nothing.

## Development

```
python3 -m unittest discover -s tests          # 78 tests, no dependencies
TOUCAN_TEST_PYTEST=/path/to/pytest python3 -m unittest discover -s tests
```

The second form additionally verifies the pytest adapter against a real pytest. Without it those
five tests skip, so the suite runs anywhere.

## License

MIT — see [LICENSE](LICENSE).
