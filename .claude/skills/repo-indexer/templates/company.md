# Company context

Copy this into the target repository at `.agentteam/company.md`. Every agent reads it and none
of them may contradict it.

Fill it by interview, not by guessing. On a brownfield repo the indexer drafts it from existing
docs and code, and a human corrects it before first use. Treat anything still marked `TODO` as an
automatic open question in every requirements document.

> Do not put credentials, connection strings, API keys or customer data in this file. It is
> committed, it is read by agents, and it ends up in prompts.

---

## Product

**What it is:** <one paragraph a new hire would understand>

**Who uses it:** <the real users, not personas>

**How it makes money:** <or: internal tool, open source, pre-revenue>

**Stage:** <pre-launch / early / mature>

## Roles

Use these exact names everywhere. Agents may not invent new ones.

| Role | Description | Can do | Cannot do |
|---|---|---|---|
| | | | |

## Business rules

Rules that are true regardless of implementation. Agents treat these as constraints, not
suggestions.

| Rule | Why it exists |
|---|---|
| | |

## Glossary

Domain terms and the exact words used in the product and the code. If a term appears here,
agents use this spelling and no synonym.

| Term | Means |
|---|---|
| | |

## Engineering standards

| Topic | Standard |
|---|---|
| Languages | |
| Testing | <framework, minimum expectation for new code> |
| Branching | |
| Commit style | |
| Review | <who must approve, what blocks merge> |
| Definition of done | |

## Constraints

Things a design must respect. Compliance, data residency, uptime commitments, platforms that
must keep working, systems that must not be touched.

| Constraint | Applies to |
|---|---|
| | |

## Deliberate non-goals

Things the product has chosen not to do. Prevents agents from helpfully proposing them every
time.

- <non-goal> — <why>
