package com.agentexecutor.api.e2e;

import com.agentexecutor.api.e2e.ApiClient.ApiResponse;
import org.junit.jupiter.api.Test;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.UUID;

import static com.agentexecutor.api.e2e.ApiClient.body;
import static org.assertj.core.api.Assertions.assertThat;

/** {@code POST /tasks} */
class CreateTaskE2E extends E2ETestBase {

    @Test
    void publicRepositoryIsQueued() {
        String prompt = prompt("public repo");
        LocalDateTime before = LocalDateTime.now(ZoneOffset.UTC).truncatedTo(ChronoUnit.MICROS);

        ApiResponse response = api.postJson("/tasks", body("repository_url", PUBLIC_REPO, "prompt", prompt));

        assertThat(response.status()).as("%s", response).isEqualTo(202);
        UUID id = UUID.fromString(response.field("task_id"));
        assertThat(response.field("status")).isEqualTo("QUEUED");
        assertThat(response.header("Location")).isEqualTo(api.baseUrl() + "/tasks/" + id);

        Map<String, Object> row = taskRow(id).orElseThrow();
        assertThat(row.get("repository_url")).isEqualTo(PUBLIC_REPO);
        assertThat(row.get("prompt")).isEqualTo(prompt);
        assertThat(row.get("status")).isEqualTo("QUEUED");
        assertThat(row.get("worker_id")).isNull();
        assertThat(row.get("result")).isNull();
        assertThat(row.get("error")).isNull();
        assertThat(row.get("started_at")).isNull();
        assertThat(row.get("completed_at")).isNull();
        assertThat(((Timestamp) row.get("created_at")).toLocalDateTime())
                .isBetween(before, LocalDateTime.now(ZoneOffset.UTC));
    }

    @Test
    void repositoryUrlIsStoredInGitHubsCanonicalForm() {
        UUID id = createTask("https://github.com/SPRING-PROJECTS/Spring-Boot.git/", prompt("canonical url"));

        assertThat(taskRow(id).orElseThrow().get("repository_url")).isEqualTo(PUBLIC_REPO);
    }

    @Test
    void privateRepositoryVisibleToTokenIsQueued() {
        // e.g. E2E_PRIVATE_REPO=https://github.com/sohampati/vd
        requireEnv("GITHUB_TOKEN");
        requireEnv("E2E_PRIVATE_REPO");

        UUID id = createTask(System.getenv("E2E_PRIVATE_REPO"), prompt("private repo"));

        assertThat(taskRow(id)).isPresent();
    }

    @Test
    void missingRepositoryIsRejectedAndNotStored() {
        assertRejected(MISSING_REPO, 422, "REPOSITORY_NOT_FOUND_OR_INACCESSIBLE");
    }

    @Test
    void archivedRepositoryIsRejectedAndNotStored() {
        assertRejected(ARCHIVED_REPO, 422, "REPOSITORY_ARCHIVED");
    }

    @Test
    void nonGitHubUrlIsRejectedAndNotStored() {
        assertRejected("https://gitlab.com/example/project", 400, "INVALID_REPOSITORY_URL");
    }

    @Test
    void gitHubSubPathIsRejectedAndNotStored() {
        assertRejected(PUBLIC_REPO + "/tree/main", 400, "INVALID_REPOSITORY_URL");
    }

    @Test
    void missingFieldsAreReportedPerField() {
        ApiResponse response = api.postJson("/tasks", body("prompt", ""));

        assertProblem(response, 400, "VALIDATION_FAILED");
        assertThat(response.json().path("errors").propertyNames()).containsExactlyInAnyOrder("repository_url", "prompt");
    }

    @Test
    void malformedJsonIsRejected() {
        assertProblem(api.post("/tasks", "{\"repository_url\":", "application/json"), 400, "BAD_REQUEST");
    }

    @Test
    void nonJsonContentTypeIsRejected() {
        assertProblem(api.post("/tasks", "hello", "text/plain"), 415, "UNSUPPORTED_MEDIA_TYPE");
    }

    private void assertRejected(String repositoryUrl, int status, String code) {
        String prompt = prompt("rejected " + code);

        ApiResponse response = api.postJson("/tasks", body("repository_url", repositoryUrl, "prompt", prompt));

        assertProblem(response, status, code);
        assertThat(countTasksWithPrompt(prompt)).as("rows written for rejected request").isZero();
    }
}
