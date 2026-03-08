# Agent Templates

This directory ships reusable runtime presets for agent creation, diffing, and bulk patch workflows.

## File format

Each template is a JSON file named `<template-name>.json` with this shape:

```json
{
  "description": "Human-readable summary",
  "runtime_config": {
    "...": "Partial runtime patch"
  }
}
```

Rules:

- `description` is optional but recommended.
- `runtime_config` must be a JSON object.
- `runtime_config` is a partial patch over the canonical runtime schema from [`backend/config.json`](../config.json).
- Templates must not contain secrets or provider catalog data such as `llm_profiles`, `llm_defaults`, or `agent_llm_overrides`.

## How templates are loaded

The API loader in [`backend/api/agents.py`](../api/agents.py) resolves template files from `backend/agent_templates/` and validates them through the same code path used for runtime config writes:

1. Read JSON from disk.
2. Extract `runtime_config` or treat the whole payload as the config object.
3. Parse with `runtime_from_payload(...)`.
4. Normalize with `runtime_to_payload(...)`.

That means templates inherit the current schema behavior automatically:

- unknown nested runtime keys are rejected
- removed fields such as `llm_runtime.profile` are rejected
- defaults from `RuntimeConfig` are applied where fields are omitted
- list normalization, enum coercion, and numeric clamping stay consistent with live config writes

## Authoring guidance

Prefer small patches over full expanded runtime payloads.

Good:

- change only the fields that define the preset's intent
- keep tool lists explicit when a profile is safety-sensitive
- let omitted fields inherit the repo defaults from `backend/config.json`

Avoid:

- copying the entire normalized runtime payload into every template
- embedding environment-specific URLs, keys, or hostnames
- relying on legacy keys that the runtime parser no longer accepts

## Shipped templates

- `balanced`: general-purpose interactive preset close to the repo defaults
- `safe-local`: conservative local preset with read-heavy chat tools and strict sandboxing
- `research`: retrieval and web research preset for chat workflows
- `terminal-safe`: sandboxed code-editing preset without outbound network access
- `scheduler-worker`: automation preset for heartbeat and cron-oriented agents

## Extending the catalog

When adding a template:

1. Pick a lowercase file name that matches the API template-name validation rules.
2. Add a short description that explains the operating mode, not the implementation details.
3. Keep `runtime_config` to the minimum patch needed.
4. Run backend tests so the shipped-template validation stays green.
5. Update this README if the catalog or authoring rules change.
