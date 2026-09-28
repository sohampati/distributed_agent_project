package com.agentexecutor.api.error;

import com.agentexecutor.api.github.RepositoryValidationException;
import com.agentexecutor.api.task.TaskNotFoundException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Every error is an RFC 9457 problem document with a machine-readable {@code code}. Malformed JSON (400) and
 * unsupported content types (415) are handled by the base class.
 */
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    @ExceptionHandler(RepositoryValidationException.class)
    ResponseEntity<ProblemDetail> handleRepositoryValidation(RepositoryValidationException e) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(e.error().status(), e.getMessage());
        problem.setTitle(e.error().title());
        problem.setProperty("code", e.error().name());

        HttpHeaders headers = new HttpHeaders();
        e.retryAfter().ifPresent(retryAfter -> headers.set(HttpHeaders.RETRY_AFTER, String.valueOf(retryAfter.toSeconds())));
        return ResponseEntity.status(e.error().status()).headers(headers).body(problem);
    }

    @ExceptionHandler(TaskNotFoundException.class)
    ResponseEntity<ProblemDetail> handleTaskNotFound(TaskNotFoundException e) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, e.getMessage());
        problem.setTitle("Task not found");
        problem.setProperty("code", "TASK_NOT_FOUND");
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(problem);
    }

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(
            MethodArgumentNotValidException e, HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        // Report field names as clients sent them (repository_url), not as Java names (repositoryUrl).
        Map<String, String> errors = new LinkedHashMap<>();
        e.getBindingResult().getFieldErrors()
                .forEach(error -> errors.putIfAbsent(toSnakeCase(error.getField()), error.getDefaultMessage()));

        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatus.BAD_REQUEST, "Request validation failed");
        problem.setTitle("Invalid request");
        problem.setProperty("code", "VALIDATION_FAILED");
        problem.setProperty("errors", errors);
        return ResponseEntity.badRequest().headers(headers).body(problem);
    }

    /** Gives framework-generated errors (malformed JSON, 415, 405, ...) a {@code code} too, e.g. BAD_REQUEST. */
    @Override
    protected ResponseEntity<Object> handleExceptionInternal(
            Exception e, Object body, HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        // The base class may build the ProblemDetail itself, so add the code to whatever it returns.
        ResponseEntity<Object> response = super.handleExceptionInternal(e, body, headers, status, request);
        if (response != null && response.getBody() instanceof ProblemDetail problem
                && (problem.getProperties() == null || !problem.getProperties().containsKey("code"))) {
            HttpStatus resolved = HttpStatus.resolve(status.value());
            problem.setProperty("code", resolved != null ? resolved.name() : "HTTP_" + status.value());
        }
        return response;
    }

    private static String toSnakeCase(String field) {
        return field.replaceAll("([a-z0-9])([A-Z])", "$1_$2").toLowerCase();
    }
}
