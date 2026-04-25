class DomainException(Exception):
    pass

class InsufficientInventoryError(DomainException):
    def __init__(self, product_id: str, requested: int, available: int):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Product {product_id}: requested {requested}, available {available}"
        )

class InvalidOrderTransitionError(DomainException):
    pass

class EmptyOrderError(DomainException):
    pass

class OptimisticLockError(DomainException):
    """Raised when a concurrent transaction modified the same row.
    The caller should retry the operation with fresh data."""
    pass