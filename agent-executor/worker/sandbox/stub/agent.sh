#!/bin/sh
# Stub agent. Input: the task prompt in $TASK_PROMPT, the repository checked out at /workspace.
# Output: changes to /workspace (the worker diffs them) and a log on stdout/stderr.
# Test hooks: "[stub:fail]" in the prompt exits 1; "[stub:sleep]" hangs (for timeout tests).
set -eu

case "$TASK_PROMPT" in
    *"[stub:fail]"*)
        echo "stub agent: failing as requested" >&2
        exit 1
        ;;
    *"[stub:sleep]"*)
        echo "stub agent: sleeping as requested"
        exec sleep 3600
        ;;
esac

cd /workspace
{
    echo "# Agent notes"
    echo
    echo "Task: $TASK_PROMPT"
} > AGENT_NOTES.md
echo "stub agent: wrote AGENT_NOTES.md"
