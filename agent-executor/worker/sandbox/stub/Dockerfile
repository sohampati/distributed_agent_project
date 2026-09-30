# Stand-in for a real coding agent: makes a deterministic edit so the sandbox pipeline can be tested
# end to end without an LLM. The worker runs it with no network, a read-only root filesystem and a non-root user.
FROM alpine:3.20
COPY agent.sh /usr/local/bin/agent
RUN chmod 755 /usr/local/bin/agent
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/agent"]
