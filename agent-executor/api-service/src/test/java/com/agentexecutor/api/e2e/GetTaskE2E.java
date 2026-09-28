package com.agentexecutor.api.e2e;

import com.agentexecutor.api.e2e.ApiClient.ApiResponse;
import org.junit.jupiter.api.Test;

import java.sql.Timestamp;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Map;
import java.util.UUID;

import static com.agentexecutor.api.e2e.ApiClient.body;
import static org.assertj.core.api.Assertions.assertThat;

/** {@code GET /tasks/{id}} */
class GetTaskE2E extends E2ETestBase {

    @Test
    void followingLocationReturnsTheStoredTask() {
        String prompt = prompt("get round trip");
        ApiResponse created = api.postJson("/tasks", body("repository_url", PUBLIC_REPO, "prompt", prompt));
        assertThat(created.status()).as("%s", created).isEqualTo(202);

        ApiResponse response = api.get(created.header("Location"));

        assertThat(response.status()).as("%s", response).isEqualTo(200);
        UUID id = UUID.fromString(response.field("task_id"));
        assertThat(id.toString()).isEqualTo(created.field("task_id"));
        assertThat(response.field("repository_url")).isEqualTo(PUBLIC_REPO);
        assertThat(response.field("prompt")).isEqualTo(prompt);
        assertThat(response.field("status")).isEqualTo("QUEUED");
        assertThat(response.field("worker_id")).isNull();
        assertThat(response.field("started_at")).isNull();
        assertThat(response.field("completed_at")).isNull();

        // created_at is the stored UTC value, with the zone made explicit.
        Map<String, Object> row = taskRow(id).orElseThrow();
        OffsetDateTime stored = ((Timestamp) row.get("created_at")).toLocalDateTime().atOffset(ZoneOffset.UTC);
        assertThat(OffsetDateTime.parse(response.field("created_at"))).isEqualTo(stored);
        assertThat(response.field("created_at")).endsWith("Z");
    }

    @Test
    void unknownTaskIs404() {
        assertProblem(api.get("/tasks/" + UUID.randomUUID()), 404, "TASK_NOT_FOUND");
    }

    @Test
    void nonUuidIdIs400() {
        assertProblem(api.get("/tasks/not-a-uuid"), 400, "BAD_REQUEST");
    }
}
