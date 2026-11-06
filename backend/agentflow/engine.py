"""Persistent, single-process orchestration with explicit deterministic provider adapters."""
import asyncio
import math
import re
from copy import deepcopy
from typing import Any

from .models import Execution, Workflow, now
from .repository import Repository
from .templates import uid
from .validation import AI_TYPES

TERMINAL = {'succeeded', 'failed', 'cancelled'}
INVOICE = {'invoice_number': 'INV-2026-1042', 'vendor': 'Acme Technologies',
           'amount': 60000, 'currency': 'INR', 'document': 'invoice_october.pdf'}


def condition(config: dict, data: dict) -> bool:
    left: Any = data
    for key in config.get('variable', 'amount').split('.'):
        left = left.get(key) if isinstance(left, dict) else None
    right = config.get('value', '')
    operator = config.get('operator')
    if operator == 'equals':
        return str(left) == right
    if operator == 'not_equals':
        return str(left) != right
    if operator == 'contains':
        return right in str(left if left is not None else '')
    try:
        if operator == 'greater_than':
            return float(left) > float(right)
        if operator == 'less_than':
            return float(left) < float(right)
    except (ValueError, TypeError):
        return False
    return False


def trigger_input(workflow: dict) -> dict:
    icon = workflow.get('icon')
    if 'CSV' in workflow['name']:
        return {'file': 'performance.csv', 'records': 42, 'revenue': 168000}
    return deepcopy({
        'email': {'from': 'customer@example.com', 'subject': 'Invoice question',
                  'body': 'Please help me understand the charges.'},
        'support': {'ticket_id': 'SUP-2041', 'message': 'Unable to access my workspace.'},
        'document': {'document': 'review.pdf', 'text': 'The team completed 42 projects.'},
        'lead': {'company': 'Acme Technologies', 'team_size': 35},
        'report': {'period': 'Last 24 hours', 'completed': 42, 'failed': 2},
    }.get(icon, INVOICE))


def execute_node(node: dict, data: dict) -> dict:
    """No network, eval, credentials, or real LLMs: providers remain replaceable adapters."""
    kind, config = node['type'], node['config']
    output = {**data, 'simulated': True}
    if kind == 'condition':
        output['matched'] = condition(config, data)
    elif kind == 'classify':
        output.update(category='billing', priority='normal', confidence=0.94)
    elif kind == 'extract':
        # Supplied execution input takes precedence over the demo invoice defaults.
        output = {**INVOICE, **output}
    elif kind == 'llm':
        output['summary'] = 'Simulated summary: review the supplied information and follow up.'
    elif kind == 'agent':
        output.update(recommendation='Route this item to the appropriate team.', score=84)
    elif kind == 'http':
        output.update(status_code=200, destination=config.get('url'))
    elif kind == 'parser':
        output.update(parsed=True, format='structured-text')
    elif kind == 'calculator':
        match = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*([+*/-])\s*(-?\d+(?:\.\d+)?)\s*',
                             config.get('expression', ''))
        if not match:
            raise ValueError('Demo calculator supports two numbers and one operator (+, -, *, /).')
        a, b = float(match[1]), float(match[3])
        operations = {'+': lambda: a+b, '-': lambda: a-b, '*': lambda: a*b, '/': lambda: a/b}
        try:
            value = operations[match[2]]()
        except ZeroDivisionError as error:
            raise ValueError('Cannot divide by zero.') from error
        if not math.isfinite(value):
            raise ValueError('Calculator result is not finite.')
        output['value'] = value
    return output


def event(execution: dict, message: str, node_id: str | None = None, level: str = 'info'):
    execution['events'].append({'id': uid('event'), 'timestamp': now(), 'message': message,
                                'level': level, **({'nodeId': node_id} if node_id else {})})


def new_execution(workflow: Workflow, data: dict | None = None) -> dict:
    graph = workflow.json_data()
    execution = {'id': uid('exec'), 'workflowId': workflow.id, 'workflowName': workflow.name,
                 'version': workflow.version, 'status': 'queued', 'startedAt': now(), 'duration': 0,
                 'trigger': 'Manual', 'traceId': uid('trace'), 'graph': graph,
                 'nodeRuns': [{'nodeId': node.id, 'status': 'pending', 'duration': 0,
                               'input': data if data is not None and node.type == 'manual' else {},
                               'output': None} for node in workflow.nodes], 'events': []}
    event(execution, 'Execution queued on the local backend. Provider steps are simulated.')
    # JSON null is kept for NodeRun.output because the frontend distinguishes absent output.
    return Execution.model_validate(execution).model_dump(mode='json', by_alias=True)


