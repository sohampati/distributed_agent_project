package com.agentexecutor.api.task;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.PostLoad;
import jakarta.persistence.PostPersist;
import jakarta.persistence.Table;
import jakarta.persistence.Transient;
import org.springframework.data.domain.Persistable;

import java.time.LocalDateTime;
import java.util.UUID;

@Entity
@Table(name = "tasks")
public class Task implements Persistable<UUID> {

    @Id
    private UUID id;

    @Column(name = "repository_url", nullable = false)
    private String repositoryUrl;

    @Column(nullable = false)
    private String prompt;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private TaskStatus status;

    @Column(name = "worker_id", length = 100)
    private String workerId;

    private String result;

    private String error;

    /** UTC wall-clock time (the column has no time zone); written as-is, so don't set hibernate.jdbc.time_zone. */
    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;

    @Column(name = "started_at")
    private LocalDateTime startedAt;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;

    // The id is assigned by us, so tell Spring Data this is an insert rather than letting it SELECT first to decide.
    @Transient
    private boolean isNew = true;

    protected Task() {
    }

    public static Task queued(UUID id, String repositoryUrl, String prompt, LocalDateTime createdAt) {
        Task task = new Task();
        task.id = id;
        task.repositoryUrl = repositoryUrl;
        task.prompt = prompt;
        task.status = TaskStatus.QUEUED;
        task.createdAt = createdAt;
        return task;
    }

    @PostLoad
    @PostPersist
    void markNotNew() {
        this.isNew = false;
    }

    @Override
    public UUID getId() {
        return id;
    }

    @Override
    public boolean isNew() {
        return isNew;
    }

    public String getRepositoryUrl() {
        return repositoryUrl;
    }

    public String getPrompt() {
        return prompt;
    }

    public TaskStatus getStatus() {
        return status;
    }

    public String getWorkerId() {
        return workerId;
    }

    public String getResult() {
        return result;
    }

    public String getError() {
        return error;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public LocalDateTime getStartedAt() {
        return startedAt;
    }

    public LocalDateTime getCompletedAt() {
        return completedAt;
    }
}
