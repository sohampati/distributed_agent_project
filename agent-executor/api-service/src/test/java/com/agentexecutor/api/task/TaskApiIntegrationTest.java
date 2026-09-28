package com.agentexecutor.api.task;

import com.agentexecutor.api.github.GitHubClient;
import com.agentexecutor.api.github.GitHubRepoRef;
import com.agentexecutor.api.github.GitHubRepository;
import com.agentexecutor.api.github.RepositoryError;
import com.agentexecutor.api.github.RepositoryValidationException;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Full stack against the local {@code agent_executor_test} database (schema built by Flyway). Only the HTTP call to
 * GitHub is mocked, so URL parsing and the archived/disabled policy run for real.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class TaskApiIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @MockitoBean
    private GitHubClient gitHubClient;

    @BeforeEach
    void clearTasks() {
        jdbcTemplate.update("DELETE FROM tasks");
    }

    @Test
    void persistsQueuedTaskWithCanonicalUrl() throws Exception {
        when(gitHubClient.getRepository(new GitHubRepoRef("example", "project")))
                .thenReturn(new GitHubRepository("Example/Project", "https://github.com/Example/Project", false, false, false));
        LocalDateTime before = LocalDateTime.now(ZoneOffset.UTC).truncatedTo(ChronoUnit.MICROS);

        String response = mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content("""
                        {"repository_url": "https://github.com/example/project.git", "prompt": "Add a health endpoint and write tests"}
                        """))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.status").value("QUEUED"))
                .andReturn().getResponse().getContentAsString();
        UUID id = UUID.fromString(JsonPath.read(response, "$.task_id"));

        Map<String, Object> row = jdbcTemplate.queryForMap("SELECT * FROM tasks WHERE id = ?", id);
        assertThat(row.get("repository_url")).isEqualTo("https://github.com/Example/Project");
        assertThat(row.get("prompt")).isEqualTo("Add a health endpoint and write tests");
        assertThat(row.get("status")).isEqualTo("QUEUED");
        assertThat(row.get("worker_id")).isNull();
        assertThat(row.get("result")).isNull();
        assertThat(row.get("error")).isNull();
        assertThat(row.get("started_at")).isNull();
        assertThat(row.get("completed_at")).isNull();
        LocalDateTime createdAt = ((java.sql.Timestamp) row.get("created_at")).toLocalDateTime();
        assertThat(createdAt).isBetween(before, LocalDateTime.now(ZoneOffset.UTC));
    }

    @Test
    void getReturnsWhatPostCreated() throws Exception {
        when(gitHubClient.getRepository(any()))
                .thenReturn(new GitHubRepository("example/project", "https://github.com/example/project", false, false, false));

        String location = mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content("""
                        {"repository_url": "https://github.com/example/project", "prompt": "round trip"}
                        """))
                .andExpect(status().isAccepted())
                .andReturn().getResponse().getHeader("Location");
        LocalDateTime storedCreatedAt = jdbcTemplate.queryForObject("SELECT created_at FROM tasks", LocalDateTime.class);

        // Follow the Location header, as a client would.
        String body = mockMvc.perform(get(location))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.task_id").value(location.substring(location.lastIndexOf('/') + 1)))
                .andExpect(jsonPath("$.repository_url").value("https://github.com/example/project"))
                .andExpect(jsonPath("$.prompt").value("round trip"))
                .andExpect(jsonPath("$.status").value("QUEUED"))
                .andExpect(jsonPath("$.worker_id").doesNotExist())
                .andReturn().getResponse().getContentAsString();

        // Compare as instants: the JSON drops trailing zeros from the fraction (.550860 -> .55086).
        OffsetDateTime createdAt = OffsetDateTime.parse(JsonPath.read(body, "$.created_at"));
        assertThat(createdAt).isEqualTo(storedCreatedAt.atOffset(ZoneOffset.UTC));
    }

    @Test
    void getUnknownTaskIs404() throws Exception {
        mockMvc.perform(get("/tasks/{id}", UUID.randomUUID()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("TASK_NOT_FOUND"));
    }

    @Test
    void twoRequestsCreateTwoRows() throws Exception {
        when(gitHubClient.getRepository(any()))
                .thenReturn(new GitHubRepository("example/project", "https://github.com/example/project", false, false, false));
        String body = """
                {"repository_url": "https://github.com/example/project", "prompt": "do it"}
                """;

        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content(body)).andExpect(status().isAccepted());
        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content(body)).andExpect(status().isAccepted());

        assertThat(jdbcTemplate.queryForObject("SELECT count(DISTINCT id) FROM tasks", Integer.class)).isEqualTo(2);
    }

    @Test
    void inaccessibleRepositoryWritesNothing() throws Exception {
        when(gitHubClient.getRepository(any())).thenThrow(new RepositoryValidationException(
                RepositoryError.REPOSITORY_NOT_FOUND_OR_INACCESSIBLE, "not found"));

        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content("""
                        {"repository_url": "https://github.com/example/missing", "prompt": "do it"}
                        """))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.code").value("REPOSITORY_NOT_FOUND_OR_INACCESSIBLE"));

        assertThat(jdbcTemplate.queryForObject("SELECT count(*) FROM tasks", Integer.class)).isZero();
    }

    @Test
    void archivedRepositoryWritesNothing() throws Exception {
        when(gitHubClient.getRepository(any()))
                .thenReturn(new GitHubRepository("example/old", "https://github.com/example/old", false, true, false));

        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content("""
                        {"repository_url": "https://github.com/example/old", "prompt": "do it"}
                        """))
                .andExpect(status().isUnprocessableContent())
                .andExpect(jsonPath("$.code").value("REPOSITORY_ARCHIVED"));

        assertThat(jdbcTemplate.queryForObject("SELECT count(*) FROM tasks", Integer.class)).isZero();
    }

    @Test
    void nonGitHubUrlIsRejectedWithoutWriting() throws Exception {
        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content("""
                        {"repository_url": "https://gitlab.com/example/project", "prompt": "do it"}
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REPOSITORY_URL"));

        assertThat(jdbcTemplate.queryForObject("SELECT count(*) FROM tasks", Integer.class)).isZero();
    }
}
