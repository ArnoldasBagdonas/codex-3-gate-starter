# Codex 3-Gate Starter

A deliberately small local orchestrator for **Codex CLI**.

It demonstrates:

1. AI drafts and critiques the specification.
2. Human is interrupted only for real product decisions (**Gate 1**).
3. AI creates and critiques technical design.
4. Human is interrupted only for architecture/risk decisions (**Gate 2**).
5. AI implements, verifies, reviews, and fixes automatically.
6. Human checks the actual outcome (**Gate 3**).

No Python packages are required.

## Prerequisites

- Python 3.10+
- Codex CLI installed
- `codex` available in PATH
- Codex CLI authenticated

Check:

```bash
codex --version
python --version
```

`codex exec` is the non-interactive Codex mode used by this starter.

## Run the example

From this folder:

```bash
python orchestrator.py
```

The orchestrator runs until it either:

- needs a genuine Gate 1 decision,
- needs a genuine Gate 2 decision,
- reaches Gate 3,
- or encounters an error.

### If Gate 1 stops

Read:

```text
features/F001-example/gates/gate1.md
```

Create:

```text
features/F001-example/gates/gate1_answers.md
```

Example:

```markdown
DEC-001: Option A.
DEC-002: No automatic retry.
```

Then simply run again:

```bash
python orchestrator.py
```

It resumes from saved state.

### Gate 2

Same idea:

```text
gates/gate2.md
gates/gate2_answers.md
```

Run the same command again.

### Gate 3

Inspect the actual result, then create:

```text
gates/gate3_answers.md
```

with:

```text
APPROVE
```

Run again and the feature becomes `DONE`.

## Reset the demo

```bash
python orchestrator.py --reset
```

## Important: configure your repositories

Edit:

```text
features/F001-example/feature.json
```

Example:

```json
{
  "repositories": [
    {
      "name": "desktop-app",
      "path": "../../../my-app",
      "verify": "npm test && npm run lint"
    },
    {
      "name": "api",
      "path": "../../../my-api",
      "verify": "pytest"
    }
  ]
}
```

Paths are relative to the directory containing `feature.json`.

Each repository should ideally contain its own `AGENTS.md`.

## Add your own feature

Copy:

```text
features/F001-example/
```

to for example:

```text
features/F014-device-update/
```

Then edit:

```text
feature.json
inputs/idea.md
```

and delete old `artifacts`, `logs`, and gate answer files.

Run:

```bash
python orchestrator.py features/F014-device-update/feature.json
```

## What persists

`feature.json`

Contains workflow state:

```text
NEW
GATE_1
SPEC_APPROVED
GATE_2
READY_TO_IMPLEMENT
VERIFYING
GATE_3
DONE
```

`artifacts/`

Contains durable project knowledge:

```text
spec.md
design.md
tasks.md
```

`logs/`

Contains structured outputs from individual Codex stages. These are primarily for debugging.

`gates/`

Contains only human decisions.

## Why this is intentionally not "fully autonomous"

The script automatically handles:

- drafting
- critique
- mechanical corrections
- design
- task planning
- implementation
- test execution
- code review
- blocker/major fix loops

It stops for:

- user-visible product decisions,
- architecture/risk decisions,
- final product outcome.

That is the useful boundary for a first version.

## Windows note

Current Codex CLI releases have had reported native-Windows issues where
`--sandbox workspace-write` may behave as read-only. If implementation cannot
write files on native Windows, run this starter under WSL, or retest with your
current Codex CLI release before changing sandbox permissions.

Do **not** blindly replace `workspace-write` with `danger-full-access`.

## Next improvements after this works

Do not add these until the simple version proves useful:

- git worktrees per implementation task
- parallel repo agents
- GitHub/Linear/Jira as the control plane
- notifications when a gate is reached
- PR creation
- CI polling
- a web UI
- database-backed workflow state

The point of this starter is to prove the operating model first.
