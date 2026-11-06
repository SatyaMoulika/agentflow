"""Workflow persistence outcomes, independent of HTTP and SQLAlchemy."""


class WorkflowNotFoundError(Exception):
    def __init__(self) -> None:
        super().__init__("The requested workflow does not exist.")


class WorkflowStorageUnavailableError(Exception):
    """Workflow storage cannot currently service an operation."""


class WorkflowArchivedError(Exception):
    """Archived workflow metadata cannot be edited through this API."""


class WorkflowVersionConflictError(Exception):
    def __init__(self) -> None:
        super().__init__("The workflow version changed. Reload before saving.")
