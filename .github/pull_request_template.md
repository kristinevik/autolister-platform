## What and why

<!-- What changes, and the problem it solves. Link the issue or alert if there is one. -->

## How it was tested

<!-- Tests added or changed. For strategy changes: what shadow mode showed. -->

## Checklist

- [ ] `make check` passes.
- [ ] Changes to `services/signer/` or `libs/core/` have a second reviewer: they can weaken a safety check.
- [ ] Changes to `config/strategy.yaml` ship in shadow mode first ([runbook](../docs/runbook.md#change-the-strategy)).
- [ ] Dependency changes went through `make lock`, and the lock diff has been read.
- [ ] Docs and the runbook still describe what the code does.
- [ ] A significant decision has an [ADR](../docs/adr/README.md).
