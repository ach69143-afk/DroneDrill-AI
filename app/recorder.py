"""DroneDrill AI - Flight Data Telemetry Recorder.

Persists and retrieves processed simulated telemetry packets in SQLite flight_data table.
"""

from typing import Any, Dict, List, Optional, Union
from app.db import get_connection
from app.telemetry import Packet


def record_telemetry(
    session_id: str,
    packets: List[Union[Packet, Dict[str, Any]]],
    db_path: Optional[str] = None,
) -> None:
    """Batch insert processed telemetry packets into flight_data table for a session."""
    if not packets:
        return

    conn = get_connection(db_path)
    cursor = conn.cursor()

    rows_to_insert = []
    for p in packets:
        if isinstance(p, Packet):
            rows_to_insert.append(
                (
                    session_id,
                    p.object_id,
                    float(p.t),
                    float(p.x_m),
                    float(p.y_m),
                    float(p.alt_m),
                    float(p.speed_mps),
                    float(p.heading_deg),
                    p.source,
                    p.ingest_ts,
                )
            )
        elif isinstance(p, dict):
            rows_to_insert.append(
                (
                    session_id,
                    p.get("object_id", "obj_unknown"),
                    float(p.get("t", 0.0)),
                    float(p.get("x_m", 0.0)),
                    float(p.get("y_m", 0.0)),
                    float(p.get("alt_m", 0.0)),
                    float(p.get("speed_mps", 0.0)),
                    float(p.get("heading_deg", 0.0)),
                    p.get("source", "simulated"),
                    p.get("ingest_ts"),
                )
            )

    cursor.executemany(
        """
        INSERT INTO flight_data (session_id, object_id, t, x_m, y_m, alt_m, speed_mps, heading_deg, source, ingest_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows_to_insert,
    )
    conn.commit()
    conn.close()


def get_telemetry(
    session_id: str,
    object_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve chronologically ordered telemetry packets for a session."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if object_id:
        cursor.execute(
            """
            SELECT session_id, object_id, t, x_m, y_m, alt_m, speed_mps, heading_deg, source, ingest_ts
            FROM flight_data
            WHERE session_id = ? AND object_id = ?
            ORDER BY t ASC;
            """,
            (session_id, object_id),
        )
    else:
        cursor.execute(
            """
            SELECT session_id, object_id, t, x_m, y_m, alt_m, speed_mps, heading_deg, source, ingest_ts
            FROM flight_data
            WHERE session_id = ?
            ORDER BY t ASC, object_id ASC;
            """,
            (session_id,),
        )

    rows = cursor.fetchall()
    conn.close()

    return [dict(r) for r in rows]
