# 5. Reconcile against the order book

**Status:** Accepted

## Context

An instruction can be lost, delayed, delivered twice, or fail partway. Orders
expire, sell, or get rejected by the exchange. A system that tracks "what we
think we have listed" drifts away from what is actually listed, and every
failure needs its own recovery path.

## Decision

The engine is a **control loop**. Every cycle it reads the order book, finds
each account's live listing there, decides what should change, and asks for
that. It keeps state only for what the book cannot show it: the previous floor,
and listings priced deeper than the 200 asks it reads.

The signer is kept simple in return:

- Work that fails before an order reaches the exchange is retried through
  Pub/Sub.
- **Order submission is at most once.** A rejected order, or one whose fate is
  unknown, is logged and never retried, because a retry could list the token
  twice. The engine's next cycles see whatever is missing.

## Alternatives considered

- **Event-driven bookkeeping**: record every order the system places and update
  it from confirmations. Every lost message or crash then needs a
  reconciliation job, which is this design with extra steps.
- **Retrying submissions in the signer.** Order submission is not idempotent,
  so retries trade a missing listing for a duplicate one, and add a second
  source of truth about what is listed.

## Consequences

- Recovering from almost any failure needs no special handling: the next cycle
  starts from the facts.
- The engine reads 200 asks a minute, well within the API's limits.
- A partially listed account (some tokens accepted, some not) is completed at
  its next relist or renewal, not immediately. That is acceptable: the listed
  tokens are already earning.
