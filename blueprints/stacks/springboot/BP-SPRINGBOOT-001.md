---
id: BP-SPRINGBOOT-001
version: v1.0
scope: stack:springboot
approved_by: <fill in — pending first human approval>
---

# Spring Boot Stack Blueprint

This is the first Blueprint for the demo project (v3 §1). It intentionally
starts small — expand it only via reviewed, versioned changes (§3.7.5),
never by an agent editing it directly.

## Directory structure
```
src/main/java/<group>/<app>/
  controller/     # @RestController classes only — no business logic here
  service/        # business logic, interfaces + impl
  repository/     # Spring Data JPA interfaces only
  dto/            # request/response DTOs — never expose entities directly
  entity/         # JPA entities
  config/         # @Configuration classes
  exception/      # custom exceptions + @ControllerAdvice handlers
src/test/java/<group>/<app>/
  <mirrors main structure>
```

## Allowed architecture pattern
Layered architecture: Controller -> Service -> Repository. No layer may
skip another (a Controller must never call a Repository directly).

## Dependency Injection
Constructor injection only. No field injection (`@Autowired` on a field
is a Blueprint violation), because constructor injection makes required
dependencies explicit and testable without a Spring context.

## Naming
- Services: `<Domain>Service` interface + `<Domain>ServiceImpl` class.
- Repositories: `<Domain>Repository extends JpaRepository<...>`.
- DTOs: `<Domain>Request` / `<Domain>Response`.

## Exception handling
Follow `BP-ERROR-HANDLING-001` (org-wide). In Spring Boot specifically:
business-rule violations throw a typed exception extending
`ApplicationException`, caught by a single `@RestControllerAdvice` and
translated to a `ProblemDetail` response — never a raw stack trace to
the client.

## Validation
All request DTOs use `jakarta.validation` annotations (`@NotNull`,
`@Size`, etc.); controllers validate with `@Valid`. Do not hand-roll
validation logic that duplicates what a Bean Validation annotation
already covers.

## Testing
Unit tests: JUnit 5 + Mockito, one test class per service/controller.
Integration tests: `@SpringBootTest` with Testcontainers for the database
— no in-memory H2 substitution for integration tests, since it can hide
Postgres-specific behavior differences.

## Anti-patterns (forbidden)
- Field injection.
- Business logic in controllers.
- Returning JPA entities directly from a controller.
- Catching `Exception` broadly and swallowing it.
