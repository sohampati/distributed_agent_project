package com.agentexecutor.api.github;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class RepositoryValidatorTest {

    private final GitHubClient gitHubClient = mock(GitHubClient.class);
    private final RepositoryValidator validator = new RepositoryValidator(gitHubClient);

    @Test
    void returnsCanonicalUrlFromGitHub() {
        when(gitHubClient.getRepository(new GitHubRepoRef("example", "project")))
                .thenReturn(new GitHubRepository("Example/Project", "https://github.com/Example/Project", false, false, false));

        assertThat(validator.validate("https://github.com/example/project.git"))
                .isEqualTo("https://github.com/Example/Project");
    }

    @Test
    void acceptsPrivateRepositoryWeCanSee() {
        when(gitHubClient.getRepository(any()))
                .thenReturn(new GitHubRepository("example/secret", "https://github.com/example/secret", true, false, false));

        assertThat(validator.validate("https://github.com/example/secret")).isEqualTo("https://github.com/example/secret");
    }

    @Test
    void rejectsArchivedRepository() {
        when(gitHubClient.getRepository(any()))
                .thenReturn(new GitHubRepository("example/old", "https://github.com/example/old", false, true, false));

        assertThatThrownBy(() -> validator.validate("https://github.com/example/old"))
                .isInstanceOfSatisfying(RepositoryValidationException.class,
                        e -> assertThat(e.error()).isEqualTo(RepositoryError.REPOSITORY_ARCHIVED));
    }

    @Test
    void rejectsDisabledRepository() {
        when(gitHubClient.getRepository(any()))
                .thenReturn(new GitHubRepository("example/gone", "https://github.com/example/gone", false, false, true));

        assertThatThrownBy(() -> validator.validate("https://github.com/example/gone"))
                .isInstanceOfSatisfying(RepositoryValidationException.class,
                        e -> assertThat(e.error()).isEqualTo(RepositoryError.REPOSITORY_DISABLED));
    }

    @Test
    void invalidUrlNeverCallsGitHub() {
        assertThatThrownBy(() -> validator.validate("https://gitlab.com/example/project"))
                .isInstanceOf(RepositoryValidationException.class);

        verifyNoInteractions(gitHubClient);
    }
}
