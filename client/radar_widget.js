// DroneDrill AI - Radar Widget Component
// Draws abstract radar/compass scope in top-left of main canvas

class RadarWidget {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    if (!this.canvas) return;
    this.ctx = this.canvas.getContext('2d');
    this.maxRangeM = 3000; // 3 km radius coverage
    this.sweepAngle = 0;
  }

  render(activeObjects = [], simTime = 0, factors = {}, visibilityWindows = {}) {
    if (!this.canvas || !this.ctx) return;
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    const cx = w / 2;
    const cy = h / 2;
    const r = Math.min(cx, cy) - 6;

    // Clear background
    ctx.clearRect(0, 0, w, h);

    // Radar Dark Scope Background
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(14, 18, 26, 0.95)";
    ctx.fill();

    // Range Rings (muted slate)
    ctx.strokeStyle = "rgba(148, 163, 184, 0.20)";
    ctx.lineWidth = 1;
    for (let ring = 1; ring <= 3; ring++) {
      ctx.beginPath();
      ctx.arc(cx, cy, (r * ring) / 3, 0, Math.PI * 2);
      ctx.stroke();
    }

    // Crosshairs & Compass Markings
    ctx.strokeStyle = "rgba(148, 163, 184, 0.18)";
    ctx.beginPath();
    ctx.moveTo(cx - r, cy);
    ctx.lineTo(cx + r, cy);
    ctx.moveTo(cx, cy - r);
    ctx.lineTo(cx, cy + r);
    ctx.stroke();

    // Cardinal Points
    ctx.fillStyle = "rgba(148, 163, 184, 0.85)";
    ctx.font = "bold 8px 'JetBrains Mono', monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("N", cx, cy - r + 8);
    ctx.fillText("S", cx, cy + r - 8);
    ctx.fillText("E", cx + r - 8, cy);
    ctx.fillText("W", cx - r + 8, cy);

    // Protected Zone Origin (0,0) - Green OK
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, Math.PI * 2);
    ctx.fillStyle = "#22c55e";
    ctx.fill();

    // Sweep Line & Phosphor Glow (primary blue)
    this.sweepAngle = (this.sweepAngle + 0.04) % (Math.PI * 2);
    const sweepX = cx + Math.cos(this.sweepAngle) * r;
    const sweepY = cy + Math.sin(this.sweepAngle) * r;

    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(0, "rgba(47, 107, 255, 0.18)");
    grad.addColorStop(1, "rgba(47, 107, 255, 0.0)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, this.sweepAngle - 0.5, this.sweepAngle);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = "rgba(79, 134, 255, 0.85)";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(sweepX, sweepY);
    ctx.stroke();

    // One source of truth: Radar draws ONLY objects currently visible in the main view
    const visibleObjects = activeObjects.filter(obj => {
      if (typeof window.isVisibleInMainView === 'function') {
        return window.isVisibleInMainView(obj, simTime, factors, visibilityWindows);
      }
      return true;
    });

    // Render Target Blips from Telemetry (x_m, y_m): amber/red, or green when detected
    visibleObjects.forEach(obj => {
      // Map local metres (x_m east/west, y_m north/south) to radar coordinates
      // Origin (0,0) is center (cx, cy). North is -y on canvas, East is +x
      const normX = (obj.x_m / this.maxRangeM) * r;
      const normY = -(obj.y_m / this.maxRangeM) * r;

      const blipX = cx + normX;
      const blipY = cy + normY;

      // Ensure within scope circle
      const distFromCenter = Math.hypot(normX, normY);
      if (distFromCenter <= r) {
        // Outer halo
        ctx.beginPath();
        ctx.arc(blipX, blipY, 4, 0, Math.PI * 2);
        ctx.fillStyle = obj.detected ? "rgba(34, 197, 94, 0.45)" : "rgba(245, 181, 61, 0.4)";
        ctx.fill();

        // Inner solid blip: amber for airborne track, green when acquired/detected
        ctx.beginPath();
        ctx.arc(blipX, blipY, 2, 0, Math.PI * 2);
        ctx.fillStyle = obj.detected ? "#22c55e" : "#f5b53d";
        ctx.fill();
      }
    });

    // Outer Bezel Rim
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}

window.RadarWidget = RadarWidget;
