"""DroneDrill AI - Database Layer (SQLite).

Manages storage for trainees, training sessions, simulation events,
skill cells encountered, and scenario fingerprints.
"""

from pathlib import Path
import sqlite3
import json
import math
from typing import Optional, Set, Tuple, Any, List, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "dronedrill.db"


def get_db_path(custom_path: Optional[str] = None) -> Path:
    """Resolve database file path."""
    if custom_path:
        return Path(custom_path)
    return DEFAULT_DB_PATH


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Create and return a SQLite database connection with row factory."""
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. Trainees table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trainees (
            id TEXT PRIMARY KEY,
            name TEXT,
            is_demo INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    for col, col_type in [
        ("name", "TEXT"),
        ("is_demo", "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE trainees ADD COLUMN {col} {col_type};")
        except sqlite3.OperationalError:
            pass

    # 2. Sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            trainee_id TEXT NOT NULL,
            scenario_id TEXT NOT NULL,
            cell TEXT NOT NULL,
            difficulty_index REAL NOT NULL,
            scenario_json TEXT,
            overall_score REAL,
            mode TEXT DEFAULT 'practice',
            is_repeat INTEGER DEFAULT 0,
            fingerprint TEXT,
            scores_json TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(trainee_id) REFERENCES trainees(id)
        );
    """)

    # Alter table if schema was created previously
    for col, col_type in [
        ("scenario_json", "TEXT"),
        ("overall_score", "REAL"),
        ("mode", "TEXT DEFAULT 'practice'"),
        ("is_repeat", "INTEGER DEFAULT 0"),
        ("fingerprint", "TEXT"),
        ("scores_json", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE sessions ADD COLUMN {col} {col_type};")
        except sqlite3.OperationalError:
            pass

    # 3. Events table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            payload TEXT,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        );
    """)

    # 4. Skill cells table (tracks cells seen per trainee & skill factor levels)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skill_cells (
            trainee_id TEXT NOT NULL,
            cell TEXT NOT NULL,
            skill TEXT DEFAULT '',
            factor TEXT DEFAULT '',
            level TEXT DEFAULT '',
            alpha REAL DEFAULT 1.0,
            beta REAL DEFAULT 1.0,
            n INTEGER DEFAULT 0,
            seen_count INTEGER DEFAULT 1,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trainee_id, cell),
            FOREIGN KEY(trainee_id) REFERENCES trainees(id)
        );
    """)

    for col, col_type in [
        ("skill", "TEXT DEFAULT ''"),
        ("factor", "TEXT DEFAULT ''"),
        ("level", "TEXT DEFAULT ''"),
        ("alpha", "REAL DEFAULT 1.0"),
        ("beta", "REAL DEFAULT 1.0"),
        ("n", "INTEGER DEFAULT 0"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE skill_cells ADD COLUMN {col} {col_type};")
        except sqlite3.OperationalError:
            pass

    # 5. Scenario fingerprints table (for deduplication / repeated detection)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scenario_fingerprints (
            fingerprint TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 6. Flight data table (MAVLink-style simulated telemetry)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flight_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            object_id TEXT NOT NULL,
            t REAL NOT NULL,
            x_m REAL NOT NULL,
            y_m REAL NOT NULL,
            alt_m REAL NOT NULL,
            speed_mps REAL NOT NULL,
            heading_deg REAL NOT NULL,
            source TEXT NOT NULL,
            ingest_ts TEXT,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_flight_data_session ON flight_data(session_id, object_id, t);")

    # Add t_s column to events if missing
    try:
        cursor.execute("ALTER TABLE events ADD COLUMN t_s REAL;")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


def record_trainee(
    trainee_id: str,
    name: Optional[str] = None,
    is_demo: int = 0,
    db_path: Optional[str] = None,
) -> None:
    """Ensure trainee is registered, optionally setting name and is_demo."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO trainees (id, name, is_demo)
        VALUES (?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = COALESCE(excluded.name, trainees.name),
            is_demo = CASE WHEN excluded.is_demo != 0 THEN excluded.is_demo ELSE trainees.is_demo END;
        """,
        (trainee_id, name, is_demo),
    )
    conn.commit()
    conn.close()


def get_all_trainees(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all trainees registered in the system."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, is_demo, created_at FROM trainees ORDER BY created_at ASC, id ASC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_demo_trainees(db_path: Optional[str] = None) -> int:
    """Idempotently remove all synthetic demo trainees and associated records."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM trainees WHERE is_demo = 1 OR id LIKE 'demo_%';")
    demo_ids = [r["id"] for r in cursor.fetchall()]
    if not demo_ids:
        conn.close()
        return 0

    placeholders = ",".join("?" for _ in demo_ids)
    cursor.execute(f"SELECT session_id FROM sessions WHERE trainee_id IN ({placeholders});", demo_ids)
    session_ids = [r["session_id"] for r in cursor.fetchall()]

    if session_ids:
        sess_placeholders = ",".join("?" for _ in session_ids)
        cursor.execute(f"DELETE FROM flight_data WHERE session_id IN ({sess_placeholders});", session_ids)
        cursor.execute(f"DELETE FROM events WHERE session_id IN ({sess_placeholders});", session_ids)

    cursor.execute(f"DELETE FROM sessions WHERE trainee_id IN ({placeholders});", demo_ids)
    cursor.execute(f"DELETE FROM skill_cells WHERE trainee_id IN ({placeholders});", demo_ids)
    cursor.execute(f"DELETE FROM trainees WHERE id IN ({placeholders});", demo_ids)

    conn.commit()
    conn.close()
    return len(demo_ids)


def record_session(
    session_id: str,
    trainee_id: str,
    scenario_id: str,
    cell: Any,
    difficulty_index: float,
    scenario_json: Optional[Any] = None,
    mode: str = "practice",
    is_repeat: int = 0,
    fingerprint: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Record a newly started training session, saving the scenario JSON for reloading."""
    cell_str = json.dumps(list(cell)) if not isinstance(cell, str) else cell
    scenario_payload = (
        json.dumps(scenario_json)
        if scenario_json is not None and not isinstance(scenario_json, str)
        else scenario_json
    )
    record_trainee(trainee_id, db_path=db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO sessions (session_id, trainee_id, scenario_id, cell, difficulty_index, scenario_json, mode, is_repeat, fingerprint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            session_id,
            trainee_id,
            scenario_id,
            cell_str,
            float(difficulty_index),
            scenario_payload,
            mode,
            int(is_repeat),
            fingerprint,
        ),
    )
    conn.commit()
    conn.close()


def get_session(session_id: str, db_path: Optional[str] = None) -> Optional[dict]:
    """Retrieve session details by session_id."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_id = ?;", (session_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    if data.get("scenario_json"):
        try:
            data["scenario"] = json.loads(data["scenario_json"])
        except Exception:
            data["scenario"] = None
    if data.get("scores_json"):
        try:
            data["scores"] = json.loads(data["scores_json"])
        except Exception:
            data["scores"] = None
    else:
        data["scores"] = None
    return data


def update_session_score(
    session_id: str,
    overall_score: Optional[float],
    scores_dict: Optional[Any] = None,
    db_path: Optional[str] = None,
) -> None:
    """Update overall score and detailed scores on an existing session."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        score_val = float(overall_score) if overall_score is not None else 0.0
        if not math.isfinite(score_val):
            score_val = 0.0
    except (ValueError, TypeError):
        score_val = 0.0

    if scores_dict is not None:
        scores_str = json.dumps(scores_dict) if not isinstance(scores_dict, str) else scores_dict
        cursor.execute(
            "UPDATE sessions SET overall_score = ?, scores_json = ? WHERE session_id = ?;",
            (score_val, scores_str, session_id),
        )
    else:
        cursor.execute(
            "UPDATE sessions SET overall_score = ? WHERE session_id = ?;",
            (score_val, session_id),
        )
    conn.commit()
    conn.close()


def record_cell_seen(
    trainee_id: str,
    cell: Any,
    db_path: Optional[str] = None,
) -> None:
    """Record that a trainee has encountered a specific condition cell."""
    cell_str = json.dumps(list(cell)) if not isinstance(cell, str) else cell
    record_trainee(trainee_id, db_path=db_path)

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO skill_cells (trainee_id, cell, seen_count, last_seen)
        VALUES (?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(trainee_id, cell) DO UPDATE SET
            seen_count = seen_count + 1,
            last_seen = CURRENT_TIMESTAMP;
        """,
        (trainee_id, cell_str),
    )
    conn.commit()
    conn.close()


def get_seen_cells(trainee_id: str, db_path: Optional[str] = None) -> Set[Tuple[str, ...]]:
    """Fetch all unique condition cells seen by a trainee."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT cell FROM skill_cells WHERE trainee_id = ? AND (skill IS NULL OR skill = '');",
        (trainee_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    seen: Set[Tuple[str, ...]] = set()
    for row in rows:
        cell_raw = row["cell"]
        try:
            parsed = json.loads(cell_raw)
            seen.add(tuple(parsed))
        except Exception:
            seen.add(tuple(cell_raw.split(":")))
    return seen


def has_trainee_seen_fingerprint(
    trainee_id: str,
    fingerprint: str,
    db_path: Optional[str] = None,
) -> bool:
    """Check if a trainee has encountered this scenario fingerprint in a prior session."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM sessions WHERE trainee_id = ? AND fingerprint = ? LIMIT 1;",
        (trainee_id, fingerprint),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def count_practice_sessions(trainee_id: str, db_path: Optional[str] = None) -> int:
    """Return count of practice sessions started/completed by a trainee."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM sessions WHERE trainee_id = ? AND (mode = 'practice' OR mode IS NULL);",
        (trainee_id,),
    )
    row = cursor.fetchone()
    count = row["cnt"] if row else 0
    conn.close()
    return int(count)


def get_trainee_sessions(
    trainee_id: str,
    mode: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[dict]:
    """Retrieve all sessions for a trainee, optionally filtered by mode."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    if mode:
        cursor.execute(
            "SELECT * FROM sessions WHERE trainee_id = ? AND mode = ? ORDER BY started_at ASC, ROWID ASC;",
            (trainee_id, mode),
        )
    else:
        cursor.execute(
            "SELECT * FROM sessions WHERE trainee_id = ? ORDER BY started_at ASC, ROWID ASC;",
            (trainee_id,),
        )
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("scores_json"):
            try:
                d["scores"] = json.loads(d["scores_json"])
            except Exception:
                d["scores"] = None
        else:
            d["scores"] = None
        results.append(d)
    return results


def has_fingerprint(fingerprint: str, db_path: Optional[str] = None) -> bool:
    """Check if a scenario fingerprint already exists in the database."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM scenario_fingerprints WHERE fingerprint = ? LIMIT 1;",
        (fingerprint,),
    )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def record_fingerprint(
    fingerprint: str,
    scenario_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Record a fingerprint. Returns True if new, False if it was already recorded."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO scenario_fingerprints (fingerprint, scenario_id) VALUES (?, ?);",
            (fingerprint, scenario_id),
        )
        conn.commit()
        inserted = True
    except sqlite3.IntegrityError:
        inserted = False
    finally:
        conn.close()
    return inserted


def record_event(
    session_id: str,
    event_type: str,
    payload: Optional[Any] = None,
    t_s: Optional[float] = None,
    db_path: Optional[str] = None,
) -> None:
    """Record a simulation event in the events table, storing simulation time t_s."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if t_s is None and isinstance(payload, dict):
        raw_val = payload.get("detect_time_s")
        if raw_val is None:
            raw_val = payload.get("t_s", 0.0)
        try:
            t_s = float(raw_val) if raw_val is not None else 0.0
        except (ValueError, TypeError):
            t_s = 0.0
    elif t_s is None:
        t_s = 0.0

    try:
        t_s = float(t_s)
        if not math.isfinite(t_s) or t_s < 0:
            t_s = 0.0
    except (ValueError, TypeError):
        t_s = 0.0

    payload_dict = dict(payload) if isinstance(payload, dict) else payload
    if isinstance(payload_dict, dict) and "t_s" not in payload_dict:
        payload_dict["t_s"] = float(t_s)

    payload_str = json.dumps(payload_dict) if payload_dict is not None and not isinstance(payload_dict, str) else payload_dict
    cursor.execute(
        "INSERT INTO events (session_id, event_type, payload, t_s) VALUES (?, ?, ?, ?);",
        (session_id, event_type, payload_str, float(t_s)),
    )
    conn.commit()
    conn.close()


def get_events(session_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all interaction events for a session ordered chronologically by simulation time."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM events WHERE session_id = ? ORDER BY t_s ASC, timestamp ASC;",
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        if d.get("payload"):
            try:
                d["payload_data"] = json.loads(d["payload"])
            except Exception:
                d["payload_data"] = None
        else:
            d["payload_data"] = None
        result.append(d)
    return result


# Initialize database automatically on module import
init_db()
