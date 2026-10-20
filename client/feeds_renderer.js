// DroneDrill AI - Stacked Sensor Feeds Component
// EO and Thermal panels call the shared renderFrame with a view rectangle:
// - Whole scene when no contact is flagged
// - Crop of at most 2.5x centred on the flagged contact (smooth scaling, objects at true size)
// Radar panel stays as it is.

class FeedsRenderer {
  constructor() {
    this.canvasEO = document.getElementById('feed-canvas-eo');
    this.canvasThermal = document.getElementById('feed-canvas-thermal');
    this.canvasRadar = document.getElementById('feed-canvas-radar');

    this.ctxEO = this.canvasEO ? this.canvasEO.getContext('2d') : null;
    this.ctxThermal = this.canvasThermal ? this.canvasThermal.getContext('2d') : null;
    this.ctxRadar = this.canvasRadar ? this.canvasRadar.getContext('2d') : null;

    this.radarSweep = 0;
    this.trailStateEO = {};
    this.trailStateThermal = {};
    this.screenObjectsEO = [];
    this.screenObjectsThermal = [];
    window.feedsRenderer = this;
  }

  render(activeObjects = [], simTime = 0, factors = {}, visibilityWindows = {}, selectedObjectId = null) {
    let flaggedObj = null;
    if (selectedObjectId) {
      flaggedObj = activeObjects.find(o => o.id === selectedObjectId);
    }
    if (!flaggedObj) {
      flaggedObj = activeObjects.find(o => o.detected);
    }

    const zoom = flaggedObj ? 2.5 : 1.0;

    // Update real zoom labels
    const eoZoomLabel = document.getElementById('eo-feed-zoom');
    if (eoZoomLabel) {
      eoZoomLabel.textContent = (zoom > 1.0) ? `Zoom ${zoom.toFixed(1)}x` : 'Zoom 1.0x';
    }
    const thermalZoomLabel = document.getElementById('thermal-feed-zoom');
    if (thermalZoomLabel) {
      thermalZoomLabel.textContent = (zoom > 1.0) ? `IR ${zoom.toFixed(1)}x` : 'IR W-Hot';
    }

    const state = {
      factors,
      activeObjects,
      simTime,
      visibilityWindows,
      selectedObjectId: flaggedObj ? flaggedObj.id : null,
    };

    // Calculate crop center in panel coordinates if flagged contact exists
    let cropCenter = null;
    if (flaggedObj && this.canvasEO && window.DroneDrillRenderer) {
      const W = this.canvasEO.width;
      const H = this.canvasEO.height;
      const horizonFrac = window.DroneDrillRenderer.getHorizonFraction(factors.terrain, factors.time_of_day);
      const proj = window.DroneDrillRenderer.projectObjectSafeSky(flaggedObj, W, H, horizonFrac, simTime, {});
      cropCenter = { x: proj.scrX, y: proj.scrY };
    }

    // 1. EO Visual Panel: calls shared renderFrame
    if (this.ctxEO && this.canvasEO && window.renderFrame) {
      const viewEO = {
        width: this.canvasEO.width,
        height: this.canvasEO.height,
        sensor: 'EO',
        zoom: zoom,
        cropCenter: cropCenter,
        isPanel: true,
        showHUD: false,
      };
      state.trailState = this.trailStateEO;
      this.screenObjectsEO = window.renderFrame(this.ctxEO, state, viewEO) || [];
    }

    // 2. Thermal IR Panel: calls shared renderFrame
    if (this.ctxThermal && this.canvasThermal && window.renderFrame) {
      const viewThermal = {
        width: this.canvasThermal.width,
        height: this.canvasThermal.height,
        sensor: 'thermal',
        zoom: zoom,
        cropCenter: cropCenter,
        isPanel: true,
        showHUD: false,
      };
      state.trailState = this.trailStateThermal;
      this.screenObjectsThermal = window.renderFrame(this.ctxThermal, state, viewThermal) || [];
    }

    // 3. Radar Feed: Draws only objects currently visible in main view
    this.renderRadar(activeObjects, simTime, factors, flaggedObj, visibilityWindows);
  }

  renderRadar(activeObjects, simTime, factors, flaggedObj, visibilityWindows = {}) {
    if (!this.ctxRadar || !this.canvasRadar) return;
    const ctx = this.ctxRadar;
    const w = this.canvasRadar.width;
    const h = this.canvasRadar.height;
    const cx = w / 2;
    const cy = h / 2;

    ctx.fillStyle = '#0e121a';
    ctx.fillRect(0, 0, w, h);

    // Range rings (muted blue-slate)
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.22)';
    ctx.lineWidth = 1;

    ctx.beginPath();
    ctx.arc(cx, cy, h * 0.42, 0, Math.PI * 2);
    ctx.arc(cx, cy, h * 0.28, 0, Math.PI * 2);
    ctx.arc(cx, cy, h * 0.14, 0, Math.PI * 2);
    ctx.stroke();

    // Azimuth crosshairs
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.18)';
    ctx.beginPath();
    ctx.moveTo(0, cy); ctx.lineTo(w, cy);
    ctx.moveTo(cx, 0); ctx.lineTo(cx, h);
    ctx.stroke();

    // Urban clutter
    if (factors.terrain === 'urban') {
      ctx.fillStyle = 'rgba(148, 163, 184, 0.08)';
      for (let i = 0; i < 20; i++) {
        const nx = (Math.sin(simTime * 5 + i * 3) * 0.5 + 0.5) * w;
        const ny = (Math.cos(simTime * 7 + i * 2) * 0.5 + 0.5) * h;
        ctx.fillRect(nx, ny, 2, 2);
      }
    }

    // Rotating radar sweep line (bright blue)
    this.radarSweep = (this.radarSweep + 0.05) % (Math.PI * 2);
    ctx.strokeStyle = 'rgba(47, 107, 255, 0.85)';
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(this.radarSweep) * (w / 2), cy + Math.sin(this.radarSweep) * (h / 2));
    ctx.stroke();

    // One source of truth: display only contacts currently visible in main view
    const visibleObjects = activeObjects.filter(obj => {
      if (typeof window.isVisibleInMainView === 'function') {
        return window.isVisibleInMainView(obj, simTime, factors, visibilityWindows);
      }
      return true;
    });

    visibleObjects.forEach(obj => {
      const rx = cx + (obj.x_m / 3000) * (w * 0.42);
      const ry = cy - (obj.y_m / 3000) * (h * 0.42);

      const isFlagged = flaggedObj && (obj.id === flaggedObj.id);
      const contactColor = isFlagged ? '#e5484d' : (obj.detected ? '#22c55e' : '#f5b53d');

      ctx.fillStyle = contactColor;
      ctx.beginPath();
      ctx.arc(rx, ry, isFlagged ? 3.5 : 2.5, 0, Math.PI * 2);
      ctx.fill();

      if (obj.detected || isFlagged) {
        ctx.strokeStyle = isFlagged ? '#e5484d' : '#22c55e';
        ctx.strokeRect(rx - 5, ry - 5, 10, 10);
      }
    });

    ctx.fillStyle = 'rgba(47, 107, 255, 0.85)';
    ctx.font = "9px 'JetBrains Mono', monospace";
    ctx.fillText('RADAR 3km', 8, 14);
  }
}

window.FeedsRenderer = FeedsRenderer;
