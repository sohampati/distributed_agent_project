package com.agentexecutor.api.task;

import java.util.UUID;

public class TaskNotFoundException extends RuntimeException {

    public TaskNotFoundException(UUID id) {
        super("Task %s does not exist".formatted(id));
    }
}
