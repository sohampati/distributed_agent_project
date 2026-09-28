package com.agentexecutor.api.github;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/** The subset of GitHub's {@code GET /repos/{owner}/{repo}} response we care about. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record GitHubRepository(
        @JsonProperty("full_name") String fullName,
        @JsonProperty("html_url") String htmlUrl,
        @JsonProperty("private") boolean isPrivate,
        @JsonProperty("archived") boolean archived,
        @JsonProperty("disabled") boolean disabled) {
}
