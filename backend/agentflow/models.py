"""Typed API contracts; camelCase JSON matches the existing TypeScript domain model."""
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

NodeType = Literal['manual', 'webhook', 'schedule', 'llm', 'classify', 'extract', 'agent',
                   'condition', 'transform', 'merge', 'end', 'http', 'calculator', 'parser', 'approval']
ExecutionStatus = Literal['queued', 'running', 'waiting_approval', 'succeeded', 'failed', 'cancelled']


def now() -> str:
    return datetime.now(UTC).isoformat().replace('+00:00', 'Z')


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra='forbid')

    def json_data(self) -> dict[str, Any]:
        return self.model_dump(mode='json', by_alias=True, exclude_none=True)


class Position(Model):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class NodeConfig(Model):
    description: str | None = Field(default=None, max_length=10000)
    model: str | None = Field(default=None, max_length=200)
    system_prompt: str | None = Field(default=None, max_length=50000)
    prompt: str | None = Field(default=None, max_length=50000)
    temperature: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    max_tokens: int | None = Field(default=None, ge=1, le=1000000)
    timeout: float | None = Field(default=None, ge=1, le=3600, allow_inf_nan=False)
    retries: int | None = Field(default=None, ge=0, le=10)
    input: str | None = Field(default=None, max_length=50000)
    output_schema: str | None = Field(default=None, max_length=50000)
    variable: str | None = Field(default=None, max_length=500)
    operator: str | None = Field(default=None, max_length=50)
    value: str | None = Field(default=None, max_length=10000)
    url: str | None = Field(default=None, max_length=4000)
    method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] | None = None
    headers: str | None = Field(default=None, max_length=10000)
    body: str | None = Field(default=None, max_length=50000)
    connection: str | None = Field(default=None, max_length=500)
    approver: str | None = Field(default=None, max_length=500)
    title: str | None = Field(default=None, max_length=1000)
    expiration: str | None = Field(default=None, max_length=200)
    expression: str | None = Field(default=None, max_length=10000)


class WorkflowNode(Model):
    id: str = Field(min_length=1, max_length=200)
    type: NodeType
    label: str = Field(max_length=300)
    position: Position
    config: NodeConfig = Field(default_factory=NodeConfig)


class WorkflowEdge(Model):
    id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    source_handle: str | None = Field(default=None, max_length=50)
    label: str | None = Field(default=None, max_length=200)


class Workflow(Model):
    id: str = Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default='', max_length=10000)
    status: Literal['draft', 'active', 'paused', 'archived'] = 'draft'
    version: int = Field(default=1, ge=1)
    nodes: list[WorkflowNode] = Field(default_factory=list, max_length=500)
    edges: list[WorkflowEdge] = Field(default_factory=list, max_length=1000)
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    total_runs: int = Field(default=0, ge=0)
    success_rate: float = Field(default=0, ge=0, le=100)
    last_run: str | None = None
    icon: str = Field(default='workflow', max_length=100)


class Tokens(Model):
    input: int = Field(ge=0)
    output: int = Field(ge=0)


class NodeRun(Model):
    node_id: str
    status: Literal['pending', 'running', 'succeeded', 'failed', 'waiting_approval', 'skipped']
    duration: int = Field(default=0, ge=0)
    attempt: int | None = None
    retry_count: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    tokens: Tokens | None = None


class ExecutionEvent(Model):
    id: str
    timestamp: str = Field(default_factory=now)
    message: str
    level: Literal['info', 'warn', 'error'] = 'info'
    node_id: str | None = None


class Execution(Model):
    id: str
    workflow_id: str
    workflow_name: str
    version: int
    status: ExecutionStatus
    started_at: str = Field(default_factory=now)
    duration: int = 0
    trigger: str = 'Manual'
    trace_id: str
    node_runs: list[NodeRun]
    events: list[ExecutionEvent]
    graph: Workflow


class Approval(Model):
    id: str
    execution_id: str
    workflow_id: str
    workflow_name: str
    node_id: str
    title: str
    description: str
    requested_at: str = Field(default_factory=now)
    status: Literal['pending', 'approved', 'rejected', 'expired'] = 'pending'
    risk: Literal['low', 'medium', 'high'] = 'medium'
    data: dict[str, Any]
    decision_at: str | None = None
    comment: str | None = None


class Integration(Model):
    id: str
    name: str
    description: str
    category: str
    icon: str
    color: str
    connected: bool = False
    connection_name: str | None = Field(default=None, max_length=300)


class Settings(Model):
    name: str = Field(default='Moulika', min_length=2, max_length=100)
    email: str = Field(default='moulika@example.com', max_length=320, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    theme: Literal['light', 'dark', 'system'] = 'light'
    model: str = Field(default='gpt-4.1-mini', min_length=1, max_length=200)
    temperature: float = Field(default=0.3, ge=0, le=2, allow_inf_nan=False)
    max_steps: int = Field(default=25, ge=1, le=100)
    timeout: int = Field(default=60, ge=5, le=3600)
    retries: int = Field(default=2, ge=0, le=10)
    concurrency: int = Field(default=5, ge=1, le=50)
    tracing: bool = True
    retention: Literal['7 days', '30 days', '90 days'] = '30 days'
    log_level: Literal['debug', 'info', 'warn', 'error'] = 'info'
    redaction: bool = True
    notify_failure: bool = True
    notify_approval: bool = True
    notify_completion: bool = False


class SaveWorkflow(Model):
    workflow: Workflow
    expected_version: int | None = Field(default=None, ge=1)


class GenerateRequest(Model):
    prompt: str = Field(min_length=15, max_length=10000)


class RunRequest(Model):
    workflow_id: str = Field(min_length=1, max_length=200)
    input: dict[str, Any] | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class DecideRequest(Model):
    decision: Literal['approved', 'rejected']
    comment: str | None = Field(default=None, max_length=1000)


class IntegrationUpdate(Model):
    connected: bool
    connection_name: str | None = Field(default=None, max_length=300)
