package com.agentexecutor.api.github;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class GitHubRepoRefTest {

    @ParameterizedTest
    @CsvSource({
            "https://github.com/example/project,          example,   project",
            "https://github.com/example/project/,         example,   project",
            "https://github.com/example/project.git,      example,   project",
            "https://www.github.com/example/project,      example,   project",
            "HTTPS://GitHub.com/Example/Project,          Example,   Project",
            "'  https://github.com/example/project  ',    example,   project",
            "https://github.com/my-org/my_repo.v2,        my-org,    my_repo.v2",
            "https://github.com/a/b,                      a,         b",
    })
    void parsesValidUrls(String url, String owner, String name) {
        assertThat(GitHubRepoRef.parse(url)).isEqualTo(new GitHubRepoRef(owner, name));
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "http://github.com/example/project",               // not https
            "git@github.com:example/project.git",              // ssh form
            "https://gitlab.com/example/project",              // other host
            "https://github.com.evil.com/example/project",     // lookalike host
            "https://github.com/example",                      // no repo
            "https://github.com/",                             // no owner
            "https://github.com/example/project/tree/main",    // sub-path
            "https://github.com/example/project?tab=readme",   // query
            "https://github.com/example/project#readme",       // fragment
            "https://user:pass@github.com/example/project",    // credentials
            "https://github.com:8443/example/project",         // port
            "https://github.com/-example/project",             // owner starts with hyphen
            "https://github.com/exa--mple/project",            // owner double hyphen
            "https://github.com/example/pro ject",             // space
            "https://github.com/example/..",                   // dot-dot
            "not a url",
            "",
    })
    void rejectsInvalidUrls(String url) {
        assertThatThrownBy(() -> GitHubRepoRef.parse(url))
                .isInstanceOfSatisfying(RepositoryValidationException.class,
                        e -> assertThat(e.error()).isEqualTo(RepositoryError.INVALID_REPOSITORY_URL));
    }

    @Test
    void acceptsOwnerOf39Characters() {
        assertThat(GitHubRepoRef.parse("https://github.com/" + "a".repeat(39) + "/project").owner()).hasSize(39);
    }

    @Test
    void rejectsOwnerOf40Characters() {
        assertThatThrownBy(() -> GitHubRepoRef.parse("https://github.com/" + "a".repeat(40) + "/project"))
                .isInstanceOf(RepositoryValidationException.class);
    }
}
