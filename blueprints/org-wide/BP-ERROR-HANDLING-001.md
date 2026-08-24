---
id: BP-ERROR-HANDLING-001
version: v1.0
scope: org
approved_by: <fill in — pending first human approval>
---

# Rule: Standard Exception Handling for Application Services

Application services must not throw raw exceptions for expected business
errors. Return a `Result<T>`-style outcome instead.

**Incorrect:**
```
throw new BusinessException("Invalid token");
```

**Correct:**
```
return Result.failure("Invalid token");
```

**Reason:** keeps error handling consistent across API responses and
prevents unhandled exceptions from leaking implementation details to
clients. This mirrors the paper's own worked example (§4.2.3) — a Coder
Agent must be checked against a rule like this one before code generation
begins, or you have nothing to catch this class of hallucination against.

**Applies to:** all stacks, unless a stack-specific Blueprint documents an
explicit, approved exception (record it there with its own rationale,
don't silently ignore this one).
