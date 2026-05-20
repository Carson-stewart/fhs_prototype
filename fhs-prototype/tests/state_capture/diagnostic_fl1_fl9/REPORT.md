# Diagnostic Report — fl1 vs fl9 Sub-Score Divergence (Phase 6)

**Branch:** `phase6/fl1-fl9-diagnostic`
**Date:** May 20 2026
**Status:** Diagnostic complete. Fix deferred to dedicated session (non-trivial, multi-file).

---

## TL;DR

The divergence is **NOT** a Plaid-mapper bug, an engine bug, or a renderer bug. It's a **frontend → API contract gap**: the form-submit path (`/api/score`) strips the `archetype` field and ALL archetype-extension input fields (FL / SB), causing any non-Individual archetype profile to silently degrade to Individual-W-2 scoring on Compute.

For fl9 specifically: `income_volatility_observed` drops from `0.15` → `None` between fl1 (`/api/profile/{idx}`) and fl9 (`/api/score`). The FL-FSS-1 Income volatility contributor stops firing → it no longer participates in the `contribution_pct` denominator → the remaining contributors (Insurance gap, Retirement gap) have their normalized shares mechanically re-inflated.

| Contributor | fl1 raw share | fl1 displayed | fl9 raw share | fl9 displayed |
|---|---|---|---|---|
| Insurance gap | 49.7% | **50%** | 61.1% | **61%** |
| Retirement gap | 31.7% | **32%** | 38.9% | **39%** |
| Income volatility | 18.6% | **19%** | 0.0% | (not shown) |
| (sum) | 100% | | 100% | |

Numbers match the brief's observed deltas (50→61, 32→39) to ±0.3pp.

---

## Bisect result

**Divergence lives at L1 — IndividualInput layer.** Engine and renderer are blameless.

| Layer | fl1 | fl9 | Differs? |
|---|---|---|---|
| L1 — IndividualInput dataclass | full FL profile loaded | 9 FL/SB fields default-to-None | **YES** |
| L2 — ScoreResult (engine output) | 14 FSS dims contribute | 10 FSS dims contribute (FL extension never runs) | YES (downstream of L1) |
| L3 — score_to_dict (API JSON) | contribution_pct sums over 14 dims | contribution_pct sums over 10 dims | YES (downstream of L1) |
| L4 — normalizeResponse → display | renders 14 dims with 1 nonzero non-Individual contributor | renders 10 dims, only 2 nonzero | YES (downstream of L1) |

### 9 fields that differ at L1

```
field                            fl1                                       fl9
─────────────────────────────────────────────────────────────────────────────────────
archetype                        'freelancer'                              'individual_w2'  ← root cause
business_structure               'sole_proprietor'                         None
income_sources                   [2 entries]                               []
income_volatility_observed       0.15                                      None             ← visible bug driver
months_of_income_history         24                                        0
tax_reserve_balance              8500                                      0
quarterly_tax_due_date           '2026-06-15'                              None
quarterly_tax_estimated_amount   6400                                      0
fixed_monthly_obligations        3000                                      0
freelance_account_separation     'separate_business_account'               'unknown'
previous                         {snapshot dict}                           None
```

---

## Root cause (precise)

### Code locations

1. **`api.py:44-65` — `class ScoreRequest`** is missing the entire archetype-extension input surface:
   - No `archetype` field
   - No FL-specific fields (`income_volatility_observed`, `months_of_income_history`, `tax_reserve_balance`, `tax_reserve_target_pct`, `quarterly_tax_due_date`, `quarterly_tax_estimated_amount`, `fixed_monthly_obligations`, `freelance_account_separation`, `income_sources`, `business_structure`)
   - No SB-specific fields (any AR/AP/LOC/payroll/owner-draw inputs)

2. **`api.py:768+` — `compute_score(req)`** consequently constructs `IndividualInput` from `ScoreRequest` only, leaving `archetype` at its `"individual_w2"` default and every extension field at `None` / `0` / `[]` / `"unknown"`.

3. **`static/index.html:1530-1544` — `computeScore()` body assembly** sends only Individual fields. No `archetype` is sent, no extension fields are sent.

4. **`static/index.html:1408-1421` — `onProfileSelect()` form-load** populates only Individual form fields from the profile response. The FL/SB fields from the loaded profile are visible in the rendered result for that one API call, but discarded the moment the user hits Compute again.

### Mechanism

