# Architecture decision records

Each record captures one significant decision: the situation, what we chose,
what we rejected, and what it costs us. They are written so that someone joining
later can understand why the system is the way it is, and can tell when a
decision should be revisited.

| # | Decision | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-keep-the-keys-in-a-separate-signer.md) | Keep the keys in a separate signer | Accepted |
| [0003](0003-send-sealed-instructions-over-pubsub.md) | Send sealed instructions over Pub/Sub | Accepted |
| [0004](0004-one-emergency-stop-enforced-twice.md) | One emergency stop, enforced twice | Accepted |
| [0005](0005-reconcile-against-the-order-book.md) | Reconcile against the order book | Accepted |
| [0006](0006-run-containers-on-vms.md) | Run containers on VMs, not Kubernetes | Accepted |
| [0007](0007-represent-money-as-integer-wei.md) | Represent money as integer wei | Accepted |
| [0008](0008-ship-configuration-with-the-code.md) | Ship configuration with the code | Accepted |

To record a new decision, copy the shape of an existing record and give it the
next number. Records are not edited once accepted: a decision that changes gets
a new record that supersedes the old one.
