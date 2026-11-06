"""Authoritative graph validation, independent of the frontend checks."""
import json
from collections import Counter, deque
from urllib.parse import urlparse

from .models import Workflow

AI_TYPES = {'llm', 'classify', 'extract', 'agent'}
OUTPUTS = {'condition': ['true', 'false'], 'approval': ['approved', 'rejected'], 'end': []}
OPERATORS = {'greater_than', 'less_than', 'equals', 'not_equals', 'contains'}


def validate_workflow(workflow: Workflow) -> list[dict]:
    issues: list[dict] = []

    def issue(message, node=None, field=None):
        issues.append({k: v for k, v in {
            'message': message, 'nodeId': node.id if node else None, 'field': field
        }.items() if v is not None})

    nodes = {node.id: node for node in workflow.nodes}
    if len(nodes) != len(workflow.nodes):
        issue('Each node must have a unique ID.')
    if len({edge.id for edge in workflow.edges}) != len(workflow.edges):
        issue('Each connection must have a unique ID.')
    triggers = [node for node in workflow.nodes if node.type == 'manual']
    if len(triggers) != 1:
        issue('A workflow needs exactly one manual trigger.')
    if not any(node.type == 'end' for node in workflow.nodes):
        issue('Add an End node to finish the workflow.')
    adjacency: dict[str, list[str]] = {key: [] for key in nodes}
    degrees = dict.fromkeys(nodes, 0)
    handles = Counter()
    for edge in workflow.edges:
        source, target = nodes.get(edge.source), nodes.get(edge.target)
        if not source or not target:
            issue('A connection points to a missing node.')
            continue
        handle = edge.source_handle or 'default'
        handles[(source.id, handle)] += 1
        if handle not in OUTPUTS.get(source.type, ['default']):
            issue('This connection uses an invalid output handle.', source)
        if handles[(source.id, handle)] > 1:
            issue('Each output can connect to one next step.', source)
        if target.type in {'manual', 'webhook', 'schedule'}:
            issue('Triggers cannot have incoming connections.', target)
        adjacency[source.id].append(target.id)
        degrees[target.id] += 1
    queue = deque(key for key, count in degrees.items() if count == 0)
    visited = 0
    while queue:
        key = queue.popleft()
        visited += 1
        for target in adjacency[key]:
            degrees[target] -= 1
            if degrees[target] == 0:
                queue.append(target)
    if visited != len(nodes):
        issue('This graph contains a cycle.')
    reachable = set()
    queue = deque(node.id for node in triggers)
    while queue:
        key = queue.popleft()
        if key in reachable:
            continue
        reachable.add(key)
        queue.extend(adjacency[key])
    for node in workflow.nodes:
        config = node.config
        if not node.label.strip():
            issue('Give this node a name.', node, 'label')
        if node.type in {'webhook', 'schedule'}:
            issue('This trigger is coming soon; use a manual trigger.', node)
        if node.id not in reachable:
            issue('Connect this node to the trigger.', node)
        for output in OUTPUTS.get(node.type, ['default']):
            if not handles[(node.id, output)]:
                issue(f'Connect the {output} output to the next step.', node)
        required = []
        if node.type in AI_TYPES:
            required = ['model', 'prompt']
        elif node.type == 'condition':
            required = ['variable', 'operator', 'value']
            if config.operator and config.operator not in OPERATORS:
                issue('Select a supported comparison operator.', node, 'operator')
        elif node.type == 'approval':
            required = ['title', 'approver']
        elif node.type in {'transform', 'calculator'}:
            required = ['expression']
        elif node.type == 'http':
            required = ['url']
            parsed = urlparse(config.url or '')
            if config.url and (parsed.scheme not in {'http', 'https'} or not parsed.netloc):
                issue('Enter an http:// or https:// URL.', node, 'url')
            for field in ['headers', 'body']:
                value = getattr(config, field)
                if value and '{{' not in value:
                    try:
                        json.loads(value)
                    except ValueError:
                        issue('Enter valid JSON or an input mapping.', node, field)
        for field in required:
            if not str(getattr(config, field) or '').strip():
                issue(f'{field.replace("_", " ").capitalize()} is required.', node, field)
        if config.output_schema:
            try:
                json.loads(config.output_schema)
            except ValueError:
                issue('Output schema must be valid JSON.', node, 'outputSchema')
    return issues