class Engine:
    def __init__(self, repository: Repository, step_delay: float = 0.25):
        self.repository = repository
        self.step_delay = step_delay
        self.tasks: dict[str, asyncio.Task] = {}
        self.closed = False

    def start(self, execution_id: str):
        existing = self.tasks.get(execution_id)
        if self.closed or (existing and not existing.done()):
            return
        self.tasks[execution_id] = asyncio.create_task(self.run(execution_id))
        self.tasks[execution_id].add_done_callback(lambda _: self.tasks.pop(execution_id, None))

    async def shutdown(self):
        self.closed = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, identifier: str):
        try:
            initial = self.repository.get('executions', identifier)
            if not initial or initial['status'] in TERMINAL | {'waiting_approval'}:
                return
            nodes = {node['id']: node for node in initial['graph']['nodes']}
            queue = [node['id'] for node in nodes.values() if node['type'] == 'manual']
            visited = set()
            while queue:
                node_id = queue.pop(0)
                if node_id in visited:
                    continue
                visited.add(node_id)
                node = nodes[node_id]
                with self.repository.transaction():
                    execution = self.repository.get('executions', identifier)
                    if not execution or execution['status'] in TERMINAL:
                        return
                    run = next(item for item in execution['nodeRuns'] if item['nodeId'] == node_id)
                    completed = run['status'] == 'succeeded'
                    if not completed:
                        predecessors = {edge['source'] for edge in execution['graph']['edges']
                                        if edge['target'] == node_id}
                        inputs = [item['output'] for item in execution['nodeRuns']
                                  if item['nodeId'] in predecessors and item['status'] == 'succeeded']
                        data = {}
                        for item in inputs:
                            data.update(item or {})
                        if not inputs:
                            data = run['input'] or trigger_input(execution['graph'])
                        run.update(status='running', startedAt=now(), attempt=1, retryCount=0,
                                   input=data)
                        execution['status'] = 'running'
                        event(execution, f'{node["label"]} started', node_id)
                        self.repository.put('executions', execution)
                if not completed:
                    await asyncio.sleep(self.step_delay)
                    with self.repository.transaction():
                        execution = self.repository.get('executions', identifier)
                        if not execution or execution['status'] in TERMINAL:
                            return
                        run = next(item for item in execution['nodeRuns']
                                   if item['nodeId'] == node_id)
                        if node['type'] == 'approval':
                            run['status'] = 'waiting_approval'
                            execution['status'] = 'waiting_approval'
                            event(execution, 'Approval requested. Execution paused.', node_id, 'warn')
                            self.repository.put('executions', execution)
                            self.repository.put('approvals', {
                                'id': uid('approval'), 'executionId': identifier,
                                'workflowId': execution['workflowId'],
                                'workflowName': execution['workflowName'], 'nodeId': node_id,
                                'title': node['config'].get('title') or 'Review workflow action',
                                'description': node['config'].get('description') or 'Review this step.',
                                'requestedAt': run['startedAt'], 'status': 'pending', 'risk': 'medium',
                                'data': run['input']})
                            return
                        duration = 890 if node['type'] in AI_TYPES else 120
                        try:
                            output = execute_node(node, run['input'])
                        except ValueError as error:
                            run.update(status='failed', endedAt=now(), duration=duration,
                                       error=str(error))
                            execution['duration'] += duration
                            execution['status'] = 'failed'
                            for item in execution['nodeRuns']:
                                if item['status'] == 'pending':
                                    item['status'] = 'skipped'
                            event(execution, str(error), node_id, 'error')
                            self.repository.put('executions', execution)
                            return
                        run.update(status='succeeded', endedAt=now(), duration=duration, output=output)
                        if node['type'] in AI_TYPES:
                            run['tokens'] = {'input': 1128, 'output': 286}
                        execution['duration'] += duration
                        event(execution, f'{node["label"]} completed ({duration}ms simulated).', node_id)
                        self.repository.put('executions', execution)
                edges = [edge for edge in execution['graph']['edges'] if edge['source'] == node_id]
                if node['type'] == 'condition':
                    branch = 'true' if condition(node['config'], run['input']) else 'false'
                    edges = [edge for edge in edges if edge.get('sourceHandle') == branch]
                elif node['type'] == 'approval':
                    edges = [edge for edge in edges
                             if edge.get('sourceHandle') == run['output'].get('decision')]
                queue.extend(edge['target'] for edge in edges)
            with self.repository.transaction():
                execution = self.repository.get('executions', identifier)
                if execution and execution['status'] not in TERMINAL | {'waiting_approval'}:
                    execution['status'] = 'succeeded'
                    for run in execution['nodeRuns']:
                        if run['status'] == 'pending':
                            run['status'] = 'skipped'
                    event(execution, 'Execution completed. All provider outputs were simulated.')
                    self.repository.put('executions', execution)
        except asyncio.CancelledError:
            # Lifespan shutdown leaves a durable checkpoint for the next startup.
            raise
        except Exception:
            with self.repository.transaction():
                execution = self.repository.get('executions', identifier)
                if execution and execution['status'] not in TERMINAL:
                    execution['status'] = 'failed'
                    for run in execution['nodeRuns']:
                        if run['status'] in {'pending', 'running'}:
                            run['status'] = 'skipped'
                    event(execution, 'The local runner encountered an internal error.', level='error')
                    self.repository.put('executions', execution)
            raise
