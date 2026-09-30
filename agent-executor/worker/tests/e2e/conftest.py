"""E2E fixtures: the real Java API (jar) and the real worker process, sharing a dedicated database.

The database is agent_executor_e2e, never the real one: a running worker claims whatever is QUEUED.
The API's Flyway migrations create the schema on first start.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

from tests.helpers import ensure_database

WORKER_DIR = Path(__file__).resolve().parents[2]
API_DIR = WORKER_DIR.parent / "api-service"
API_JAR = API_DIR / "target" / "api-service-0.0.1-SNAPSHOT.jar"

E2E_DATABASE_URL = os.environ.get("WORKER_E2E_DATABASE_URL", "postgresql://postgres@localhost:5432/agent_executor_e2e")


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: dict

    def __str__(self) -> str:
        return f"HTTP {self.status} {self.body}"


class Api:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def post_task(self, repository_url: str, prompt: str) -> HttpResponse:
        body = json.dumps({"repository_url": repository_url, "prompt": prompt}).encode()
        return self._send(urllib.request.Request(
            self.base_url + "/tasks", data=body, method="POST", headers={"Content-Type": "application/json"}))

    def get_task(self, task_id: uuid.UUID | str) -> HttpResponse:
        return self._send(urllib.request.Request(f"{self.base_url}/tasks/{task_id}"))

    @staticmethod
    def _send(request: urllib.request.Request) -> HttpResponse:
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return HttpResponse(response.status, dict(response.headers), json.loads(response.read() or b"{}"))
        except urllib.error.HTTPError as e:  # 4xx/5xx: return it, tests assert on status
            return HttpResponse(e.code, dict(e.headers), json.loads(e.read() or b"{}"))


@dataclass
class WorkerRun:
    returncode: int
    output: dict  # the JSON line the worker prints on stdout
    stderr: str


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _jdbc_url(libpq_url: str) -> str:
    return "jdbc:" + libpq_url.replace("postgresql://postgres@", "postgresql://", 1)


@pytest.fixture(scope="session")
def e2e_database_url() -> str:
    ensure_database(E2E_DATABASE_URL)
    return E2E_DATABASE_URL


@pytest.fixture(scope="session")
def api(e2e_database_url: str, tmp_path_factory) -> Iterator[Api]:
    """Starts the API jar on a free port against the E2E database; stops it after the session."""
    if not API_JAR.exists():
        subprocess.run([str(API_DIR / "mvnw"), "-q", "-B", "-DskipTests", "package"], cwd=API_DIR, check=True)

    port = _free_port()
    log_path = tmp_path_factory.mktemp("api") / "api.log"
    env = {**os.environ, "DB_URL": _jdbc_url(e2e_database_url)}
    with open(log_path, "w") as log:
        process = subprocess.Popen(
            ["java", "-jar", str(API_JAR), f"--server.port={port}"], env=env, stdout=log, stderr=subprocess.STDOUT)
    client = Api(f"http://localhost:{port}")

    deadline = time.monotonic() + 60
    while True:
        if process.poll() is not None:
            pytest.fail(f"API exited during startup (code {process.returncode}); see {log_path}")
        try:
            if client.get_task(uuid.uuid4()).status == 404:  # up and answering
                break
        except OSError:
            pass
        if time.monotonic() > deadline:
            process.kill()
            pytest.fail(f"API did not start within 60s; see {log_path}")
        time.sleep(0.5)

    yield client

    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture
def db(e2e_database_url: str, api: Api) -> Iterator[psycopg.Connection]:
    """Connection to the E2E database, with tasks emptied before each test (after the API created the schema)."""
    with psycopg.connect(e2e_database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM tasks")
        yield conn


@pytest.fixture
def run_worker(e2e_database_url: str):
    """Runs ``python -m agent_worker --once`` as a separate process and parses its JSON output."""

    def _run(worker_id: str) -> WorkerRun:
        result = subprocess.run(
            [sys.executable, "-m", "agent_worker", "--once", "--worker-id", worker_id],
            # PYTHONPATH: on macOS uv marks .venv hidden and Python skips hidden .pth files, so the editable
            # install isn't always importable; point at the source directly.
            env={**os.environ, "DATABASE_URL": e2e_database_url, "PYTHONPATH": str(WORKER_DIR / "src")},
            capture_output=True, text=True, timeout=30,
        )
        lines = result.stdout.strip().splitlines()
        output = json.loads(lines[-1]) if lines else {}
        return WorkerRun(result.returncode, output, result.stderr)

    return _run
