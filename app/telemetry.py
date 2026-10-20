"""DroneDrill AI - Simulated Telemetry Input Layer.

Provides a pluggable MAVLink-style telemetry packet architecture.
All telemetry data is strictly simulated and labelled as such. Real drone input
(Pixhawk/MAVLink) is NOT built; this layer provides the simulated ingestion adapter.
Never claims real MAVLink hardware support.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
PLACEHOLDER_LOG_PATH = BASE_DIR / "data" / "placeholder" / "flight_log_placeholder.json"


class Packet(BaseModel):
    """MAVLink-style telemetry packet representing single-point track state."""
    t: float = Field(..., description="Time in seconds from scenario start")
    object_id: str = Field(..., description="Target object identifier")
    x_m: float = Field(..., description="Local X position in metres from protected zone origin (0, 0)")
    y_m: float = Field(..., description="Local Y position in metres from protected zone origin (0, 0)")
    alt_m: float = Field(..., description="Altitude in metres above ground level")
    speed_mps: float = Field(..., description="Ground speed in metres per second")
    heading_deg: float = Field(..., description="Heading direction in degrees [0, 360)")
    source: str = Field("simulated", description="Telemetry origin: simulated | log_file")
    ingest_ts: Optional[str] = Field(None, description="ISO timestamp stamped by TelemetryAdapter during ingestion")


class TelemetrySource(ABC):
    """Abstract base class for telemetry ingestion sources."""

    @abstractmethod
    def packets(self, scenario: Dict[str, Any]) -> List[Packet]:
        """Generate or retrieve a list of telemetry packets for a scenario."""
        pass


class SimulatedSource(TelemetrySource):
    """Generates synthetic MAVLink-style telemetry packets at 5 Hz.
    
    Deterministic per scenario (seeded by scenario fingerprint).
    Models straight, loiter, erratic, parallel, and converging motion patterns
    with class-appropriate speed limits.
    """

    def __init__(self, sample_rate_hz: float = 5.0):
        self.sample_rate_hz = float(sample_rate_hz)
        self.dt = 1.0 / self.sample_rate_hz

    def packets(self, scenario: Dict[str, Any]) -> List[Packet]:
        """Generate 5 Hz packets for all scenario objects from t=0 to scenario duration."""
        fingerprint = scenario.get("fingerprint", "default_fp")
        seed_int = int(hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed_int)

        duration_s = float(scenario.get("duration_s", 60.0))
        num_steps = int(duration_s * self.sample_rate_hz)

        objects = scenario.get("objects", [])
        factors = scenario.get("factors", {})
        default_motion = factors.get("motion_pattern", "straight")

        all_packets: List[Packet] = []

        for obj in objects:
            obj_id = obj.get("id", "obj_unknown")
            true_cls = obj.get("true_class", "unknown")
            motion = obj.get("motion_pattern", default_motion)

            start_pos = obj.get("start_position", [1000.0, 1000.0, 100.0])
            base_vel = obj.get("velocity", [-15.0, -15.0, 0.0])

            x0, y0, z0 = float(start_pos[0]), float(start_pos[1]), float(start_pos[2])
            vx0, vy0, vz0 = float(base_vel[0]), float(base_vel[1]), float(base_vel[2])

            # Class-appropriate speed adjustments
            if true_cls == "balloon":
                speed_cap = rng.uniform(2.0, 5.0)
            elif true_cls == "bird":
                speed_cap = rng.uniform(8.0, 14.0)
            elif true_cls == "light_aircraft":
                speed_cap = rng.uniform(40.0, 70.0)
            else:  # multirotor, fixed_wing_uav, unknown
                speed_cap = rng.uniform(15.0, 45.0)

            # Object seed for deterministic trajectory variations
            obj_seed = int(hashlib.md5(f"{fingerprint}_{obj_id}".encode("utf-8")).hexdigest()[:8], 16)
            obj_rng = random.Random(obj_seed)

            # Pre-compute motion parameters
            radius = obj_rng.uniform(150.0, 300.0)
            omega = (speed_cap / radius) if radius > 0 else 0.05
            lane_offset = obj_rng.uniform(-100.0, 100.0)

            cur_x, cur_y, cur_z = x0, y0, z0

            for step in range(num_steps):
                t = round(step * self.dt, 2)

                if motion == "straight":
                    # Linear translation along base velocity
                    cur_x = x0 + vx0 * t
                    cur_y = y0 + vy0 * t
                    cur_z = max(10.0, z0 + vz0 * t)
                    heading = (math.degrees(math.atan2(vx0, vy0)) + 360.0) % 360.0
                    spd = math.hypot(vx0, vy0)

                elif motion == "loiter":
                    # Slow orbital circle around starting area
                    angle = omega * t
                    cur_x = x0 + radius * math.cos(angle)
                    cur_y = y0 + radius * math.sin(angle)
                    cur_z = max(10.0, z0 + math.sin(t * 0.1) * 5.0)
                    heading = (math.degrees(angle + math.pi / 2.0) + 360.0) % 360.0
                    spd = speed_cap

                elif motion == "erratic":
                    # Random seeded jitter along base velocity path
                    jitter_x = math.sin(t * 1.5 + obj_seed % 10) * 35.0
                    jitter_y = math.cos(t * 1.8 + obj_seed % 7) * 35.0
                    cur_x = x0 + vx0 * t + jitter_x
                    cur_y = y0 + vy0 * t + jitter_y
                    cur_z = max(10.0, z0 + math.sin(t * 0.5) * 15.0)
                    inst_vx = vx0 + 1.5 * math.cos(t * 1.5 + obj_seed % 10) * 35.0
                    inst_vy = vy0 - 1.8 * math.sin(t * 1.8 + obj_seed % 7) * 35.0
                    heading = (math.degrees(math.atan2(inst_vx, inst_vy)) + 360.0) % 360.0
                    spd = min(speed_cap * 1.3, math.hypot(inst_vx, inst_vy))

                elif motion == "parallel":
                    # Parallel lane offset
                    cur_x = x0 + lane_offset + vx0 * t
                    cur_y = y0 + vy0 * t
                    cur_z = max(10.0, z0 + vz0 * t)
                    heading = (math.degrees(math.atan2(vx0, vy0)) + 360.0) % 360.0
                    spd = math.hypot(vx0, vy0)

                elif motion == "converging":
                    # Direct approach toward protected zone origin (0, 0)
                    dist_to_origin = math.hypot(cur_x, cur_y)
                    if dist_to_origin > 10.0:
                        dir_x = -cur_x / dist_to_origin
                        dir_y = -cur_y / dist_to_origin
                    else:
                        dir_x, dir_y = 0.0, 0.0
                    cur_x = cur_x + dir_x * speed_cap * self.dt
                    cur_y = cur_y + dir_y * speed_cap * self.dt
                    cur_z = max(10.0, z0 - (t / max(1.0, duration_s)) * (z0 * 0.3))
                    heading = (math.degrees(math.atan2(dir_x, dir_y)) + 360.0) % 360.0
                    spd = speed_cap

                else:
                    # Default straight translation
                    cur_x = x0 + vx0 * t
                    cur_y = y0 + vy0 * t
                    cur_z = max(10.0, z0 + vz0 * t)
                    heading = (math.degrees(math.atan2(vx0, vy0)) + 360.0) % 360.0
                    spd = speed_cap

                all_packets.append(
                    Packet(
                        t=t,
                        object_id=obj_id,
                        x_m=round(cur_x, 2),
                        y_m=round(cur_y, 2),
                        alt_m=round(cur_z, 2),
                        speed_mps=round(spd, 2),
                        heading_deg=round(heading, 2),
                        source="simulated",
                    )
                )

        return all_packets


class LogFileSource(TelemetrySource):
    """Reads recorded flight log JSON placeholder and maps onto scenario objects.
    
    Placeholder until a real flight log is provided.
    """

    def __init__(self, log_path: Optional[Path] = None, replay_object_id: Optional[str] = None):
        self.log_path = Path(log_path) if log_path else PLACEHOLDER_LOG_PATH
        self.replay_object_id = replay_object_id

    def packets(self, scenario: Dict[str, Any]) -> List[Packet]:
        """Load packets from flight log file and assign to scenario target object."""
        if not self.log_path.exists():
            return []

        with open(self.log_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_packets = data.get("packets", [])
        objects = scenario.get("objects", [])
        target_obj_id = self.replay_object_id or (objects[0]["id"] if objects else "obj_1")

        result: List[Packet] = []
        for p in raw_packets:
            result.append(
                Packet(
                    t=float(p["t"]),
                    object_id=target_obj_id,
                    x_m=float(p["x_m"]),
                    y_m=float(p["y_m"]),
                    alt_m=float(p["alt_m"]),
                    speed_mps=float(p["speed_mps"]),
                    heading_deg=float(p["heading_deg"]),
                    source="log_file",
                )
            )
        return result


class TelemetryAdapter:
    """Ingestion adapter that validates, filters, and standardizes telemetry streams.
    
    Never alters ground-truth class or threat labels.
    Applies light moving-average smoothing and drops corrupt/out-of-order packets.
    """

    @staticmethod
    def process(
        packets: List[Union[Packet, Dict[str, Any]]],
        window_size: int = 3,
    ) -> Dict[str, Any]:
        """Validate, smooth, and timestamp incoming telemetry packets.
        
        Returns:
            {"packets": List[Packet], "stats": Dict[str, Any]}
        """
        ingest_time = datetime.now(timezone.utc).isoformat()

        total_received = len(packets)
        valid_packets: List[Packet] = []
        dropped_count = 0
        drop_reasons: Dict[str, int] = {}

        last_t_per_object: Dict[str, float] = {}

        for raw_p in packets:
            # Coerce dict to Packet
            if isinstance(raw_p, dict):
                try:
                    pkt = Packet(**raw_p)
                except Exception:
                    dropped_count += 1
                    drop_reasons["schema_validation_error"] = drop_reasons.get("schema_validation_error", 0) + 1
                    continue
            elif isinstance(raw_p, Packet):
                pkt = raw_p
            else:
                dropped_count += 1
                drop_reasons["invalid_type"] = drop_reasons.get("invalid_type", 0) + 1
                continue

            # 1. Range validation
            if pkt.alt_m < 0.0 or pkt.speed_mps < 0.0:
                dropped_count += 1
                drop_reasons["out_of_range"] = drop_reasons.get("out_of_range", 0) + 1
                continue

            if abs(pkt.x_m) > 100000.0 or abs(pkt.y_m) > 100000.0:
                dropped_count += 1
                drop_reasons["spatial_boundary_exceeded"] = drop_reasons.get("spatial_boundary_exceeded", 0) + 1
                continue

            # 2. Non-decreasing timestamp validation per object
            obj_id = pkt.object_id
            if obj_id in last_t_per_object:
                if pkt.t < last_t_per_object[obj_id]:
                    dropped_count += 1
                    drop_reasons["timestamp_decreased"] = drop_reasons.get("timestamp_decreased", 0) + 1
                    continue
            last_t_per_object[obj_id] = pkt.t

            # 3. Unit normalization and timestamp stamping
            normalized_heading = round(float(pkt.heading_deg) % 360.0, 2)
            validated_pkt = Packet(
                t=round(float(pkt.t), 2),
                object_id=pkt.object_id,
                x_m=round(float(pkt.x_m), 2),
                y_m=round(float(pkt.y_m), 2),
                alt_m=round(float(pkt.alt_m), 2),
                speed_mps=round(float(pkt.speed_mps), 2),
                heading_deg=normalized_heading,
                source=pkt.source,
                ingest_ts=ingest_time,
            )
            valid_packets.append(validated_pkt)

        # 4. Moving-average smoothing per object (3-point window on coordinates)
        smoothed_packets: List[Packet] = []
        packets_by_obj: Dict[str, List[Packet]] = {}
        for p in valid_packets:
            packets_by_obj.setdefault(p.object_id, []).append(p)

        for obj_id, obj_pkts in packets_by_obj.items():
            for i, p in enumerate(obj_pkts):
                start_i = max(0, i - window_size + 1)
                window = obj_pkts[start_i : i + 1]
                avg_x = sum(w.x_m for w in window) / len(window)
                avg_y = sum(w.y_m for w in window) / len(window)
                avg_alt = sum(w.alt_m for w in window) / len(window)

                smoothed_packets.append(
                    Packet(
                        t=p.t,
                        object_id=p.object_id,
                        x_m=round(avg_x, 2),
                        y_m=round(avg_y, 2),
                        alt_m=round(avg_alt, 2),
                        speed_mps=p.speed_mps,
                        heading_deg=p.heading_deg,
                        source=p.source,
                        ingest_ts=p.ingest_ts,
                    )
                )

        # Re-sort chronologically by timestamp
        smoothed_packets.sort(key=lambda x: (x.t, x.object_id))

        stats = {
            "total_received": total_received,
            "valid_count": len(smoothed_packets),
            "dropped_count": dropped_count,
            "drop_reasons": drop_reasons,
            "ingest_timestamp": ingest_time,
        }

        return {
            "packets": smoothed_packets,
            "stats": stats,
        }
