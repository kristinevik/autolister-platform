# 4. One emergency stop, enforced twice

**Status:** Accepted

## Context

The worst realistic failure is listing positions far below their value: a
pricing bug, a wrong floor from a data provider, or a compromised engine. Every
safeguard inside the engine fails together with the engine.

## Decision

There is one simple rule: **never list below the 21st cheapest ask** on
LooksRare (ignoring asks under 0.1 ETH as troll listings). Twenty cheaper NFTs
always stand in front of ours, and a buyer sweeping the floor must buy all of
them first.

- The rule lives once, in `autolister_core.guard`, and both services call it.
- The **engine** applies it before publishing a listing.
- The **signer** applies it again, to its *own* read of the order book, before
  signing. It never trusts the engine's answer.
- The rule counts every ask, ours included, so it can be computed from public
  data alone.
- The signer's parameters are configured separately from the strategy, so no
  strategy change can loosen them, and a test fails if the two disagree.

## Alternatives considered

- **Check only in the engine.** Useless against the failure it exists for.
- **A price band set by hand** (for example, never below a fixed ETH price).
  Simple, but stale within days in a moving market, and one more setting to get
  wrong.
- **Relative to the floor from the data providers.** That is exactly the input
  an attacker or a provider bug would distort; the order book costs real money
  to move.

## Consequences

- The engine and the signer read the book a few seconds apart, so in a fast
  market the signer occasionally refuses a listing the engine thought safe. That
  alerts, and the engine decides again on its next cycle.
- In a thin book (fewer than 21 asks) the floor is the most expensive ask, so
  listing effectively stops. That is the safe direction to fail.
- The rule bounds, rather than prevents, the damage a compromised engine can do:
  it can still force listings at the emergency floor itself.
