import { Link } from 'react-router-dom';
import { Button, LoadingSkeleton } from '../components/ui';
import { ApiError } from './client';
export function Pending() {
  return (
    <div className="api-panel">
      <LoadingSkeleton rows={3} />
    </div>
  );
}
export function Failure({ error, retry }: { error: unknown; retry?: () => void }) {
  const problem = error instanceof ApiError ? error : null;
  return (
    <div className="api-error" role="alert">
      <strong>
        {problem?.message ||
          (error instanceof Error ? error.message : 'This request could not be completed.')}
      </strong>
      {problem?.code === 'WORKFLOW_VERSION_CONFLICT' && (
        <p>
          Your unsaved changes are kept. Download your draft, then load the latest version to
          compare before saving.
        </p>
      )}
      {problem?.requestId && <small>Request ID: {problem.requestId}</small>}
      {problem?.location && (
        <Link to={problem.location.replace('/api/v1/runs/', '/executions/')}>
          Inspect the retained run
        </Link>
      )}
      {retry && (
        <Button type="button" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}
export function Pages({
  page,
  total,
  size,
  onChange,
}: {
  page: number;
  total: number;
  size: number;
  onChange: (page: number) => void;
}) {
  return (
    <div className="api-pagination">
      <span>
        {total} records · Page {page} of {Math.max(1, Math.ceil(total / size))}
      </span>
      <div className="api-actions">
        <Button disabled={page <= 1} onClick={() => onChange(page - 1)}>
          Previous
        </Button>
        <Button disabled={page * size >= total} onClick={() => onChange(page + 1)}>
          Next
        </Button>
      </div>
    </div>
  );
}
