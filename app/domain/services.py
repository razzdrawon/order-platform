from app.domain.exceptions import InsufficientInventoryError
from app.domain.models import InventoryItem, Order, OrderItem


class OrderReservationService:
    """
    Coordinates inventory reservation for an order.

    Responsibility: given an Order and a map of available inventory,
    attempt to reserve all items atomically. If any item fails,
    roll back all previously made reservations and re-raise.

    This class is pure domain logic — no DB, no framework dependencies.
    """

    def reserve(
        self,
        order: Order,
        inventory: dict[str, InventoryItem],  # keyed by str(product_id)
    ) -> None:
        """
        Reserve inventory for all items in the order.

        Raises:
            InsufficientInventoryError: if any product lacks available stock.
                All previously reserved items are rolled back before raising.
            KeyError: if a product_id in the order has no inventory entry.
        """
        reserved_so_far: list[tuple[InventoryItem, int]] = []

        for item in order.items:
            key = str(item.product_id)
            inv = inventory[key]  # raises KeyError if product not found

            try:
                inv.reserve(item.quantity)
                reserved_so_far.append((inv, item.quantity))
            except InsufficientInventoryError:
                # Roll back everything we already reserved
                for reserved_inv, reserved_qty in reserved_so_far:
                    reserved_inv.release(reserved_qty)
                raise

    def release(
        self,
        order: Order,
        inventory: dict[str, InventoryItem],  # keyed by str(product_id)
    ) -> None:
        """
        Release inventory reservations for all items in the order.
        Called when an order is cancelled.
        """
        for item in order.items:
            key = str(item.product_id)
            inv = inventory[key]
            inv.release(item.quantity)
