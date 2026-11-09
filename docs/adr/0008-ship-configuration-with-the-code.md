# 8. Ship configuration with the code

**Status:** Accepted

## Context

Two files decide what the system does with money: `strategy.yaml` (how it
prices) and `accounts.yaml` (which wallets and tokens it trades). A wrong value
in either does as much damage as a bug.

## Decision

- Both files live in the repository. They change through pull requests, CI
  loads and validates them, and both services validate them again at start-up.
- Both are **baked into the images**, so a running version always uses the
  configuration it was reviewed and tested with.
- Terraform reads `accounts.yaml` too, so adding an account creates its wallet
  secret, readable only by the signer.
- Operational switches (the kill switches and the gas fee cap) are Terraform
  variables instead, because they must change quickly and are not part of a
  release.
- Secrets are in neither: their values live only in Secret Manager.

## Alternatives considered

- **Environment variables set by Terraform.** Fast to change, but not reviewed
  alongside the code that interprets them, and not tied to a version.
- **A configuration service read at runtime.** Changes without a deploy, which
  is the problem: the running configuration would no longer match any reviewed
  commit.

## Consequences

- Changing the strategy is a deploy, which takes minutes. Strategy changes ship
  in shadow mode first ([runbook](../runbook.md#change-the-strategy)).
- A rollback restores code and configuration together.
- Git history is the audit trail of every parameter change.
