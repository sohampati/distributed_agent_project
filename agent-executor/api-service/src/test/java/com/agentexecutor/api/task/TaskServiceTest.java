package com.agentexecutor.api.task;

import com.agentexecutor.api.github.RepositoryError;
import com.agentexecutor.api.github.RepositoryValidationException;
import com.agentexecutor.api.github.RepositoryValidator;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class TaskServiceTest {

    private static final Instant NOW = Instant.parse("2026-09-28T12:00:00.123456789Z");

    private final TaskRepository taskRepository = mock(TaskRepository.class);
    private final RepositoryValidator repositoryValidator = mock(RepositoryValidator.class);
    private final TaskService service =
            new TaskService(taskRepository, repositoryValidator, Clock.fixed(NOW, ZoneOffset.UTC));

    @Test
    void savesQueuedTaskWithCanonicalUrl() {
        when(repositoryValidator.validate("https://github.com/example/project.git"))
                .thenReturn("https://github.com/Example/Project");
        when(taskRepository.save(any(Task.class))).thenAnswer(invocation -> invocation.getArgument(0));

        Task returned = service.create("https://github.com/example/project.git", "Add a health endpoint");

        ArgumentCaptor<Task> saved = ArgumentCaptor.forClass(Task.class);
        verify(taskRepository).save(saved.capture());
        Task task = saved.getValue();
        assertThat(task.getId()).isNotNull();
        assertThat(task.isNew()).isTrue();
        assertThat(task.getRepositoryUrl()).isEqualTo("https://github.com/Example/Project");
        assertThat(task.getPrompt()).isEqualTo("Add a health endpoint");
        assertThat(task.getStatus()).isEqualTo(TaskStatus.QUEUED);
        assertThat(task.getCreatedAt()).isEqualTo(LocalDateTime.of(2026, 9, 28, 12, 0, 0, 123_456_000));
        assertThat(task.getWorkerId()).isNull();
        assertThat(task.getResult()).isNull();
        assertThat(task.getError()).isNull();
        assertThat(task.getStartedAt()).isNull();
        assertThat(task.getCompletedAt()).isNull();
        assertThat(returned.getId()).isEqualTo(task.getId());
    }

    @Test
    void generatesDistinctIds() {
        when(repositoryValidator.validate(any())).thenReturn("https://github.com/example/project");
        when(taskRepository.save(any(Task.class))).thenAnswer(invocation -> invocation.getArgument(0));

        Task first = service.create("https://github.com/example/project", "one");
        Task second = service.create("https://github.com/example/project", "two");

        assertThat(first.getId()).isNotEqualTo(second.getId());
    }

    @Test
    void getReturnsExistingTask() {
        Task task = Task.queued(UUID.randomUUID(), "https://github.com/example/project", "prompt", LocalDateTime.now());
        when(taskRepository.findById(task.getId())).thenReturn(Optional.of(task));

        assertThat(service.get(task.getId())).isSameAs(task);
    }

    @Test
    void getUnknownTaskThrows() {
        UUID id = UUID.randomUUID();
        when(taskRepository.findById(id)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.get(id)).isInstanceOf(TaskNotFoundException.class);
    }

    @Test
    void rejectedRepositoryIsNeverSaved() {
        when(repositoryValidator.validate(any())).thenThrow(
                new RepositoryValidationException(RepositoryError.REPOSITORY_NOT_FOUND_OR_INACCESSIBLE, "nope"));

        assertThatThrownBy(() -> service.create("https://github.com/example/missing", "prompt"))
                .isInstanceOf(RepositoryValidationException.class);

        verifyNoInteractions(taskRepository);
    }
}
