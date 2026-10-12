"""Per-client order rate limit: a burst from one client is refused, not queued."""

from src.orders.order_rate_limit import OrderRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_the_limit_allows_count_orders_then_refuses_with_a_wait() -> None:
    # Arrange
    clock = FakeClock()
    limiter = OrderRateLimiter(count=2, window_s=600, clock=clock)

    # Act
    first = limiter.check("1.2.3.4")
    second = limiter.check("1.2.3.4")
    third = limiter.check("1.2.3.4")

    # Assert
    assert (first.allowed, second.allowed) == (True, True)
    assert third.allowed is False
    assert third.retry_after_s == 600


def test_the_window_slides_so_old_orders_stop_counting() -> None:
    # Arrange
    clock = FakeClock()
    limiter = OrderRateLimiter(count=1, window_s=600, clock=clock)
    limiter.check("1.2.3.4")

    # Act
    clock.now = 601.0
    again = limiter.check("1.2.3.4")

    # Assert
    assert again.allowed is True


def test_clients_are_limited_separately() -> None:
    # Arrange
    limiter = OrderRateLimiter(count=1, window_s=600, clock=FakeClock())
    limiter.check("1.2.3.4")

    # Act
    other = limiter.check("5.6.7.8")

    # Assert
    assert other.allowed is True
