# 3. Send sealed instructions over Pub/Sub

**Status:** Accepted

## Context

The engine needs to tell the signer what to do ([ADR 0002](0002-keep-the-keys-in-a-separate-signer.md)).
The channel between them must be:

- **one-way**, so the signer accepts no inbound connections;
- **durable**, so instructions survive a signer restart;
- **ordered per account**, so "cancel, then list" never runs as "list, then
  cancel";
- **authenticated**, so the signer acts only on what the engine sent.

The first version passed instructions through an email mailbox. It was one-way
and simple, but gave no ordering, no delivery guarantees we could reason about,
and one more password to protect.

## Decision

- Publish instructions to a **Pub/Sub topic** that only the engine may publish
  to, and consume them from a subscription that only the signer may read. Each
  account's instructions share an **ordering key**.
- **Seal** every instruction with an HMAC-SHA256 over a canonical JSON
  encoding, and include its issue time and a unique id.
- The signer **refuses** any instruction with a bad seal, any older than an
  hour, and any it has already handled or that an instruction it has already
  carried out supersedes.

## Alternatives considered

- **An HTTP API on the signer.** Synchronous and familiar, but it gives the one
  service holding keys an inbound attack surface.
- **A shared bucket or database that the signer polls.** One-way, but ordering,
  retries and dead-lettering would all be ours to build.
- **IAM alone, without a seal.** Pub/Sub permissions already restrict who can
  publish. The seal means one misconfigured binding cannot let anyone instruct
  the signer, and expiry and replay protection need a timestamp and an id in
  the message anyway.

## Consequences

- Delivery is at least once, so the signer has to be idempotent. It keeps replay
  marks, and cancellation checks the chain before sending anything.
- Failed instructions are retried with backoff and then dead-lettered, which
  alerts. We did not have to build any of that.
- The HMAC key is symmetric: anything that can seal can also verify, and the
  engine, the signer and on-call (for the break-glass command) can all read it.
  That is acceptable because all three are already trusted to issue
  instructions.
