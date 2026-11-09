# 6. Run containers on VMs, not Kubernetes

**Status:** Accepted

## Context

We run two long-lived workers. Neither serves traffic, and they must be strongly
isolated from each other, since one holds keys and the other parses untrusted
data. Exactly one signer may run at a time. Operations should take as little of
our time as possible.

## Decision

Run each service as a single container on its own **Container-Optimized OS VM**,
in a **managed instance group of one**:

- The group recreates a VM that dies, and replaces it when the image changes,
  deleting the old VM before starting the new one, so two signers never
  overlap.
- systemd runs the container through cloud-init, as Google documents for COS:
  unprivileged, read-only root filesystem, all capabilities dropped.
- The VMs have shielded boot, no public address and no inbound access.

## Alternatives considered

- **GKE.** Strong tooling, but a cluster to secure and upgrade for two
  processes, and isolating the key holder from untrusted workloads would mean
  separate node pools anyway.
- **Cloud Run.** Built around serving requests. A pull worker that must never
  run twice fits it poorly.
- **Plain VMs without containers.** The same isolation, but we would lose the
  immutable, hash-pinned image that is identical in CI and production.

## Consequences

- Each service has a VM boundary, with its own kernel, around it.
- A deploy means a minute or two of downtime per service. Instructions wait in
  Pub/Sub meanwhile, so nothing is lost.
- Applying Terraform picks up the latest COS image, which replaces the VMs: that
  is how they get patched.
- There is no horizontal scaling. None is needed.
