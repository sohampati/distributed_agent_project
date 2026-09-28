package com.agentexecutor.api.task.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/** GitHub-specific URL checks happen in {@link com.agentexecutor.api.github.RepositoryValidator}. */
public record CreateTaskRequest(
        @NotBlank @Size(max = 2048) String repositoryUrl,
        @NotBlank @Size(max = 10_000) String prompt) {
}
