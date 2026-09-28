package com.agentexecutor.api.github;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

@ConfigurationProperties(prefix = "github")
public record GitHubProperties(String apiUrl, String token, Duration connectTimeout, Duration readTimeout) {

    public boolean hasToken() {
        return token != null && !token.isBlank();
    }
}
