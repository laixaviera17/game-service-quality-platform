from __future__ import annotations

from sqlalchemy import text

from .database import connect, initialize_database


def list_pending_outbox_orders(run_id: int) -> list[str]:
    """Return pending outbox order ids for a reliability run.

    In this lab, experiment runners and Celery poller tasks call this query.
    There is no separate production sweeper, dead-letter queue, or timed retry
    policy — those are intentionally out of scope.
    """
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            text(
                """SELECT o.order_id FROM delivery_outbox_events e
                JOIN delivery_orders o ON o.order_id = e.order_id
                WHERE o.run_id = :run_id AND e.status = 'pending'
                ORDER BY e.event_id"""
            ),
            {"run_id": run_id},
        ).scalars().all()
    return [str(order_id) for order_id in rows]
