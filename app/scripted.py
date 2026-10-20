"""DroneDrill AI - Hand-Authored Scripted Scenarios Loader.

Loads hand-authored scenarios from data/scripted/*.json.
Ensures all scripted scenarios belong strictly to PRACTICE_CELLS.
Provides library retrieval and inspection for practice drills.
"""

from pathlib import Path
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.factors import PRACTICE_CELLS, HELD_OUT_CELLS

logger = logging.getLogger("dronedrill.scripted")

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTED_DIR = BASE_DIR / "data" / "scripted"

_SCRIPTED_CACHE: Dict[str, Dict[str, Any]] = {}


def load_scripted_scenarios(scripted_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load all scripted scenarios from JSON files in the scripted directory.
    
    Enforces that:
    1. Every scenario has title, description, and source == 'scripted'.
    2. Every scenario's condition cell is strictly in PRACTICE_CELLS.
    """
    target_dir = Path(scripted_dir) if scripted_dir else SCRIPTED_DIR
    scenarios: Dict[str, Dict[str, Any]] = {}

    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        return scenarios

    for json_path in sorted(target_dir.glob("*.json")):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read scripted scenario {json_path}: {e}")
            continue

        # Validation of required fields
        scen_id = data.get("scenario_id") or json_path.stem
        data["scenario_id"] = scen_id
        data["source"] = "scripted"

        assert "title" in data and data["title"], f"Scenario {scen_id} missing 'title'"
        assert "description" in data and data["description"], f"Scenario {scen_id} missing 'description'"
        assert "cell" in data, f"Scenario {scen_id} missing 'cell'"

        cell_tuple = tuple(data["cell"])
        assert len(cell_tuple) == 6, f"Scenario {scen_id} cell must contain 6 factors, got {len(cell_tuple)}"
        assert cell_tuple in PRACTICE_CELLS, (
            f"Scenario {scen_id} condition cell {cell_tuple} must be a PRACTICE cell. "
            f"It cannot be in HELD_OUT cells."
        )

        scenarios[scen_id] = data

    global _SCRIPTED_CACHE
    _SCRIPTED_CACHE = scenarios
    return scenarios


def get_scripted_scenarios(reload: bool = False) -> Dict[str, Dict[str, Any]]:
    """Retrieve dictionary of loaded scripted scenarios."""
    global _SCRIPTED_CACHE
    if not _SCRIPTED_CACHE or reload:
        load_scripted_scenarios()
    return _SCRIPTED_CACHE


def get_scripted_scenario(scripted_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single scripted scenario by ID."""
    scenarios = get_scripted_scenarios()
    return scenarios.get(scripted_id)


def list_scripted_library() -> List[Dict[str, Any]]:
    """Return summary list of scripted scenarios for client library view."""
    scenarios = get_scripted_scenarios()
    library = []
    for sid, s in scenarios.items():
        library.append(
            {
                "id": sid,
                "title": s.get("title", sid),
                "description": s.get("description", ""),
                "cell": s.get("cell", []),
                "difficulty_index": s.get("difficulty_index", 0.5),
                "object_count": len(s.get("objects", [])),
                "source": "scripted",
            }
        )
    return library
