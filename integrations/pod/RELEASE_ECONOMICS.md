# Signed per-unit release economics (version 1)

LAUNCH now requires current economics from the server-owned Money Factory snapshot.
Missing legacy economics blocks submission; PRELAUNCH production and publication-
disabled dry runs retain their existing behavior. This does not enable publication.

The grant carries a verified price (positive safe-integer amount_minor, currency
and evidence_id) and economics with these required fields:

| Fields | Contract |
|---|---|
| schema_version, verified, all_variable_costs_included | 1, true, true |
| job_id, business_id, account_id, platform, package_sha256 | Exact release scope |
| currency, price_minor | Match the grant's verified price |
| expected_receipts_minor | Positive safe integer, no greater than sale price |
| variable_cost_minor | Nonnegative safe integer |
| minimum_contribution_minor | Explicit nonnegative safe integer |
| minimum_margin_bps | Explicit integer from 0 through 10000 |
| evidence_event_id | Verified upstream economic-decision event identity |
| source_evidence_ids | 1–32 unique nonempty IDs, including the price evidence_id |
| observed_at_ms, valid_until_ms | Integer timestamps: observed by now, still valid |

Expected receipts are per sold unit after marketplace deductions, including any
platform printing/royalty calculation already applied upstream. Variable costs
include all remaining per-unit costs and allocations under the approved upstream
policy, without charging the same deduction twice. Taxes/fees/cost treatment and
currency must be established from actual provider and business evidence. Neither
repository infers a royalty rate, FX rate, zero cost or minimum margin. This
version handles a single-currency unit sale whose receipts do not exceed price;
other economic models require an explicit later contract.

Contribution = expected receipts - variable costs. Both the absolute contribution
minimum and contribution/expected-receipts margin must pass. The implementation
uses BigInt cross multiplication to compare basis points without floating-point
rounding, then returns the exact safe-integer contribution. A supplied derived
profit value is ignored. Zero minima are accepted only when explicitly signed;
there is no default policy authorizing them.

Money Factory must load this evidence from its existing authoritative snapshot,
with approval.economics_event_id matching the exact economic-decision event.
It validates before signing and caps the grant expiry at the evidence's validity.
Its HTTP endpoint still accepts only job_id, never request-supplied economics.
Content Control validates again after artifact checks, fresh-grant resolution and
local database eligibility, immediately before the adapter call. An expired,
incomplete, differently scoped or below-minimum budget cannot submit.

The two repositories contain the same versioned economics validator and numeric
test vectors. The MF cross-repository workflow pins Content Control and checks a
signed grant through its actual release validator. Adaptation requires a current,
properly scoped upstream approval; do not refresh timestamps on stale evidence.

This is a release budget, not realized profit or an immutable financial event.
No revenue is booked here. Actual source evidence, live snapshot configuration,
cost policy approval and provider reconciliation remain separate acceptance work.
Publication stays disabled until the owner's separate release approval.
