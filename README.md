# agentic-team-kit

Claude Code skills for running a small "agent development team" over a codebase: an indexer that
onboards agents onto an existing repo, and a product-manager skill that turns feature requests
into requirements documents the rest of the team can build from.

## Skills

| Skill | Purpose |
|---|---|
| [`repo-indexer`](.claude/skills/repo-indexer/SKILL.md) | Reads an existing repository and produces `.agentteam/repo-map.md` and a draft `.agentteam/company.md` — the context files every other agent depends on. |
| [`pm-requirements`](.claude/skills/pm-requirements/SKILL.md) | Turns a short feature request into `docs/features/<slug>/requirements.md`: use cases, edge cases, testable acceptance criteria, and one batched list of open questions. |

## How they fit together

1. Run `repo-indexer` once, on the target repository, to produce `.agentteam/repo-map.md` and
   `.agentteam/company.md`. On a brownfield repo these are extracted from the code, not proposed;
   a human then reviews and corrects the draft `company.md`. On a greenfield (empty) repo, the
   indexer instead interviews the human to fill `company.md` and defers the repo map to the first
   feature.
2. Run `pm-requirements` against a feature request. It reads `company.md` and `repo-map.md`
   (when present), grounds every use case in real paths, and writes a requirements document with
   testable acceptance criteria and a single batched list of open questions for the human to
   answer.
3. Downstream design and implementation work (architect, dev manager, QA manager) consumes the
   requirements document — not covered by this kit yet.

## Layout

```
.claude/skills/
  repo-indexer/
    SKILL.md
    scripts/scan.py              # deterministic repo scan: languages, manifests, CI, tests, secrets
    references/conventions-checklist.md
    templates/repo-map.md        # copied to <target-repo>/.agentteam/repo-map.md
    templates/company.md         # copied to <target-repo>/.agentteam/company.md
  pm-requirements/
    SKILL.md
    references/artifact-schema.md  # the requirements.md contract
```

## Repository context files

Both skills read and write `.agentteam/repo-map.md` and `.agentteam/company.md` in the *target*
repository (not in this kit). `repo-map.md` records where things live and how to build/test it;
`company.md` records domain, users, business rules and standards. Neither file should ever
contain credentials, connection strings, or customer data — they are committed and get read
straight into agent prompts.
