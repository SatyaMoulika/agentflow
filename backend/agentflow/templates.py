"""Deterministic generation adapter; templates are exported from the shared TS fixtures."""
import json
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .models import Workflow, now

SEED = json.loads(Path(__file__).with_name('seed.json').read_text())
REGISTRY = {item['type']: item for item in SEED['registry']}


def uid(prefix: str) -> str:
    return f'{prefix}_{uuid4().hex[:12]}'


def generate(prompt: str) -> dict:
    patterns = [('invoice', r'\binvoices?\b'), ('email', r'\b(?:e-?mails?|inbox)\b'),
                ('support', r'\b(?:support|tickets?)\b'), ('csv', r'\bcsv\b'),
                ('document', r'\bdocuments?\b'), ('lead', r'\bleads?\b'),
                ('report', r'\b(?:reports?|performance)\b')]
    fixture = next((name for name, pattern in patterns if re.search(pattern, prompt, re.I)), None)
    if fixture is None:
        raise HTTPException(422, 'Supported templates: invoice, email, support ticket, CSV, document, '
                            'lead and daily report. Arbitrary AI generation is not enabled.')
    identifier = 'document' if fixture == 'csv' else fixture
    workflow = deepcopy(next(w for w in SEED['workflows'] if w['id'] == f'wf_{identifier}'))
    workflow.update(id=uid('wf'), version=1, status='draft', createdAt=now(), updatedAt=now(),
                    totalRuns=0, successRate=0)
    workflow.pop('lastRun', None)
    chain = None
    if fixture == 'csv':
        chain = ['manual', 'parser', 'llm', 'end']
        workflow.update(name='CSV Analysis Pipeline', icon='document',
                        description='Parse CSV records and produce a structured demo summary.')
    if fixture == 'email' and re.search(r'summari[sz]|summar(?:y|ies)', prompt, re.I):
        chain = ['manual', 'llm', 'classify', 'http', 'end']
        workflow.update(name='Email Summary & Classification',
                        description='Summarize and classify incoming messages using demo steps.')
    if chain:
        workflow['nodes'] = [dict(id=uid('node'), type=kind, label=REGISTRY[kind]['name'],
                                  position={'x': index*300, 'y': 150},
                                  config=deepcopy(REGISTRY[kind]['defaultConfig']))
                             for index, kind in enumerate(chain)]
        workflow['edges'] = [dict(id=uid('edge'), source=source['id'], target=target['id'])
                             for source, target in zip(workflow['nodes'], workflow['nodes'][1:])]
        if fixture == 'email':
            workflow['nodes'][1]['label'] = 'Summarize email'
            workflow['nodes'][1]['config']['prompt'] = 'Summarize the incoming email in three bullets.'
    integrations = []
    if any(node['type'] in {'llm', 'extract', 'classify', 'agent'} for node in workflow['nodes']):
        integrations.append('AI provider (simulated)')
    if any(node['type'] == 'http' for node in workflow['nodes']):
        integrations.append('HTTP tool (simulated)')
    return {'ok': True, 'workflow': Workflow.model_validate(workflow).json_data(),
            'fixture': fixture, 'requiredIntegrations': integrations,
            'configurationNotes': ['Generated from a supported template on the local backend.',
                                   'AI and external tool steps are simulated; no provider is called.',
                                   'Review prompts, conditions, and approval routes before running.']}
