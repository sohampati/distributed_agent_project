package com.agentexecutor.api.task.dto;

import com.agentexecutor.api.task.Task;
import com.agentexecutor.api.task.TaskStatus;

import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.UUID;

/** Timestamps are stored as UTC without a zone; the API states the zone explicitly (e.g. 2026-09-28T15:01:33Z). */
public record TaskResponse(
        UUID taskId,
        String repositoryUrl,
        String prompt,
        TaskStatus status,
        String workerId,
        String result,
        String error,
        OffsetDateTime createdAt,
        OffsetDateTime startedAt,
        OffsetDateTime completedAt) {

    public static TaskResponse from(Task task) {
        return new TaskResponse(
                task.getId(),
                task.getRepositoryUrl(),
                task.getPrompt(),
                task.getStatus(),
                task.getWorkerId(),
                task.getResult(),
                task.getError(),
                utc(task.getCreatedAt()),
                utc(task.getStartedAt()),
                utc(task.getCompletedAt()));
    }

    private static OffsetDateTime utc(LocalDateTime time) {
        return time == null ? null : time.atOffset(ZoneOffset.UTC);
    }
}
