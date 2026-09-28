package com.agentexecutor.api.github;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import java.time.Clock;
import java.time.Duration;

/**
 * Looks up repositories through the GitHub REST API and turns every non-200 outcome into a
 * {@link RepositoryValidationException} with a specific {@link RepositoryError}.
 */
public class GitHubClient {

    private static final Logger log = LoggerFactory.getLogger(GitHubClient.class);

    private final RestClient restClient;
    private final Clock clock;

    public GitHubClient(RestClient restClient, Clock clock) {
        this.restClient = restClient;
        this.clock = clock;
    }

    public GitHubRepository getRepository(GitHubRepoRef ref) {
        try {
            return restClient.get()
                    .uri("/repos/{owner}/{repo}", ref.owner(), ref.name())
                    .exchange((request, response) -> {
                        int status = response.getStatusCode().value();
                        if (status == 200) {
                            GitHubRepository repository = response.bodyTo(GitHubRepository.class);
                            if (repository == null || repository.htmlUrl() == null) {
                                throw unavailable(ref, "GitHub returned an empty repository response", null);
                            }
                            return repository;
                        }
                        throw toException(ref, status, response.getHeaders());
                    });
        } catch (ResourceAccessException e) {
            // Connection refused, DNS failure, or connect/read timeout.
            throw unavailable(ref, "Could not reach GitHub: " + e.getMessage(), e);
        }
    }

    private RepositoryValidationException toException(GitHubRepoRef ref, int status, HttpHeaders headers) {
        if (isRateLimited(status, headers)) {
            Duration retryAfter = retryAfter(headers);
            log.warn("GitHub rate limit hit while checking {}; retry after {}s", ref.fullName(), retryAfter.toSeconds());
            return new RepositoryValidationException(RepositoryError.GITHUB_RATE_LIMITED,
                    "GitHub API rate limit exceeded; retry after %d seconds".formatted(retryAfter.toSeconds()), retryAfter);
        }
        return switch (status) {
            case 401 -> {
                log.error("GitHub rejected our credentials (401) while checking {}; check GITHUB_TOKEN", ref.fullName());
                yield new RepositoryValidationException(RepositoryError.GITHUB_AUTH_MISCONFIGURED,
                        "The server's GitHub credentials were rejected; this is a server configuration problem");
            }
            case 403 -> new RepositoryValidationException(RepositoryError.REPOSITORY_ACCESS_DENIED,
                    "Access to %s is forbidden (e.g. organization SSO or insufficient token permissions)".formatted(ref.fullName()));
            // GitHub answers 404 for both missing repositories and private ones we cannot see.
            case 404 -> new RepositoryValidationException(RepositoryError.REPOSITORY_NOT_FOUND_OR_INACCESSIBLE,
                    "Repository %s does not exist, or it is private and not accessible to this service".formatted(ref.fullName()));
            case 451 -> new RepositoryValidationException(RepositoryError.REPOSITORY_UNAVAILABLE_LEGAL,
                    "Repository %s is unavailable for legal reasons".formatted(ref.fullName()));
            default -> unavailable(ref, "GitHub responded with HTTP " + status, null);
        };
    }

    private static boolean isRateLimited(int status, HttpHeaders headers) {
        if (status == 429) {
            return true;
        }
        // Primary limit: remaining hits 0. Secondary (abuse) limit: Retry-After is set.
        return status == 403
                && ("0".equals(headers.getFirst("x-ratelimit-remaining")) || headers.getFirst(HttpHeaders.RETRY_AFTER) != null);
    }

    private Duration retryAfter(HttpHeaders headers) {
        String retryAfter = headers.getFirst(HttpHeaders.RETRY_AFTER);
        if (retryAfter != null) {
            try {
                return Duration.ofSeconds(Math.max(1, Long.parseLong(retryAfter.strip())));
            } catch (NumberFormatException ignored) {
                // Fall through to the reset header.
            }
        }
        String reset = headers.getFirst("x-ratelimit-reset");
        if (reset != null) {
            try {
                long seconds = Long.parseLong(reset.strip()) - clock.instant().getEpochSecond();
                return Duration.ofSeconds(Math.max(1, seconds));
            } catch (NumberFormatException ignored) {
                // Fall through to the default.
            }
        }
        return Duration.ofSeconds(60);
    }

    private static RepositoryValidationException unavailable(GitHubRepoRef ref, String reason, Throwable cause) {
        log.warn("GitHub unavailable while checking {}: {}", ref.fullName(), reason);
        return new RepositoryValidationException(RepositoryError.GITHUB_UNAVAILABLE,
                "GitHub is currently unavailable; please retry", null, cause);
    }
}
