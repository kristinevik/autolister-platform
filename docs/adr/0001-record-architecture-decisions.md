# 1. Record architecture decisions

**Status:** Accepted

## Context

The system moves investors' capital. The reasons behind its shape, such as why
the keys live where they do or why a check happens twice, matter as much as the
code, and they are the first thing lost when the person who knew them is not in
the room.

## Decision

We record each significant decision as a short document in `docs/adr/`, in the
format Michael Nygard describes: context, decision, consequences. A decision is
significant if it is hard to reverse, if it affects safety, or if a newcomer
would reasonably ask "why is it done this way?".

## Consequences

- Reviewers can ask for a record when a pull request makes a decision of this
  kind.
- Records are immutable once accepted. Changing course means a new record that
  supersedes the old one, so the history stays readable.
