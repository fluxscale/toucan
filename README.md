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

The critic is read-only. It does not repair the implementation, prescribe the patch, advance a
slice, or decide what happens next.

## What does not ship yet

Toucan is early. The critic is complete and usable on its own; the machinery that produces the
specification it consumes is in design:

- **Slice registration** — `/toucan`, which drafts a specification from your intent and the
  repository, asks you to ratify only the fields it invented, runs the oracle once to establish a
  baseline, and freezes the result before any implementation begins.
- **The loop** — iteration budgets, durable failure memory, and orchestration between the
  implementer and the critic.

Until registration ships, the critic's invocation contract must be supplied by hand. The contract
is documented in [`agents/toucan-critic.md`](agents/toucan-critic.md).

## Relationship to Gauntlet Loop

Toucan and [Gauntlet Loop](https://github.com/robonuggets/gauntlet-loop) are complementary.
Gauntlet gates comparative quality by blind comparison against a named reference — designs,
essays, research output, anything taste-driven. Toucan gates correctness by a preregistered
executable criterion. A deliverable with both objective and subjective requirements wants both.

The builder–critic split, fresh critic context, per-piece iteration, and binary judgment all have
direct precedent in Gauntlet Loop. Toucan's distinct contribution is executable evidence,
oracle-integrity checking, bounded retries, and durable failure memory.

## Requirements

Claude Code. The registration tooling, when it lands, will additionally require Python 3 (standard
library only, no packages to install).

## License

MIT — see [LICENSE](LICENSE).
