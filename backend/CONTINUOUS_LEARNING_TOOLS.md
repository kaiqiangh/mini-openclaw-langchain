# Continuous Learning Notes: Tools Redesign

These instinct-style notes capture durable preferences from the tools redesign.

## Instinct: Prefer Canonical Tool Names

- Trigger: when two or more tool names map to the same behavior.
- Confidence: 0.85
- Action: keep one canonical tool name per capability and remove aliases.
- Evidence: removed `exec`, `read`, and `web_fetch`; kept canonical names only.

## Instinct: Merge Overlapping File Read Tools

- Trigger: when `read_file` and `read_files` overlap heavily.
- Confidence: 0.88
- Action: keep only `read_files` and support both `path` and `paths` arguments.
- Evidence: consolidated single and multi-file read workflows into one tool contract.

## Instinct: Keep Local-First Dependencies Minimal

- Trigger: when adding capabilities like PDF extraction.
- Confidence: 0.80
- Action: use optional dependency install path instead of making base requirements heavier.
- Evidence: added `requirements-pdf.txt` and explicit runtime error guidance when `pypdf` is missing.

## Instinct: Add Operational Read-Only Tools Before Mutating Ones

- Trigger: when expanding agent/session/scheduler introspection.
- Confidence: 0.77
- Action: prioritize read-only tools that inspect current state from local files/managers.
- Evidence: added session, agent, and scheduler inspection tools without introducing new infrastructure.

## Instinct: Make Breaking Simplification Explicit

- Trigger: when long-term simplification conflicts with backward compatibility aliases.
- Confidence: 0.79
- Action: do one coordinated hard cut (code + config + tests + docs) instead of hidden shims.
- Evidence: updated runtime defaults, tool registration, tests, and READMEs in one pass.
