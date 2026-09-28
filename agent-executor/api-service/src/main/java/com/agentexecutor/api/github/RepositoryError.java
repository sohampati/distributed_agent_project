package com.agentexecutor.api.github;

import org.springframework.http.HttpStatus;

/**
 * Why a repository was rejected. 4xx codes are the client's to fix; 5xx codes are problems on our side or GitHub's.
 */
public enum RepositoryError {
    INVALID_REPOSITORY_URL(HttpStatus.BAD_REQUEST, "Invalid repository URL"),
    REPOSITORY_NOT_FOUND_OR_INACCESSIBLE(HttpStatus.UNPROCESSABLE_CONTENT, "Repository not found or inaccessible"),
    REPOSITORY_ACCESS_DENIED(HttpStatus.UNPROCESSABLE_CONTENT, "Repository access denied"),
    REPOSITORY_DISABLED(HttpStatus.UNPROCESSABLE_CONTENT, "Repository disabled"),
    REPOSITORY_ARCHIVED(HttpStatus.UNPROCESSABLE_CONTENT, "Repository archived"),
    REPOSITORY_UNAVAILABLE_LEGAL(HttpStatus.UNPROCESSABLE_CONTENT, "Repository unavailable for legal reasons"),
    GITHUB_AUTH_MISCONFIGURED(HttpStatus.BAD_GATEWAY, "GitHub authentication misconfigured"),
    GITHUB_RATE_LIMITED(HttpStatus.SERVICE_UNAVAILABLE, "GitHub rate limit exceeded"),
    GITHUB_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "GitHub unavailable");

    private final HttpStatus status;
    private final String title;

    RepositoryError(HttpStatus status, String title) {
        this.status = status;
        this.title = title;
    }

    public HttpStatus status() {
        return status;
    }

    public String title() {
        return title;
    }
}
