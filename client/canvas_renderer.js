// DroneDrill AI - Main Viewport Canvas Renderer
// Uses ONE shared renderFrame(ctx, state, view) from renderer.js

class CanvasRenderer {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas ? this.canvas.getContext('2d') : null;

    this.activeSensorMode = 'EO';
    this.screenObjects = [];
    this.hitRadius = 45;
    this.trailState = {};

    this.resize();
    window.addEventListener('resize', () => this.resize());
  }

  resize() {
    if (!this.canvas) return;
    const rect = this.canvas.parentElement ? this.canvas.parentElement.getBoundingClientRect() : null;
    if (rect && rect.width > 0 && rect.height > 0) {
      const targetW = Math.min(1920, Math.floor(rect.width));
      const targetH = Math.min(1080, Math.floor(rect.height));

      if (this.canvas.width !== targetW || this.canvas.height !== targetH) {
        this.canvas.width = targetW;
        this.canvas.height = targetH;
      }
    }
  }

  setSensorMode(mode) {
    this.activeSensorMode = mode || 'EO';
  }

  preloadBackground(terrain, tod) {
    if (window.DroneDrillRenderer && window.DroneDrillRenderer.getStaticBackgroundCanvas) {
      const W = this.canvas ? this.canvas.width : 1200;
      const H = this.canvas ? this.canvas.height : 800;
      window.DroneDrillRenderer.getStaticBackgroundCanvas(terrain, tod, this.activeSensorMode, W, H);
    }
  }

  render(activeObjects = [], simTime = 0, factors = {}, visibilityWindows = {}, selectedObjId = null) {
    if (!this.canvas || !this.ctx || !window.renderFrame) return;

    const W = this.canvas.width;
    const H = this.canvas.height;

    const state = {
      factors,
      activeObjects,
      simTime,
      visibilityWindows,
      selectedObjectId: selectedObjId,
      trailState: this.trailState,
    };

    const view = {
      width: W,
      height: H,
      sensor: this.activeSensorMode,
      zoom: 1.0,
      cropCenter: null,
      isPanel: false,
      showHUD: true,
    };

    this.screenObjects = window.renderFrame(this.ctx, state, view) || [];
  }

  detectAtScreenCoord(screenX, screenY) {
    let closest = null;
    let minDist = this.hitRadius;

    for (let obj of this.screenObjects) {
      const d = Math.hypot(screenX - obj.scrX, screenY - obj.scrY);
      if (d <= minDist) {
        minDist = d;
        closest = obj;
      }
    }
    return closest;
  }
}

window.CanvasRenderer = CanvasRenderer;
