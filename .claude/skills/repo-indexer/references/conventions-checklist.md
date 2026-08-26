# Conventions checklist

Work through each item for the "Extract conventions" step of the repo-indexer skill. For every
item: sample three to five files from different parts of the codebase, record the dominant
pattern, and cite the example path(s) that demonstrate it. If there is no dominant pattern, say
so explicitly rather than picking one — "mixed, see `<path>` and `<path>`" is a correct entry.

## Error handling

- How do functions/handlers signal failure — exceptions, error return values, result types?
- Is there a central error type or error-handling middleware?
- Are errors logged, and where?

## Naming

- File naming: kebab-case, snake_case, PascalCase?
- Function/variable naming conventions per language in use.
- Any prefix/suffix conventions (`_test`, `.spec.`, `I` for interfaces, etc.)?

## Test structure

- Where do tests live — colocated with source, or a separate `tests/`/`spec/` tree?
- What test framework(s) are in use?
- Unit vs. integration vs. end-to-end — how are they separated and named?

## Directory layout

- Is the layout feature-based, layer-based (controllers/models/views), or something else?
- Where do shared utilities live?
- Where does configuration live?

## API response shape

- For HTTP APIs: is there a consistent envelope (`{ data, error }`, JSON:API, plain resource)?
- How are errors represented in responses (status codes, error body shape)?
- Is pagination handled consistently, and how?

## Additional conventions worth checking

- Dependency injection / service construction pattern
- Logging conventions (structured vs. plain, log levels used)
- Comment and documentation style
- Commit message conventions (if discoverable from `git log`)
- Import ordering / module boundaries enforced by linting
