import { describe, expect, it } from 'vitest';
import { githubEndpoint } from '../src/api/github';

describe('GitHub connection endpoint', () => {
  it('builds an API endpoint for the chosen repository and list', () => {
    expect(githubEndpoint('SatyaMoulika', 'agentflow', 'issues')).toBe(
      'https://api.github.com/repos/SatyaMoulika/agentflow/issues',
    );
    expect(githubEndpoint('octocat', 'hello-world', 'pulls')).toBe(
      'https://api.github.com/repos/octocat/hello-world/pulls',
    );
  });

  it('rejects path manipulation and invalid owners', () => {
    for (const [owner, repository] of [
      ['owner/other', 'repo'],
      ['owner', '../private'],
      ['owner', '..'],
      ['owner', 'repo?token=x'],
      ['-owner', 'repo'],
    ]) {
      expect(githubEndpoint(owner, repository, 'issues')).toBeNull();
    }
  });
});
