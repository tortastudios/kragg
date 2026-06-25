# Known limitations

kragg raises the floor; it does not claim to make any bug class impossible to
ship green. These are the honest boundaries of the static gates — read them
before trusting a green run to mean more than it does.

## Unmodeled nullability is invisible to static gates

The gates that target the "external/nullable data consumed as a concrete type"
class — `typing-strictness` (strict mypy as a verified contract) and
`nullable-default` (arithmetic on `.get(key, default)` results) — close the
common, *modeled* cases deterministically. They do **not** close the class:

- **A genuinely-nullable field typed as non-null still ships green.** If an API
  field can be `null` but you model it as `int` (not `int | None`), mypy is
  satisfied and `nullable-default` sees nothing wrong. The production incident
  that motivated these gates would itself have passed strict mypy, because the
  payload was typed away as `dict[str, Any]` — and `Any` defeats the checker.
  Only a runtime schema that validates the payload (e.g. Pydantic) **plus** a
  test that feeds `None`/missing actually catches it, and kragg can enforce
  neither — it can only require the typing floor that makes the modeling honest.

- **`nullable-default` matches an idiom, not data flow.** kragg has no taint
  analysis, so it cannot tell an API dict from a local one. To stay precise
  (measured at ~5 hits across a real 206-file repo) it is scoped to arithmetic
  where both operands are dict accessors, excluding the `d.get(k, 0) + 1`
  accumulator and ALL-CAPS constant maps. Consequences:
  - it **misses** a dangerous read assigned to a variable first
    (`x = data.get("n", 0); total = x + y`) — only the inline idiom is caught;
  - it **misses** comparison, subscripting, and attribute access on the result
    (arithmetic only, by design, to keep false positives low);
  - it may still **flag a safe internal dict** that happens to match the shape.
    Suppress a reviewed-safe site with a trailing `# kragg: ignore`.

The discipline the gates cannot enforce lives in the generated `AGENTS.md`:
model external/nullable data as `T | None` at the boundary, never consume raw
external dicts, and add a None/missing-case test for each nullable field.
