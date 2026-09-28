package com.agentexecutor.api.e2e;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.junit.jupiter.api.Assumptions.assumeFalse;

/** Guards the E2E harness itself: tests must never leave rows in the real database. */
class E2ECleanupE2E extends E2ETestBase {

    @BeforeEach
    void requireCleanupEnabled() {
        assumeFalse("true".equalsIgnoreCase(System.getenv("E2E_KEEP_DATA")), "cleanup disabled by E2E_KEEP_DATA");
    }

    @Test
    void untaggedTaskIsCleanedUpById() {
        // Deliberately not using prompt(): the tag safety net can't find this row, only ID tracking can.
        UUID id = createTask(PUBLIC_REPO, "untagged cleanup check " + RUN_ID);
        assertThat(taskRow(id)).isPresent();

        cleanUp();

        assertThat(taskRow(id)).isEmpty();
    }

    @Test
    void registeredCleanupsRunNewestFirstAndAllRunEvenIfOneFails() {
        StringBuilder order = new StringBuilder();
        registerCleanup("first", () -> order.append("1"));
        registerCleanup("fails", () -> {
            throw new IllegalStateException("boom");
        });
        registerCleanup("last", () -> order.append("3"));

        assertThatThrownBy(this::cleanUp)
                .hasMessageContaining("1 E2E cleanup(s) failed")
                .satisfies(e -> assertThat(e.getSuppressed()[0]).hasMessageContaining("fails"));
        assertThat(order).hasToString("31");
    }

    @Test
    void staleRowsFromKilledRunsAreSwept() {
        UUID stale = UUID.randomUUID();
        UUID recent = UUID.randomUUID();
        LocalDateTime now = LocalDateTime.now(ZoneOffset.UTC);
        insertTask(stale, "[e2e deadbeef] left by a killed run", now.minusHours(2));
        // A recent row may belong to another run still in progress, so it must survive.
        insertTask(recent, "[e2e cafef00d] concurrent run", now);
        registerCleanup("recent row", () -> jdbc.update("DELETE FROM tasks WHERE id = ?", recent));

        sweepStaleRows();

        assertThat(taskRow(stale)).isEmpty();
        assertThat(taskRow(recent)).isPresent();
    }

    private void insertTask(UUID id, String prompt, LocalDateTime createdAt) {
        jdbc.update("INSERT INTO tasks (id, repository_url, prompt, status, created_at) VALUES (?, ?, ?, 'QUEUED', ?)",
                id, PUBLIC_REPO, prompt, createdAt);
    }
}
