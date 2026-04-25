---
name: debugging
description: Systematic bug hunt — check KB and prior sessions before reproducing
---

# Debugging

## Steps

1. **Search for prior context** — call `store_search` on `hanuman/atoms` for the error message or module name. Check if this bug has been seen before.
2. **State the bug** — exact error, `file:line` if known, what was expected vs what happened.
3. **Identify the smallest reproduction** — what is the minimum input that triggers this?
4. **Hypothesize** — list 2-3 candidate causes, ranked by likelihood.
5. **Test the top hypothesis first** — read the relevant file, check the relevant line. Confirm or eliminate.
6. **Fix only what is broken** — no surrounding cleanup, no refactoring. One surgical change.
7. **Run the relevant test** — confirm the fix holds. If no test exists, write one first.
8. **Commit** — message: `fix(<module>): <what was wrong> — <why it was wrong>`

## Rules

- Never skip step 1. Prior session context often contains the root cause.
- Never fix without a test. A fix without a test is just a guess.
- Step 6 is a hard constraint: surgical only. Bug fixes don't get free refactors.