The user-visible bug is downstream of the input gap, in `_scrub_breakdowns_for_api` in `engine.py` (see §11.1 of CLAUDE.md). That helper computes `contribution_pct` for each FSS dim as `weighted[i] / Σ weighted[j] × 100`. It's a **share-of-total-strain** metric, not an absolute-strain metric.

When fl1 has Income volatility contributing weighted-strain proportional to `pla=0.15 × weight=0.10 = 0.015`, that contribution is part of the denominator and shrinks every other dim's percentage proportionally. Drop it (fl9), and the same absolute Insurance-gap strain (~0.04) now claims a larger share of a smaller pie.

This is correct math for "relative ranking" but reads as "Plaid connection inflated my insurance gap" to the user. The §11.1 design tradeoff (replace `weighted` with `contribution_pct` to plug a trade-secret leak) was sound; the surface gap is that the underlying `weighted` was at least invariant to contributor-set changes, and `contribution_pct` is not.

---

## Scope of impact

**Far broader than the originally-reported Missing coverage / Retirement catch-up drift.**

The frontend-to-API contract gap means **every non-Individual archetype profile silently degrades to Individual-W-2 scoring on Compute**:

- **All 8 Freelancer profiles** lose income volatility / tax-reserve insufficiency / fixed-obligation coverage / volatility trajectory strain contributors on form submit.
- **All 5 Small Business profiles** lose AR aging / AP compression / LOC utilization / payroll coverage strain contributors on form submit.
- **All archetype-specific recommendations** are dropped on form submit. `extend_score_for_freelancer()` and `extend_score_for_small_business()` are gated on `inp.archetype` and never fire.
- **Famine-state framing** for FL would be skipped entirely on form submit (no `famine_context`, no protect-tax-reserve / focus-essentials primary).

**Verification by inspection:** the 15/15 archetype compliance test suite (`test_runner.py`) runs profiles through `score_individual()` directly, NOT through the API surface. So the test gate is green even with this contract gap — the gate never exercises the form-submit path. This is exactly the kind of bug that only surfaces under integration testing across the full stack.

### What "form submit" means in current UX

