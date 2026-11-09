# 7. Represent money as integer wei

**Status:** Accepted

## Context

Prices are ETH amounts with 18 decimal places. Binary floating point cannot
represent most of them exactly: `0.1 + 0.2 != 0.3`. Every conversion between ETH
and wei is also a chance to be off by a factor of 10^18. Our safety checks
compare prices, so they need exact arithmetic.

## Decision

- Every amount is an `int` number of wei (`autolister_core.money.Wei`), from the
  API response to the signed order.
- Percentages and ratios are `Decimal`. Applying one rounds explicitly to the
  nearest wei, with ties to even.
- Converting ETH to wei rejects floats outright. The strategy file stores
  percentages as strings, so YAML never turns them into floats.
- Conversion to ETH happens only for display (`format_eth`).

## Alternatives considered

- **Floats with a tolerance.** Every comparison then needs an epsilon, and the
  emergency stop is exactly the kind of comparison where that goes wrong.
- **Decimal ETH everywhere.** Exact, but the chain and the APIs speak wei, so
  every boundary would need a conversion.

## Consequences

- Comparisons such as "is this price below the emergency floor" are exact.
- Code reads in wei, which is less intuitive; helpers like `eth_to_wei("1.07")`
  and `format_eth` keep tests and logs readable.
