package com.agentexecutor.api.e2e;

import com.agentexecutor.api.e2e.ApiClient.ApiResponse;
import org.junit.jupiter.api.Test;
import org.springframework.test.context.TestPropertySource;

import static com.agentexecutor.api.e2e.ApiClient.body;
import static org.assertj.core.api.Assertions.assertThat;

/** The server's own GitHub credentials are wrong: a server-side 502, not the client's fault. Runs in its own app context. */
@TestPropertySource(properties = "github.token=ghp_e2e_deliberately_invalid")
class GitHubAuthFailureE2E extends E2ETestBase {

    @Test
    void invalidServerTokenIs502AndNotStored() {
        String prompt = prompt("invalid server token");

        ApiResponse response = api.postJson("/tasks", body("repository_url", PUBLIC_REPO, "prompt", prompt));

        assertProblem(response, 502, "GITHUB_AUTH_MISCONFIGURED");
        assertThat(countTasksWithPrompt(prompt)).isZero();
    }
}
