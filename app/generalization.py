"""DroneDrill AI - Generalization and Rote Metrics.

Calculates:
1. Generalization Score: Test session performance against difficulty-matched practice performance.
2. Rote Indicator: Performance gap between repeated-fingerprint and novel practice sessions.
"""

from typing import Any, Dict, Optional
import numpy as np

from app.db import get_trainee_sessions


def _safe_float(val: Any, default: float = 0.5) -> float:
    try:
        f = float(val) if val is not None else default
        return f if np.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def generalization_score(
    trainee_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Evaluate trainee generalization by comparing test sessions against difficulty-matched practice sessions.
    
    Returns:
        {score, n_test, n_matched, note}
        score is null if fewer than 2 test sessions or 2 matched practice sessions exist.
    """
    test_sessions = get_trainee_sessions(trainee_id, mode="test", db_path=db_path)
    test_scored = [s for s in test_sessions if s.get("overall_score") is not None and np.isfinite(_safe_float(s.get("overall_score")))]

    practice_sessions = get_trainee_sessions(trainee_id, mode="practice", db_path=db_path)
    practice_scored = [s for s in practice_sessions if s.get("overall_score") is not None and np.isfinite(_safe_float(s.get("overall_score")))]

    n_test = len(test_scored)

    # Find practice sessions whose difficulty is within +-0.1 of any test session
    matched_practice = [
        p for p in practice_scored
        if any(abs(_safe_float(p.get("difficulty_index")) - _safe_float(t.get("difficulty_index"))) <= 0.1 for t in test_scored)
    ]
    n_matched = len(matched_practice)

    if n_test < 2 or n_matched < 2:
        return {
            "score": None,
            "n_test": n_test,
            "n_matched": n_matched,
            "note": "Insufficient data: requires at least 2 test sessions and 2 difficulty-matched practice sessions",
        }

    mean_test = float(np.mean([_safe_float(t.get("overall_score")) for t in test_scored]))
    mean_practice = float(np.mean([_safe_float(p.get("overall_score")) for p in matched_practice]))

    if mean_practice > 0:
        score = round(mean_test / mean_practice, 4)
    else:
        score = 1.0 if mean_test == 0.0 else round(mean_test, 4)

    return {
        "score": score,
        "n_test": n_test,
        "n_matched": n_matched,
        "note": "Generalization score successfully calculated",
    }


def rote_indicator(
    trainee_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Detect rote memorization by comparing repeated-fingerprint sessions to difficulty-matched novel sessions.
    
    Returns:
        {gap, n_repeat, n_novel, note}
        gap is null if fewer than 2 repeated or 2 novel matched practice sessions exist.
    """
    practice_sessions = get_trainee_sessions(trainee_id, mode="practice", db_path=db_path)
    practice_scored = [s for s in practice_sessions if s.get("overall_score") is not None and np.isfinite(_safe_float(s.get("overall_score")))]

    repeat_sessions = [s for s in practice_scored if s.get("is_repeat") == 1]
    novel_sessions = [s for s in practice_scored if not s.get("is_repeat")]

    n_repeat = len(repeat_sessions)

    # Match novel sessions within +-0.1 difficulty of any repeated session
    matched_novel = [
        n for n in novel_sessions
        if any(abs(_safe_float(n.get("difficulty_index")) - _safe_float(r.get("difficulty_index"))) <= 0.1 for r in repeat_sessions)
    ]
    n_novel = len(matched_novel)

    if n_repeat < 2 or n_novel < 2:
        return {
            "gap": None,
            "n_repeat": n_repeat,
            "n_novel": n_novel,
            "note": "Insufficient data: requires at least 2 repeated and 2 difficulty-matched novel practice sessions",
        }

    mean_repeat = float(np.mean([_safe_float(r.get("overall_score")) for r in repeat_sessions]))
    mean_novel = float(np.mean([_safe_float(n.get("overall_score")) for n in matched_novel]))
    gap = round(mean_repeat - mean_novel, 4)


    if gap > 0.15:
        note = "Significant performance gap on repeated scenarios indicates probable rote memorization"
    else:
        note = "Performance is consistent between repeated and novel scenarios"

    return {
        "gap": gap,
        "n_repeat": n_repeat,
        "n_novel": n_novel,
        "note": note,
    }
