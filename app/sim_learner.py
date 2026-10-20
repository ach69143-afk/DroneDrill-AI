"""DroneDrill AI - Synthetic Learner Simulation.

Provides SimLearner agent with ground-truth skill levels across condition factors
and configurable rote memorization bonuses for testing and validation.
Produces events directly and calls scoring.py without HTTP networking.
"""

import random
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import numpy as np

from app.factors import (
    CONDITION_FACTOR_NAMES,
    CLASS_MIX,
)
from app.generator import _coerce_rng
from app.scoring import score_session, load_decision_tree


class SimLearner:
    """Synthetic trainee with ground-truth latent skill per condition level.
    
    Attributes:
        base_skill: Default skill level (0.0 to 1.0).
        condition_skills: Map from (factor, level) or (skill, factor, level) to true skill (0.0 to 1.0).
        rote_bonus: Extra performance added on repeated scenario fingerprints.
        rng: Deterministic random generator.
    """

    def __init__(
        self,
        base_skill: float = 0.75,
        condition_skills: Optional[Dict[Tuple[str, ...], float]] = None,
        rote_bonus: float = 0.0,
        rng: Optional[Union[int, random.Random, np.random.Generator]] = None,
    ):
        self.base_skill = float(base_skill)
        self.condition_skills = condition_skills or {}
        self.rote_bonus = float(rote_bonus)
        self.rng = _coerce_rng(rng)
        self.seen_fingerprints: Set[str] = set()

    def get_skill_for_condition(self, factor: str, level: str, skill_name: Optional[str] = None) -> float:
        """Lookup ground truth skill for a factor level, optionally specific to a skill."""
        if skill_name and (skill_name, factor, level) in self.condition_skills:
            return self.condition_skills[(skill_name, factor, level)]
        if (factor, level) in self.condition_skills:
            return self.condition_skills[(factor, level)]
        return self.base_skill

    def evaluate_scenario(
        self,
        scenario: Dict[str, Any],
        is_repeat: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Generate trainee interaction events and compute session scores directly."""
        factors = scenario.get("factors", {})
        cell = scenario.get("cell", [])

        # Extract factor levels
        factor_values: Dict[str, str] = {}
        for idx, f_name in enumerate(CONDITION_FACTOR_NAMES):
            if f_name in factors:
                factor_values[f_name] = str(factors[f_name])
            elif idx < len(cell):
                factor_values[f_name] = str(cell[idx])
            else:
                factor_values[f_name] = "none"

        # Determine effective skill for this condition
        specific_skills = [
            self.get_skill_for_condition(f, factor_values[f])
            for f in CONDITION_FACTOR_NAMES
            if (f, factor_values[f]) in self.condition_skills
        ]
        if specific_skills:
            mean_cond_skill = float(np.mean(specific_skills))
        else:
            cond_skills = [
                self.get_skill_for_condition(f, factor_values[f])
                for f in CONDITION_FACTOR_NAMES
            ]
            mean_cond_skill = float(np.mean(cond_skills))

        # Check repeated fingerprint
        fp = scenario.get("fingerprint", "")
        if is_repeat is None:
            is_repeat = fp in self.seen_fingerprints
        if fp:
            self.seen_fingerprints.add(fp)

        effective_skill = mean_cond_skill + (self.rote_bonus if is_repeat else 0.0)
        effective_skill = float(np.clip(effective_skill, 0.05, 0.98))

        # Decision tree rules for response selection
        tree_data = load_decision_tree()
        rules = tree_data.get("rules", {})

        objects = scenario.get("objects", [])
        events: List[Dict[str, Any]] = []

        for obj in objects:
            true_cls = obj.get("true_class", "unknown")
            beh = obj.get("behaviour_label", "benign")
            true_threat = obj.get("true_threat_level", 1)

            # Detection event
            detected = self.rng.random() < effective_skill

            # Reaction time: slower and closer to limit_time when skill is low
            duration_s = float(scenario.get("duration_s", 60.0))
            diff = float(scenario.get("difficulty_index", 0.5))
            limit_time = 0.6 * duration_s * (1.0 + diff)
            time_frac = float(np.clip(1.0 - effective_skill + self.rng.uniform(-0.08, 0.08), 0.05, 0.95))
            detect_time_s = round(time_frac * limit_time, 2)

            # Classification
            if self.rng.random() < effective_skill:
                classified_as = true_cls
            else:
                other_classes = [c for c in CLASS_MIX if c != true_cls]
                classified_as = self.rng.choice(other_classes) if other_classes else true_cls

            # Threat level rating
            if classified_as == true_cls and self.rng.random() < effective_skill:
                threat_level_rated = true_threat
            else:
                threat_level_rated = self.rng.choice([0, 1, 2, 3])

            # Response choice
            rule_key = f"{true_cls}|{beh}"
            rule = rules.get(rule_key, {})
            responses = rule.get("responses", {"monitor": 1.0})

            if responses:
                sorted_resps = sorted(responses.items(), key=lambda x: x[1], reverse=True)
                best_resp = sorted_resps[0][0]
                worst_resp = sorted_resps[-1][0]
                if self.rng.random() < effective_skill:
                    response_chosen = best_resp
                else:
                    response_chosen = worst_resp
            else:
                response_chosen = "monitor"

            # Confidence assessment
            if classified_as == true_cls:
                conf = float(np.clip(effective_skill + self.rng.uniform(-0.05, 0.05), 0.5, 0.99))
            else:
                # Miscalibrated on errors
                conf = float(np.clip(0.65 + (1.0 - effective_skill) * 0.2 + self.rng.uniform(-0.05, 0.05), 0.4, 0.95))

            events.append(
                {
                    "object_id": obj["id"],
                    "detected": detected,
                    "detect_time_s": detect_time_s,
                    "classified_as": classified_as,
                    "threat_level_rated": threat_level_rated,
                    "response_chosen": response_chosen,
                    "confidence": round(conf, 2),
                }
            )

        # False alarms: lower false alarms for higher skill
        noise_windows = int(scenario.get("noise_windows", 3))
        fa_prob = float(np.clip((1.0 - effective_skill) * 0.6, 0.0, 0.9))
        false_alarms = 0
        for _ in range(noise_windows):
            if self.rng.random() < fa_prob:
                false_alarms += 1

        self.last_events = events
        self.last_false_alarms = false_alarms

        return score_session(scenario=scenario, events=events, false_alarms=false_alarms)
