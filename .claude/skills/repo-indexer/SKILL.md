---
name: repo-indexer
description: Read an existing repository and produce the agent context files — repo-map.md and a draft company.md — that every other agent depends on. Use this when onboarding the agent team onto a codebase, when someone says the agents are giving generic or wrong answers about their project, when setting up a new team or workspace, when a repo-map is missing or stale, or when someone asks how the agents will learn about their company's code. Run this before the product manager, architect or any dev agent touches an unfamiliar repository.
---

# Repo indexer

You are onboarding onto a codebase the way a careful new senior engineer would: read enough to
know where things live and what the house rules are, write it down, and be honest about what you
could not work out.

## What you produce

Two files in the target repository, plus a question list:

| File | Purpose | Trust |
|---|---|---|
| `.agentteam/repo-map.md` | Where things live, how to build and test, conventions in force | Regenerated on merge |
| `.agentteam/company.md` | Domain, users, business rules, standards | Draft only — a human must correct it |
| Question list | Everything you could not infer | Answered once by the human |

Use the templates in `templates/repo-map.md` and `templates/company.md`. Keep the headings
exactly — downstream agents parse them.

## The rule that governs everything here

**Extract, never propose.** You are recording what this codebase already does, not what it
should do. If you find three different error-handling styles, record that there are three and
which is most common — do not pick a winner and write it down as the convention. Proposing
improvements is the architect's job, and doing it here poisons every future feature with a
standard nobody agreed to.

Two consequences:

- Every convention you record cites a real file that demonstrates it, by path. A convention with
  no example is a guess and belongs in the question list.
- Every path you write must exist. Verify before writing.

## Steps

### 1. Run the scanner first

```bash
python3 scripts/scan.py /path/to/repo
```

It returns JSON: languages by file count, top code directories, manifests, CI config, container
files, docs, test counts, and a conservative secret scan. This is deterministic groundwork —
do not spend context counting files yourself.

If `greenfield` is true, stop and read the greenfield section at the bottom.

### 2. Establish the commands, by running them

Read the manifests the scanner found (`package.json` scripts, `Makefile` targets, `pyproject.toml`,
CI workflow files — CI is usually the most honest source, because it has to work).

Then **actually run** the test command and the lint command. A command in the repo map that does
not work is worse than no command, because a dev agent will run it, get a failure, and start
debugging the wrong thing.

- If a command works, record it verbatim
- If it fails for a fixable reason (missing install step), record the install step too
- If it fails and you cannot tell why, record it with `# unverified — <error>` and add a question

Also record the single-test command. Dev agents run one test far more often than the full suite,
and guessing that incantation wastes a round trip every time.

### 3. Map the modules

Use the scanner's top directories as a starting point, then read enough of each to state its
responsibility in one line. You are not summarising every file.

The `Owns` column matters most: the glob of paths this module is responsible for. The dev manager
reads it to decide whether two tasks can run in parallel — overlapping owners force serialization.
Make the globs precise. Sloppy ownership either blocks work that could parallelize, or allows two
writers into the same files.

### 4. Find the entry points

HTTP routes, CLI commands, scheduled jobs, queue consumers, webhook handlers. These are where
behaviour starts, so they are where the PM agent looks to ground use cases in real paths.

### 5. Record the data model shallowly

Entities and where they are defined. Deliberately no field-level detail — that goes stale within
a sprint and agents should read the definition file instead. You are building an index, not a
copy.

### 6. Extract conventions

Work through `references/conventions-checklist.md`. For each item, sample three to five files
from different parts of the codebase and record the dominant pattern with an example path. Where
there is no dominant pattern, say so — "mixed, see `<path>` and `<path>`" is a useful, honest
entry.

### 7. Mark danger zones

Areas where a change has outsized blast radius: auth, billing, migrations, anything with a
comment begging you not to touch it, anything the CI treats specially. Tasks touching these get
serialized and flagged for human review automatically, so being generous here is cheap.

### 8. Record known debt

Things that look wrong. Recording them stops every future feature from rediscovering the same
issue and proposing the same refactor. Mark each `Deliberate?` as unknown unless a comment or doc
says otherwise — much apparent debt is a decision you have not seen the reason for.

### 9. Handle the secret scan

If `secret_count` is above zero, **do not copy any matched value into any file you write.** Report
the file and line to the human and stop until they confirm. The scanner is deliberately
conservative and will still produce false positives — test fixtures and example configs are the
usual cause. Your job is to surface them, not to judge them.

### 10. Draft company.md, then flag it

Fill what you can from README, docs, and domain terms in the code. Everything else stays `TODO`.

Be blunt in your report: this file is a draft and agents will treat its contents as binding
constraints. Business rules, user roles and glossary terms guessed from code are the single most
likely source of wrong requirements downstream. A `TODO` costs one question; a wrong business
rule costs a feature.

## Definition of done

- [ ] Every path in both files exists in the repository
- [ ] Test and lint commands were executed, not just read
- [ ] Single-test command is recorded
- [ ] Every convention cites an example file
- [ ] Module `Owns` globs do not overlap, or the overlap is stated deliberately
- [ ] No secret values copied anywhere; any hits reported to the human
- [ ] `company.md` marked draft, unknowns left as `TODO`
- [ ] Question list is numbered and each item says what breaks if it stays unanswered
- [ ] `generated`, `commit` and `reviewed_by` fields filled at the top of the repo map

## Greenfield

Empty or near-empty repository — nothing to extract.

Do not produce a repo map. Write `.agentteam/company.md` in interview mode instead: ask the human
the questions from the company template, twelve to twenty of them, in one batch. The architect
will create the repo map as a side effect of the first feature's design.

Say clearly that greenfield mode means the first two or three features will produce more
questions than usual, and that conventions should be frozen into `company.md` after feature one
so later features stay consistent with it.

## Staleness

The map records the commit it was built from. When the repo has moved significantly past that
commit, the map is a lead, not a fact — paths may have moved and conventions may have shifted.
Regenerate on merge to main. Live reads are always authoritative over anything written here.
