# Team Coding Standards

## Naming
- Functions and variables: `snake_case`. Classes: `PascalCase`. Constants: `UPPER_SNAKE_CASE`.
- Boolean variables/functions should read as a predicate: `is_valid`, `has_permission`, not `valid`, `permission`.
- Avoid single-letter variable names except for loop indices (`i`, `j`) or well-known math (`x`, `y`).

## Functions
- A function should do one thing. If you need "and" to describe it, split it.
- Max function length: ~40 lines. Longer functions should be decomposed.
- Max function parameters: 5. Beyond that, use a config object / dataclass.
- Avoid deeply nested conditionals (max 3 levels). Prefer early returns / guard clauses.

## Error Handling
- Never use a bare `except:` — always catch a specific exception type.
- Don't swallow exceptions silently. If you catch and don't re-raise, log with context.
- User-facing errors should not leak internal stack traces or raw exception messages.

## Security
- Never hardcode secrets, API keys, or credentials — use environment variables or a secrets manager.
- Never build SQL queries with string concatenation or f-strings — always use parameterized queries.
- Validate and sanitize all external input at the boundary (API layer), not deep in business logic.

## Documentation
- Every public function/class needs a docstring stating purpose, params, and return value.
- Docstrings should explain *why*, not restate the code (`# increment i` is not useful).
- Non-obvious business logic decisions should have an inline comment explaining the reasoning.

## Testing
- Every new function handling business logic needs at least one unit test.
- Tests should cover the happy path plus at least one edge case / failure case.
- Don't mock what you don't own only when necessary — prefer testing real logic where feasible.
