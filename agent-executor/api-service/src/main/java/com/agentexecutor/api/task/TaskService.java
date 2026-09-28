package com.agentexecutor.api.task;

import com.agentexecutor.api.github.RepositoryValidator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

@Service
public class TaskService {

    private static final Logger log = LoggerFactory.getLogger(TaskService.class);

    private final TaskRepository taskRepository;
    private final RepositoryValidator repositoryValidator;
    private final Clock clock;

    public TaskService(TaskRepository taskRepository, RepositoryValidator repositoryValidator, Clock clock) {
        this.taskRepository = taskRepository;
        this.repositoryValidator = repositoryValidator;
        this.clock = clock;
    }

    /**
     * Records a new task as QUEUED and returns immediately; workers pick it up later.
     * Deliberately not {@code @Transactional}: the GitHub call must not hold a database connection open.
     */
    public Task create(String repositoryUrl, String prompt) {
        String canonicalUrl = repositoryValidator.validate(repositoryUrl);

        // Postgres stores microseconds; truncating keeps the in-memory value equal to what is persisted.
        LocalDateTime now = LocalDateTime.now(clock).truncatedTo(ChronoUnit.MICROS);
        Task task = taskRepository.save(Task.queued(UUID.randomUUID(), canonicalUrl, prompt, now));

        log.info("Queued task {} for {}", task.getId(), canonicalUrl);
        return task;
    }

    public Task get(UUID id) {
        return taskRepository.findById(id).orElseThrow(() -> new TaskNotFoundException(id));
    }
}
