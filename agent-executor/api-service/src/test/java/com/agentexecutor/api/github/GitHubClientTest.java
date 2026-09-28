package com.agentexecutor.api.github;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.net.SocketTimeoutException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withException;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class GitHubClientTest {

    private static final Instant NOW = Instant.parse("2026-09-28T12:00:00Z");
    private static final GitHubRepoRef REF = new GitHubRepoRef("example", "project");
    private static final String REPO_URL = "https://api.github.com/repos/example/project";

    private MockRestServiceServer server;
    private GitHubClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("https://api.github.com");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new GitHubClient(builder.build(), Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void returnsRepositoryOn200() {
        server.expect(requestTo(REPO_URL)).andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess("""
                        {"full_name": "Example/Project", "html_url": "https://github.com/Example/Project",
                         "private": true, "archived": false, "disabled": false, "stargazers_count": 3}
                        """, MediaType.APPLICATION_JSON));

        GitHubRepository repository = client.getRepository(REF);

        assertThat(repository).isEqualTo(
                new GitHubRepository("Example/Project", "https://github.com/Example/Project", true, false, false));
        server.verify();
    }

    @Test
    void notFoundMeansMissingOrPrivate() {
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.NOT_FOUND));

        assertRejected(RepositoryError.REPOSITORY_NOT_FOUND_OR_INACCESSIBLE);
    }

    @Test
    void unauthorizedMeansOurTokenIsBad() {
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.UNAUTHORIZED));

        assertRejected(RepositoryError.GITHUB_AUTH_MISCONFIGURED);
    }

    @Test
    void forbiddenWithoutRateLimitHeadersIsAccessDenied() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("x-ratelimit-remaining", "4999");
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.FORBIDDEN).headers(headers));

        assertRejected(RepositoryError.REPOSITORY_ACCESS_DENIED);
    }

    @Test
    void unavailableForLegalReasons() {
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.UNAVAILABLE_FOR_LEGAL_REASONS));

        assertRejected(RepositoryError.REPOSITORY_UNAVAILABLE_LEGAL);
    }

    @Test
    void primaryRateLimitUsesResetHeaderForRetryAfter() {
        HttpHeaders headers = new HttpHeaders();
        headers.set("x-ratelimit-remaining", "0");
        headers.set("x-ratelimit-reset", String.valueOf(NOW.plusSeconds(120).getEpochSecond()));
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.FORBIDDEN).headers(headers));

        RepositoryValidationException e = assertRejected(RepositoryError.GITHUB_RATE_LIMITED);
        assertThat(e.retryAfter()).contains(Duration.ofSeconds(120));
    }

    @Test
    void secondaryRateLimitUsesRetryAfterHeader() {
        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.RETRY_AFTER, "30");
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.FORBIDDEN).headers(headers));

        RepositoryValidationException e = assertRejected(RepositoryError.GITHUB_RATE_LIMITED);
        assertThat(e.retryAfter()).contains(Duration.ofSeconds(30));
    }

    @Test
    void tooManyRequestsWithoutHeadersDefaultsRetryAfter() {
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS));

        RepositoryValidationException e = assertRejected(RepositoryError.GITHUB_RATE_LIMITED);
        assertThat(e.retryAfter()).contains(Duration.ofSeconds(60));
    }

    @ParameterizedTest
    @ValueSource(ints = {500, 502, 503, 504})
    void serverErrorsMeanGitHubUnavailable(int status) {
        server.expect(requestTo(REPO_URL)).andRespond(withStatus(HttpStatus.valueOf(status)));

        assertRejected(RepositoryError.GITHUB_UNAVAILABLE);
    }

    @Test
    void timeoutMeansGitHubUnavailable() {
        server.expect(requestTo(REPO_URL)).andRespond(withException(new SocketTimeoutException("Read timed out")));

        assertRejected(RepositoryError.GITHUB_UNAVAILABLE);
    }

    private RepositoryValidationException assertRejected(RepositoryError expected) {
        RepositoryValidationException[] caught = new RepositoryValidationException[1];
        assertThatThrownBy(() -> client.getRepository(REF))
                .isInstanceOfSatisfying(RepositoryValidationException.class, e -> {
                    assertThat(e.error()).isEqualTo(expected);
                    caught[0] = e;
                });
        server.verify();
        return caught[0];
    }
}
