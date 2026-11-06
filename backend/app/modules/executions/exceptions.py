"""Static execution outcomes; never include user payloads or driver messages."""

from uuid import UUID


class ExecutionNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("The requested execution resource does not exist.")


class ExecutionConflictError(Exception):
    def __init__(self) -> None:
        super().__init__("Execution state changed or is incompatible with this operation.")


class InvalidExecutionDataError(Exception):
    def __init__(self) -> None:
        super().__init__("The execution result does not match the target state.")


class WorkflowNotExecutableError(Exception):
    def __init__(self) -> None:
        super().__init__("The saved version is not executable by the current runner.")


class ExecutionStorageUnavailableError(Exception):
    def __init__(self, run_id: UUID | None = None) -> None:
        self.run_id = run_id
        super().__init__("Execution storage is temporarily unavailable.")
