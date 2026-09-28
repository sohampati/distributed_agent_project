package com.agentexecutor.api.task.dto;

import com.agentexecutor.api.task.TaskStatus;

import java.util.UUID;

public record CreateTaskResponse(UUID taskId, TaskStatus status) {
}
