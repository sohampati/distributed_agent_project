package com.agentexecutor.api.github;

import java.time.Duration;
import java.util.Optional;

public class RepositoryValidationException extends RuntimeException {

    private final RepositoryError error;
    private final Duration retryAfter;

    public RepositoryValidationException(RepositoryError error, String detail) {
        this(error, detail, null, null);
    }

    public RepositoryValidationException(RepositoryError error, String detail, Duration retryAfter) {
        this(error, detail, retryAfter, null);
    }

    public RepositoryValidationException(RepositoryError error, String detail, Duration retryAfter, Throwable cause) {
        super(detail, cause);
        this.error = error;
        this.retryAfter = retryAfter;
    }

    public RepositoryError error() {
        return error;
    }

    public Optional<Duration> retryAfter() {
        return Optional.ofNullable(retryAfter);
    }
}
