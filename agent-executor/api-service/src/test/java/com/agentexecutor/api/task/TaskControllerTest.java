package com.agentexecutor.api.task;

import com.agentexecutor.api.github.RepositoryError;
import com.agentexecutor.api.github.RepositoryValidationException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(TaskController.class)
class TaskControllerTest {

    private static final String VALID_BODY = """
            {"repository_url": "https://github.com/example/project", "prompt": "Add a health endpoint and write tests"}
            """;

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private TaskService taskService;

    @Test
    void returns202WithTaskIdAndLocation() throws Exception {
        UUID id = UUID.fromString("8f7c2b9e-1111-4222-8333-444455556666");
        when(taskService.create("https://github.com/example/project", "Add a health endpoint and write tests"))
                .thenReturn(Task.queued(id, "https://github.com/example/project", "prompt", LocalDateTime.now()));

        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content(VALID_BODY))
                .andExpect(status().isAccepted())
                .andExpect(header().string("Location", "http://localhost/tasks/" + id))
                .andExpect(jsonPath("$.task_id").value(id.toString()))
                .andExpect(jsonPath("$.status").value("QUEUED"))
                .andExpect(jsonPath("$.taskId").doesNotExist());
    }

    @Test
    void missingFieldsAreReportedInSnakeCase() throws Exception {
        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.errors.repository_url").exists())
                .andExpect(jsonPath("$.errors.prompt").exists());

        verifyNoInteractions(taskService);
    }

    @Test
    void blankPromptIsRejected() throws Exception {
        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"repository_url": "https://github.com/example/project", "prompt": "   "}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.prompt").exists());

        verifyNoInteractions(taskService);
    }

    @Test
    void oversizedPromptIsRejected() throws Exception {
        String body = """
                {"repository_url": "https://github.com/example/project", "prompt": "%s"}
                """.formatted("x".repeat(10_001));

        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.prompt").exists());
    }

    @Test
    void malformedJsonIsRejected() throws Exception {
        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content("{\"repository_url\": "))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("BAD_REQUEST"));

        verifyNoInteractions(taskService);
    }

    @Test
    void nonJsonContentTypeIsRejected() throws Exception {
        mockMvc.perform(post("/tasks").contentType(MediaType.TEXT_PLAIN).content("hello"))
                .andExpect(status().isUnsupportedMediaType())
                .andExpect(jsonPath("$.code").value("UNSUPPORTED_MEDIA_TYPE"));
    }

    @ParameterizedTest
    @EnumSource(RepositoryError.class)
    void everyRepositoryErrorMapsToItsStatusAndCode(RepositoryError error) throws Exception {
        when(taskService.create(any(), any())).thenThrow(new RepositoryValidationException(error, "detail message"));

        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content(VALID_BODY))
                .andExpect(status().is(error.status().value()))
                .andExpect(header().string("Content-Type", MediaType.APPLICATION_PROBLEM_JSON_VALUE))
                .andExpect(jsonPath("$.code").value(error.name()))
                .andExpect(jsonPath("$.title").value(error.title()))
                .andExpect(jsonPath("$.detail").value("detail message"));
    }

    @Test
    void rateLimitSetsRetryAfterHeader() throws Exception {
        when(taskService.create(any(), any())).thenThrow(new RepositoryValidationException(
                RepositoryError.GITHUB_RATE_LIMITED, "slow down", Duration.ofSeconds(42)));

        mockMvc.perform(post("/tasks").contentType(MediaType.APPLICATION_JSON).content(VALID_BODY))
                .andExpect(status().isServiceUnavailable())
                .andExpect(header().string("Retry-After", "42"));
    }
}
