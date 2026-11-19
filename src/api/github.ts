const ownerPattern = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
const repositoryPattern = /^(?!\.{1,2}$)[A-Za-z0-9_.-]{1,100}$/;

export function githubEndpoint(owner: string, repository: string, resource: 'issues' | 'pulls') {
  if (!ownerPattern.test(owner) || !repositoryPattern.test(repository)) return null;
  return `https://api.github.com/repos/${owner}/${repository}/${resource}`;
}
