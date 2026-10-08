# Phase 0 and Phase 2 verification status

## Phase 0 — reproducible baseline

Local prerequisites, a fresh Python 3.12 environment, pinned model/photos,
root setup instructions, configurable Compose ports and worker preflight are
available. The earlier copied virtual environment is not the supported runtime.

The supplied directory still lacks canonical Git history. A clean-clone setup
and versioned team release remain unverified; Phase 0 is not fully closed.

## Phase 2 — browser and physical worker

The local browser-to-Docker rehearsal completed ten genuine photographs in two
tasks, with downloaded results verified for exact input accounting. Job ID:
`2a34f804-a3ea-4ead-80bf-6888157f0408`.

Evidence:

- `output/phase2/browser-result.json`: actual browser-downloaded job output.
- `output/phase2/browser-verification.json`: ten images, two tasks, zero errors.
- `output/phase2/db-evidence.json`: task owners and accepted metrics.
- `output/phase2/browser-completed.jpg`: captured dashboard completion.

Both tasks were owned by **Local Docker rehearsal** on this development machine.
This is not proof of computation on a separate physical retired laptop.
Health/startup success was reported from a second Windows laptop, but no new
physical node was observed in the API during that session. The separate-machine
acceptance gate therefore remains pending.

The earlier Phase 2 handoff ZIP is a historical source bundle, not an installer
or the new approval-enabled worker release. Use current source and the upgraded
backend for onboarding development.

## Current work

The user prioritized easier owner-approved onboarding before further physical
fleet work. See [WORKER_ONBOARDING.md](WORKER_ONBOARDING.md) for implemented
pairing/reconnect/revocation and remaining desktop/install milestones.
Energy figures remain estimates; measured savings and hardware waste prevention
are separate evidence requirements.
