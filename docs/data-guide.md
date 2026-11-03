# Private data preparation and qualification

See `cases/zheng-2025/data-contract.json` and the supplier audit. Raw observations are user-authorized files outside the public Git repository. Existing AStockDB is the preferred source for validated common A-share fields; this project does not assume it includes convertible bonds, historical contract events or factor returns. Its local runtime is checked separately in the acceptance evidence.

## Manifest

The private directory contains `manifest.json` and `observations.jsonl`, optionally `factors.csv`. `files` maps each relative filename to its actual SHA256. Paths escaping the manifest directory are rejected. Every file's bytes are verified before and after calculation. Approval also freezes the manifest bytes.

```json
{
  "source": "qualified-provider-and-version-description",
  "license": "user-authorized-private-research",
  "snapshot_date": "2026-11-03",
  "evidence_level": "alternative_vendor",
  "sample_start": "2000-07",
  "sample_end": "2022-06",
  "files": {"observations.jsonl": "ACTUAL_SHA256"}
}
```

`evidence_level` may be `synthetic`, `alternative_vendor` or `original_comparable`. It is a declaration, not independent certification. `original_comparable` does not override model limitations or unexecuted objectives. Dates in observations must be ISO calendar dates inside the declared sample.

Each JSONL row contains formation `date`, `bond_id`, positive `market_price`, decimal holding-month `next_return`, decimal holding-month `risk_free`, and a historical `contract` accepted by `contract_from_dict`. Optional issue size must be the issue size for appendix size weighting, not remaining principal.

`contract.risk_free` is annual continuous pricing yield; the row's `risk_free` is the one-month holding return from the paper's deposit-rate convention. They have different meanings. Current conversion price must match current raw stock price; estimate volatility from the stated historical250trading days with adjustment/corporate-action convention documented. Do not insert present-day terms into old months.

The provider preflight does not build a full qualified panel. Normalizing textual clauses, event histories, payment conventions, rights decisions, calendars and old-bond missingness requires separate source verification. No paid subscription automatically resolves these requirements.

## Factor returns

`factors.csv` has a `date` column labelled by actual holding month end, plus decimal monthly factor-return columns. Put its SHA256 in `files`. Add `factor_models` to the manifest, for example `{"Carhart4":["MKT","SMB","HML","UMD"]}`. Supported definitions have4/5/4/4/3explicit columns for Carhart4/FF5/HXZ4/SY4/DHS3. Their provenance, definitions, original vintages and exact units must be documented separately.

The recipe shifts formation month to the following holding month explicitly. The factors may contain extra months, but every selected holding-month date must match exactly. Missing values/months, unknown models, bad factor counts and rank-deficient regressions are recorded as errors. No interpolation or silent inner-join deletion occurs. Paper Table3 alpha targets are already stored in decimal units; display percentages multiply once by100.

## Returns and terminal events

`next_return` is a supplied, verified next-month total return. Include coupon cashflows and final conversion/redemption/put proceeds using a declared tax and clean/dirty convention. A missing terminal payoff is an error, never a zero return or a vanished holding. The current recipe does not infer total returns from `cb_daily.pct_chg`.

The last formation month may require a subsequent holding month outside the pricing sample. Disclose the return window and any exclusion rather than choosing an endpoint to force the published counts. The raw sample-count targets and regression-count targets are separate.

## Output status

Without a private dataset, the paper recipe returns BLOCKED with392unmeasured numerical targets. With data, it calculates prices, per-rowMCerrors/method notes, Table1 descriptive statistics, Table2 group/MKT results and optionally Table3 factor results. The remaining figures/appendix robustness remain inventoried and not certified. A full scientific replication cannot pass until those core/explained targets, model assumptions and independent data-qualified rerun are resolved.
