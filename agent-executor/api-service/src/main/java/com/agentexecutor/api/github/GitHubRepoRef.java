package com.agentexecutor.api.github;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.regex.Pattern;

/**
 * An {@code owner/repo} pair parsed from a {@code https://github.com/owner/repo} URL. Only the syntax is checked
 * here; whether the repository exists is {@link RepositoryValidator}'s job.
 */
public record GitHubRepoRef(String owner, String name) {

    // GitHub usernames: alphanumerics and single hyphens, no leading/trailing hyphen, at most 39 characters.
    private static final Pattern OWNER = Pattern.compile("[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}");
    private static final Pattern NAME = Pattern.compile("[A-Za-z0-9._-]{1,100}");

    public static GitHubRepoRef parse(String url) {
        URI uri;
        try {
            uri = new URI(url.strip());
        } catch (URISyntaxException e) {
            throw invalid("'%s' is not a valid URL".formatted(url));
        }

        if (!"https".equalsIgnoreCase(uri.getScheme())) {
            throw invalid("Repository URL must use https");
        }
        String host = uri.getHost();
        if (host == null || !(host.equalsIgnoreCase("github.com") || host.equalsIgnoreCase("www.github.com"))) {
            throw invalid("Only github.com repositories are supported");
        }
        if (uri.getRawUserInfo() != null || uri.getPort() != -1 || uri.getRawQuery() != null || uri.getRawFragment() != null) {
            throw invalid("Repository URL must not contain credentials, a port, a query or a fragment");
        }

        String path = uri.getPath() == null ? "" : uri.getPath();
        if (path.endsWith("/")) {
            path = path.substring(0, path.length() - 1);
        }
        if (path.endsWith(".git")) {
            path = path.substring(0, path.length() - ".git".length());
        }
        String[] segments = path.startsWith("/") ? path.substring(1).split("/", -1) : new String[0];
        if (segments.length != 2) {
            throw invalid("Repository URL must look like https://github.com/{owner}/{repo}");
        }

        String owner = segments[0];
        String name = segments[1];
        if (!OWNER.matcher(owner).matches()) {
            throw invalid("'%s' is not a valid GitHub owner".formatted(owner));
        }
        if (!NAME.matcher(name).matches() || name.equals(".") || name.equals("..")) {
            throw invalid("'%s' is not a valid GitHub repository name".formatted(name));
        }
        return new GitHubRepoRef(owner, name);
    }

    public String fullName() {
        return owner + "/" + name;
    }

    private static RepositoryValidationException invalid(String detail) {
        return new RepositoryValidationException(RepositoryError.INVALID_REPOSITORY_URL, detail);
    }
}
