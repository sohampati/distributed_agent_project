package com.agentexecutor.api.github;

import org.springframework.stereotype.Component;

/**
 * Checks that a repository URL points at a GitHub repository this service can use, and returns its canonical URL.
 */
@Component
public class RepositoryValidator {

    private final GitHubClient gitHubClient;

    public RepositoryValidator(GitHubClient gitHubClient) {
        this.gitHubClient = gitHubClient;
    }

    /**
     * @return GitHub's canonical {@code html_url}, which resolves renames and normalizes case
     * @throws RepositoryValidationException if the URL is malformed or the repository cannot be used
     */
    public String validate(String repositoryUrl) {
        GitHubRepoRef ref = GitHubRepoRef.parse(repositoryUrl);
        GitHubRepository repository = gitHubClient.getRepository(ref);

        if (repository.disabled()) {
            throw new RepositoryValidationException(RepositoryError.REPOSITORY_DISABLED,
                    "Repository %s has been disabled by GitHub".formatted(repository.fullName()));
        }
        if (repository.archived()) {
            throw new RepositoryValidationException(RepositoryError.REPOSITORY_ARCHIVED,
                    "Repository %s is archived and read-only".formatted(repository.fullName()));
        }
        return repository.htmlUrl();
    }
}
