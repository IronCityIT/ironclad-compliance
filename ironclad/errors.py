"""Every error the engine raises on purpose.

One base class so a caller can catch all engine faults, and specific subclasses
so the CLI can map a fault to a distinct exit code instead of a traceback.
"""


class IroncladError(Exception):
    """Base for every deliberate engine fault."""


class ValidationError(IroncladError):
    """Input did not satisfy a declared contract (manifest, framework, crosswalk)."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []

    def __str__(self) -> str:
        base = super().__str__()
        if not self.errors:
            return base
        return base + "\n  - " + "\n  - ".join(self.errors)


class FrameworkError(IroncladError):
    """A framework or crosswalk could not be loaded or resolved."""


class AuthorizationError(IroncladError):
    """The principal may not perform this action, or not in this tenant."""


class SelectionError(IroncladError):
    """An unknown module or empty module group was requested."""


class ExceptionWorkflowError(IroncladError):
    """A risk-acceptance state transition is not allowed."""


class AuditChainError(IroncladError):
    """The audit log's hash chain does not verify."""
