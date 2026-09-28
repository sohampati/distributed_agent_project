package com.agentexecutor.api.e2e;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpHeaders;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.BiConsumer;

/**
 * Minimal real-HTTP client for E2E tests. Never throws on 4xx/5xx: tests assert on the status themselves.
 * Takes a base URL so the same tests could later target a deployed instance.
 */
public class ApiClient {

    private static final JsonMapper JSON = JsonMapper.builder().build();

    private final String baseUrl;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build();
    private final BiConsumer<HttpRequest, ApiResponse> onResponse;

    public ApiClient(String baseUrl) {
        this(baseUrl, (request, response) -> { });
    }

    /** {@code onResponse} sees every exchange, e.g. so tests can track what they created for cleanup. */
    public ApiClient(String baseUrl, BiConsumer<HttpRequest, ApiResponse> onResponse) {
        this.baseUrl = baseUrl;
        this.onResponse = onResponse;
    }

    public String baseUrl() {
        return baseUrl;
    }

    public ApiResponse get(String path) {
        return send(HttpRequest.newBuilder(uri(path)).GET());
    }

    public ApiResponse postJson(String path, Object body) {
        return post(path, JSON.writeValueAsString(body), "application/json");
    }

    public ApiResponse post(String path, String rawBody, String contentType) {
        return send(HttpRequest.newBuilder(uri(path))
                .header("Content-Type", contentType)
                .POST(HttpRequest.BodyPublishers.ofString(rawBody)));
    }

    /** Convenience body builder, e.g. {@code body("repository_url", url, "prompt", p)}. */
    public static Map<String, Object> body(Object... keyValues) {
        Map<String, Object> map = new LinkedHashMap<>();
        for (int i = 0; i < keyValues.length; i += 2) {
            map.put((String) keyValues[i], keyValues[i + 1]);
        }
        return map;
    }

    private URI uri(String pathOrAbsoluteUrl) {
        return URI.create(pathOrAbsoluteUrl.startsWith("http") ? pathOrAbsoluteUrl : baseUrl + pathOrAbsoluteUrl);
    }

    private ApiResponse send(HttpRequest.Builder request) {
        long start = System.nanoTime();
        try {
            HttpRequest built = request.timeout(Duration.ofSeconds(15)).build();
            HttpResponse<String> response = http.send(built, HttpResponse.BodyHandlers.ofString());
            Duration elapsed = Duration.ofNanos(System.nanoTime() - start);
            String raw = response.body();
            JsonNode json = raw == null || raw.isBlank() ? JSON.missingNode() : JSON.readTree(raw);
            ApiResponse apiResponse = new ApiResponse(response.statusCode(), response.headers(), json, raw, elapsed);
            onResponse.accept(built, apiResponse);
            return apiResponse;
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(e);
        }
    }

    public record ApiResponse(int status, HttpHeaders headers, JsonNode json, String raw, Duration elapsed) {

        public String header(String name) {
            return headers.firstValue(name).orElse(null);
        }

        /** String value at a top-level field, or null if absent/null. */
        public String field(String name) {
            JsonNode node = json.path(name);
            return node.isMissingNode() || node.isNull() ? null : node.asString();
        }

        @Override
        public String toString() {
            return "HTTP " + status + " " + raw;
        }
    }
}
