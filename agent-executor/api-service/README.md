# API Service

Spring Boot service that accepts coding tasks and durably queues them in PostgreSQL. It does **not** execute tasks; workers pick up `QUEUED` rows later.

## Run

Requires Java 21+ and a local PostgreSQL with the `distributed_agent_project` database. Maven is downloaded by the wrapper.

| Variable | Default | Purpose |
|---|---|---|
| `DB_URL` | `jdbc:postgresql://localhost:5432/distributed_agent_project` | JDBC URL |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | falls back to `PGPASSWORD` | Database password |
| `GITHUB_TOKEN` | *(none)* | Used to check repositories exist and are accessible. Without it only public repos pass and GitHub allows 60 checks/hour. Use a fine-grained token with read-only *Metadata* and *Contents*. |

```bash
./mvnw spring-boot:run
```

On first start against an existing database, Flyway records the current `tasks` schema as version 1 (`flyway_schema_history`) without modifying it.

## `POST /tasks`

```bash
curl -i -X POST localhost:8080/tasks -H 'Content-Type: application/json' \
  -d '{"repository_url": "https://github.com/example/project", "prompt": "Add a health endpoint and write tests"}'
```

```
HTTP/1.1 202 Accepted
Location: http://localhost:8080/tasks/8f7c2b9e-...

{"task_id": "8f7c2b9e-...", "status": "QUEUED"}
```

`repository_url` must be `https://github.com/{owner}/{repo}` (a trailing `/` or `.git` is fine). The service looks the repository up on GitHub before queuing and stores GitHub's canonical URL. Errors are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem documents with a `code`:

| Status | `code` | Meaning |
|---|---|---|
| 400 | `VALIDATION_FAILED` | Missing/blank field or prompt over 10,000 chars; see `errors` |
| 400 | `INVALID_REPOSITORY_URL` | Not a `https://github.com/{owner}/{repo}` URL |
| 400 | `BAD_REQUEST` | Malformed JSON |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | Body is not `application/json` |
| 422 | `REPOSITORY_NOT_FOUND_OR_INACCESSIBLE` | Doesn't exist, or is private and the token can't see it (GitHub doesn't distinguish) |
| 422 | `REPOSITORY_ACCESS_DENIED` | Forbidden, e.g. org SSO not authorized for the token |
| 422 | `REPOSITORY_ARCHIVED` | Archived (read-only) |
| 422 | `REPOSITORY_DISABLED` | Disabled by GitHub |
| 422 | `REPOSITORY_UNAVAILABLE_LEGAL` | Blocked for legal reasons (451) |
| 502 | `GITHUB_AUTH_MISCONFIGURED` | The server's `GITHUB_TOKEN` was rejected |
| 503 | `GITHUB_RATE_LIMITED` | GitHub rate limit hit; honour `Retry-After` |
| 503 | `GITHUB_UNAVAILABLE` | GitHub timed out or returned 5xx |

Rejected requests never write to the database.

## Test

```bash
createdb -U postgres agent_executor_test   # once
./mvnw test
```

Integration tests run against `agent_executor_test` (override with `TEST_DB_URL`); Flyway builds its schema and each test clears `tasks`. GitHub is mocked in tests.

## End-to-end tests

```bash
./mvnw verify -Pe2e                                              # unit + integration + E2E
E2E_PRIVATE_REPO=https://github.com/<you>/<private-repo> ./mvnw verify -Pe2e   # also cover a private repo
E2E_KEEP_DATA=true ./mvnw verify -Pe2e                           # keep E2E rows to inspect with psql
```

E2E tests (`src/test/java/.../e2e/*E2E.java`) start the real app on a random port and call it over HTTP, against the **real** database (`DB_URL`, default `distributed_agent_project`) and the **real** GitHub API (`GITHUB_TOKEN`). Nothing is mocked. They are not part of `./mvnw test`.

**Cleanup** (after every test, pass or fail, so existing data is untouched):
1. Every task created through the E2E client (`POST /tasks` → 202) is deleted by id. Other registered cleanups run too, newest first; if one fails the rest still run and the test reports it.
2. Safety net: any row whose prompt starts with this run's `[e2e <runId>]` tag is deleted.
3. Once per run, `[e2e …]` rows older than an hour (from a run that was killed mid-test) are swept.

`E2ECleanupE2E` tests the cleanup itself. Find leftovers with `SELECT * FROM tasks WHERE prompt LIKE '[e2e %';`.

**Adding a route:** create `<Route>E2E extends E2ETestBase`. The base provides `api` (HTTP client), `prompt(label)` (tagged test data), `createTask(...)`, `taskRow(id)` / `countTasksWithPrompt(...)` (DB checks), `assertProblem(response, status, code)` (error contract), `requireEnv(...)` (skip when config is missing) and `registerCleanup(description, action)` — call it for anything the new route creates that isn't a task (tasks are tracked automatically).
