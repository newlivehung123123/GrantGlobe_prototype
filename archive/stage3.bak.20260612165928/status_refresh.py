"""
Daily status recalculation job.

Transitions run in strict order within each execution:
  1. Upcoming → Open   (grant_opening_date has passed)
  2. Open    → Closed  (application_deadline has passed)

This ordering is critical: a grant whose opening date AND deadline have both passed
must end up as Closed in a single run. Reversing the order would leave it Open.

Only records with status_source = 'computed' are touched.
All date comparisons use CURRENT_DATE (DATE columns are timezone-independent in
PostgreSQL; UTC is enforced at the Python layer via datetime.now(timezone.utc).date()).
"""

import structlog
from datetime import datetime, timezone

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SQL — two sequential UPDATE statements in mandatory order
# ---------------------------------------------------------------------------

_UPCOMING_TO_OPEN_SQL = """
UPDATE grants
SET current_status = 'Open',
    updated_at     = NOW()
WHERE status_source   = 'computed'
  AND current_status  = 'Upcoming'
  AND grant_opening_date <= CURRENT_DATE
"""

_OPEN_TO_CLOSED_SQL = """
UPDATE grants
SET current_status = 'Closed',
    updated_at     = NOW()
WHERE status_source      = 'computed'
  AND current_status     = 'Open'
  AND application_deadline < CURRENT_DATE
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_status_refresh(conn) -> dict:
    """Execute both status transitions in mandatory order and commit.

    Step 1 — Upcoming → Open:
        Grants whose opening date has arrived are now accepting applications.

    Step 2 — Open → Closed:
        Grants whose application deadline has passed are now closed.

    The two-step ordering ensures that a grant whose opening date AND deadline
    have both passed in the same refresh cycle lands in 'Closed' (not 'Open').

    Only records with ``status_source = 'computed'`` are affected.
    Records with ``status_source = 'extracted'`` or ``'sentinel'`` are never
    touched by this job.

    Args:
        conn: Active psycopg2 connection.

    Returns:
        Dict with keys ``upcoming_to_open`` and ``open_to_closed`` counting
        the number of rows changed by each step.
    """
    with conn.cursor() as cur:
        # Step 1 — must run before Step 2
        cur.execute(_UPCOMING_TO_OPEN_SQL)
        upcoming_to_open: int = cur.rowcount

        # Step 2 — picks up records just promoted from Upcoming in Step 1
        cur.execute(_OPEN_TO_CLOSED_SQL)
        open_to_closed: int = cur.rowcount

    conn.commit()

    log.info(
        "status_refresh_complete",
        upcoming_to_open=upcoming_to_open,
        open_to_closed=open_to_closed,
    )

    return {
        "upcoming_to_open": upcoming_to_open,
        "open_to_closed": open_to_closed,
    }
