package com.agentexecutor.api.task;

import com.agentexecutor.api.task.dto.CreateTaskRequest;
import com.agentexecutor.api.task.dto.CreateTaskResponse;
import com.agentexecutor.api.task.dto.TaskResponse;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.support.ServletUriComponentsBuilder;

import java.net.URI;
import java.util.UUID;

@RestController
@RequestMapping("/tasks")
public class TaskController {

    private final TaskService taskService;

    public TaskController(TaskService taskService) {
        this.taskService = taskService;
    }

    /** 202 Accepted: the task is durably queued, not executed. */
    @PostMapping(consumes = MediaType.APPLICATION_JSON_VALUE, produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<CreateTaskResponse> create(@Valid @RequestBody CreateTaskRequest request) {
        Task task = taskService.create(request.repositoryUrl(), request.prompt());
        URI location = ServletUriComponentsBuilder.fromCurrentRequest()
                .path("/{id}")
                .buildAndExpand(task.getId())
                .toUri();
        return ResponseEntity.accepted()
                .location(location)
                .body(new CreateTaskResponse(task.getId(), task.getStatus()));
    }

    @GetMapping(path = "/{id}", produces = MediaType.APPLICATION_JSON_VALUE)
    public TaskResponse get(@PathVariable UUID id) {
        return TaskResponse.from(taskService.get(id));
    }
}
