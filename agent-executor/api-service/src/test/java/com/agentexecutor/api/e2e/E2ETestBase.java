package com.agentexecutor.api.e2e;

import com.agentexecutor.api.e2e.ApiClient.ApiResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;

import java.net.http.HttpRequest;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/**
 * Base for end-to-end tests: the real application on a random port, talking to the real database
 * ({@code DB_URL}, default {@code distributed_agent_project}) and the real GitHub API ({@code GITHUB_TOKEN}).
 * Nothing is mocked.
 *
 * <p>To cover a new route, add a {@code <Something>E2E} class extending this one; run with
 * {@code ./mvnw verify -Pe2e}. Build prompts with {@link #prompt(String)} so rows are traceable to a run.
 *
 * <p>Cleanup, after every test (pass or fail), unless {@code E2E_KEEP_DATA=true}:
 * <ol>
 *   <li>Registered cleanups run, newest first. Every task created through {@link #api} ({@code POST /tasks} → 202)
 *       is registered automatically; tests for new routes call {@link #registerCleanup} for what they create.</li>
 *   <li>Safety net: any row whose prompt carries this run's {@code [e2e <runId>]} tag is deleted.</li>
 * </ol>
 * Once per run, tagged rows older than an hour (left by a run that was killed mid-test) are swept as well.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
public abstract class E2ETestBase {

    private static final Logger log = LoggerFactory.getLogger(E2ETestBase.class);

    protected static final String RUN_ID = UUID.randomUUID().toString().substring(0, 8);
    // Hex run id: no LIKE wildcards (% or _) in the prefix, so it can be used as a LIKE pattern directly.
    private static final String PROMPT_PREFIX = "[e2e " + RUN_ID + "] ";

    protected static final String PUBLIC_REPO = "https://github.com/spring-projects/spring-boot";
    protected static final String ARCHIVED_REPO = "https://github.com/atom/atom";
    protected static final String MISSING_REPO = "https://github.com/octocat/does-not-exist-e2e-" + RUN_ID;

    private static final AtomicBoolean staleRowsSwept = new AtomicBoolean();

    @LocalServerPort
    private int port;

    @Autowired
    protected JdbcTemplate jdbc;

    protected ApiClient api;

    private final Deque<Cleanup> cleanups = new ArrayDeque<>();

    @BeforeEach
    void setUpClient() {
        sweepStaleRowsOnce();
        api = new ApiClient("http://localhost:" + port, this::trackCreatedResources);
    }

    @AfterEach
    void cleanUp() {
        if (keepData()) {
            if (!cleanups.isEmpty()) {
                log.info("E2E_KEEP_DATA=true, keeping: {}", cleanups.stream().map(Cleanup::description).toList());
            }
            cleanups.clear();
            return;
        }

        // Run every cleanup even if one fails, then report all failures together.
        List<RuntimeException> failures = new ArrayList<>();
        while (!cleanups.isEmpty()) {
            Cleanup cleanup = cleanups.pop();
            try {
                cleanup.action().run();
            } catch (RuntimeException e) {
                failures.add(new IllegalStateException("Cleanup failed: " + cleanup.description(), e));
            }
        }
        jdbc.update("DELETE FROM tasks WHERE prompt LIKE ?", PROMPT_PREFIX + "%");

        if (!failures.isEmpty()) {
            IllegalStateException error = new IllegalStateException(failures.size() + " E2E cleanup(s) failed");
            failures.forEach(error::addSuppressed);
            throw error;
        }
    }

    /** Registers an undo action for something this test created. Runs after the test, newest first. */
    protected void registerCleanup(String description, Runnable action) {
        cleanups.push(new Cleanup(description, action));
    }

    private void trackCreatedResources(HttpRequest request, ApiResponse response) {
        if ("POST".equals(request.method()) && "/tasks".equals(request.uri().getPath()) && response.status() == 202) {
            UUID id = UUID.fromString(response.field("task_id"));
            registerCleanup("task " + id, () -> jdbc.update("DELETE FROM tasks WHERE id = ?", id));
        }
    }

    private void sweepStaleRowsOnce() {
        if (!keepData() && staleRowsSwept.compareAndSet(false, true)) {
            sweepStaleRows();
        }
    }

    /** Deletes tagged rows from earlier runs that never cleaned up. Package-private for {@link E2ECleanupE2E}. */
    int sweepStaleRows() {
        int swept = jdbc.update("""
                DELETE FROM tasks
                WHERE prompt LIKE '[e2e %'
                  AND created_at < (now() AT TIME ZONE 'utc') - interval '1 hour'
                """);
        if (swept > 0) {
            log.warn("Swept {} stale E2E task row(s) left by earlier runs", swept);
        }
        return swept;
    }

    private static boolean keepData() {
        return "true".equalsIgnoreCase(System.getenv("E2E_KEEP_DATA"));
    }

    private record Cleanup(String description, Runnable action) {
    }

    // ---- test data --------------------------------------------------------------------------------------------

    /** A prompt tagged with this run's id, so rows are traceable and cleaned up. */
    protected static String prompt(String label) {
        return PROMPT_PREFIX + label;
    }

    protected static void requireEnv(String name) {
        String value = System.getenv(name);
        assumeTrue(value != null && !value.isBlank(), name + " is not set; skipping");
    }

    // ---- API helpers ------------------------------------------------------------------------------------------

    /** POSTs a task that must be accepted, and returns its id. */
    protected UUID createTask(String repositoryUrl, String prompt) {
        ApiResponse response = api.postJson("/tasks", ApiClient.body("repository_url", repositoryUrl, "prompt", prompt));
        assertThat(response.status()).as("create task: %s", response).isEqualTo(202);
        return UUID.fromString(response.field("task_id"));
    }

    // ---- database helpers -------------------------------------------------------------------------------------

    protected Optional<Map<String, Object>> taskRow(UUID id) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT * FROM tasks WHERE id = ?", id);
        return rows.stream().findFirst();
    }

    protected int countTasksWithPrompt(String prompt) {
        return jdbc.queryForObject("SELECT count(*) FROM tasks WHERE prompt = ?", Integer.class, prompt);
    }

    // ---- assertions -------------------------------------------------------------------------------------------

    /** Every error from this API is an RFC 9457 problem document with a machine-readable code. */
    protected static void assertProblem(ApiResponse response, int status, String code) {
        assertThat(response.status()).as("status of %s", response).isEqualTo(status);
        assertThat(response.header("Content-Type")).as("content type of %s", response).startsWith("application/problem+json");
        assertThat(response.field("code")).as("code of %s", response).isEqualTo(code);
        assertThat(response.field("title")).as("title of %s", response).isNotBlank();
        assertThat(response.field("detail")).as("detail of %s", response).isNotBlank();
    }
}
