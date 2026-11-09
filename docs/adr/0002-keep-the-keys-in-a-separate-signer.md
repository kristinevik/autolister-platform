# 2. Keep the keys in a separate signer

**Status:** Accepted

## Context

The system needs the investors' private keys to list and cancel. Whoever holds a
key controls everything in that wallet.

The pricing logic reads untrusted input all day: listings anyone can create,
floor prices from third parties, and responses parsed by a large dependency
tree. That makes it the part of the system most likely to be compromised.
Putting the keys in the same process would put them one parsing bug away from
an attacker.

## Decision

Split the system in two:

- The **engine** does all the pricing and holds no keys. Its image does not even
  contain a signing library, and a test fails the build if one appears.
- The **signer** holds the keys and contains no pricing logic. It accepts a
  narrow set of instructions (list an account at a price, or cancel an
  account's orders), checks each one independently, and can do nothing else.

They run on separate VMs with separate service accounts. Only the signer's
service account can read wallet keys.

## Alternatives considered

- **One service.** Simpler, but a compromise of anything means a compromise of
  every wallet.
- **Keys generated inside Cloud HSM**, which supports Ethereum's secp256k1
  curve, so that no process ever sees a raw key. A compromised signer could
  then sign only while it stayed compromised, and could not take the keys with
  it. The investors' wallets predate the system, though, and moving to new keys
  means new wallets and moving every position. This is the natural next step
  for key protection.

## Consequences

- A compromised engine can still ask for listings and cancellations, so the
  signer must check prices itself ([ADR 0004](0004-one-emergency-stop-enforced-twice.md)).
- The two services need a channel and a protocol between them
  ([ADR 0003](0003-send-sealed-instructions-over-pubsub.md)).
- There are two images to build and deploy instead of one.