In the current vanilla frontend, a user reaches the form-submit path through:
- Clicking **Compute** at any time after the form is populated
- Connecting Plaid (which can trigger a re-score via the form's current state)
- Editing any field and re-running

Selecting a test profile from the dropdown uses `/api/profile/{idx}` and dodges the bug. **The only profiles users will see scored correctly today are the ones they never re-compute after loading.** That's not a beta-ready state.

---

## Plaid presence sensitivity

The bug is **not Plaid-specific**. Plaid connection is incidental — the bug fires on ANY non-Individual profile the moment the user submits the form. The reason fl9 surfaces it visibly is just that "fl1 + Plaid banks" is a natural visual-test scenario where Compute gets re-run after Plaid sync.

Without this fix, even fl1 itself would exhibit the bug if the user clicked Compute after the initial profile load.

---

## Soft observation re Pass 2's `normalizeResponse` lead

Pass 2 flagged `normalizeResponse` (static/index.html:2228+) as a possible cause: flat vs nested-with-`d.scores` shape branching. **That lead does not pan out as a cause for the sub-score drift.** Both shape paths populate the same keys (`fhs_breakdown`, `fss_breakdown`, `frs_breakdown`) from analogous source paths. The keys themselves and the values themselves are identical for fl1 across shapes; the values differ for fl9 vs fl1 because the engine computed different sub-scores against a different input.

The Pass 2 observation was correctly cautious and worth checking, but the bisect cleanly places divergence one layer earlier (at IndividualInput construction, not at response normalization).

---

## Fix recommendation

### Recommended: deferred fix in dedicated session

**Patch size estimate:** Not trivial. Touches three files at minimum.

**Surface 1 — `api.py` (ScoreRequest extension):** Add `archetype` field plus all archetype-extension input fields with safe defaults matching `IndividualInput`. ~25 fields. Schema additions + threading into `IndividualInput` construction in `compute_score`. ~50 lines added.

**Surface 2 — `static/index.html` (form-submit body assembly):** `computeScore()` needs to thread `archetype` + extension field values into the request body. Archetype is currently held in `<select id="profile-select">` — its `value` (an index into PROFILES) needs translation to the loaded profile's `input.archetype`. The extension field values are not currently held in any form input; they need to be cached from the last `/api/profile/{idx}` response into a JS state variable that `computeScore()` reads. ~30 lines added.

**Surface 3 — Test coverage:** Existing `test_runner.py` runs `score_individual()` directly and won't catch this regression. A new integration test that POSTs to `/api/score` with archetype-bearing payloads and asserts the resulting breakdowns match the synthetic-profile-path scoring is the right safety net. ~80 lines for the test file.

**Optional Surface 4 — `contribution_pct` semantic clarification:** Even after the input gap is fixed, the underlying issue that `contribution_pct` swings when a contributor enters/leaves is real. Options:
- A. Keep current behavior + UX rename to "Share of strain mix" (column label)
- B. Switch the bar to render `pla` directly (absolute strain magnitude) instead of `contribution_pct`
- C. Compute `contribution_pct` against a fixed denominator (sum of theoretical maximums)

This is a UX research decision — defer to a separate brief.

### Why this isn't an in-session trivial fix

The brief sets the trivial-fix bar at "≤10 lines changed, single file, no new tests required, no cascading effects." This fix:
- Touches 3 files minimum (api.py, static/index.html, plus a new integration test)
- Adds ~50+25+80 = ~155 lines minimum
- Requires careful schema design for which extension fields to expose in the public API surface vs which to keep internal
- Has cascading effects on the API contract that need careful staging (e.g., `/api/score/previous` likely needs the same treatment)

**Conservative call: defer.** The fix gets its own session brief.

### Beta criticality

**HIGH.** This is exactly the kind of trust-erosion bug pre-beta polish was meant to clear. Without this fix:

- Every Freelancer beta user will see Income volatility / Tax reserve / Coverage strain disappear from their FSS bars after the first Compute click. The "Plaid connected, my financial picture got worse" perception is a leading indicator for cancellation.
- Every Small Business beta user will see AR aging / AP compression / LOC utilization disappear similarly.
- Famine-state recommendations stop firing on form-submit — the most carefully-authored brand-voice surface in the project (Phase 5b.4) won't reach the user.

**This should ship before any beta where users can hit Compute.** A beta with synthetic-profile dropdown only and no Compute button would dodge the bug, but isn't a realistic beta scope.

### Risk of the fix

Once the schema gap is closed, no further math changes are required — the engine already does the right thing when given the full input. The risk is in:

1. **Frontend state-cache regressions** — the extension-field cache logic needs to invalidate cleanly on archetype switches and on Plaid sync. The Phase 4 P4-H4 `dataset.userEdited` pattern is the existing precedent; the new cache should follow that shape.
2. **Backward compatibility** — old `/api/score` request payloads (no archetype) should default to Individual W-2 gracefully (which is current behavior). This is preserved by giving every new ScoreRequest field a safe default.
3. **Test coverage** — the integration test addition is the critical safety net; without it, the same class of bug can re-surface as schemas evolve.

---

## Beta-readiness impact

Pass 2's closeout listed four remaining items between current state and beta launch:

1. fl1/fl9 sub-score divergence diagnostic ← (this session, done)
2. Phase 6 real-data calibration
3. Phase 7b production hardening
4. Phase 7a React Native conversion

**This diagnostic surfaces a new pre-beta-critical item:** the form-submit archetype-stripping bug. It belongs at #1.5 on the list — between "diagnostic" (now done) and "real-data calibration" (which the broken API contract would corrupt; you can't calibrate against synthetic users whose API path drops 9 input fields).

Revised pre-beta list:

1. ~~fl1/fl9 sub-score divergence diagnostic~~ ✅ (this session)
2. **Form-submit archetype-stripping fix** (NEW — discovered by this diagnostic; estimated dedicated session; HIGH beta criticality)
3. Phase 6 real-data calibration (blocked by #2)
4. Phase 7b production hardening
5. Phase 7a React Native conversion

---

## Captured state files

- `tests/state_capture/diagnostic_fl1_fl9/_capture.py` — capture tool (4-layer snapshot)
- `tests/state_capture/diagnostic_fl1_fl9/fl1.json` — fl1 four-layer snapshot
- `tests/state_capture/diagnostic_fl1_fl9/fl9.json` — fl9 four-layer snapshot
- `tests/state_capture/diagnostic_fl1_fl9/_diff_summary.json` — bisect diff summary
- `tests/state_capture/diagnostic_fl1_fl9/REPORT.md` — this file
