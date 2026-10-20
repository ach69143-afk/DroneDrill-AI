// DroneDrill AI - Unified Draw Pipeline (renderer.js)
// Single shared renderFrame(ctx, state, view) function for main viewport, sensor panels, and test sheet.

(function (window) {
  'use strict';

  // Horizon fraction per terrain and time-of-day (from user specification)
  const HORIZON_FRACTIONS = {
    open_day: 0.60,
    open_night: 0.66,
    urban_day: 0.58,
    urban_night: 0.64,
    forest_day: 0.62,
    forest_night: 0.80,
    hills_day: 0.74,
    hills_night: 0.69,
  };

  // Image cache and offscreen pre-rendered static background cache
  const imageAssets = {};
  const staticBgCache = {}; // key: `${terrain}_${time}_${sensor}_${w}x${h}` -> HTMLCanvasElement
  const warnedImages = new Set();

  // Pre-rendered noise texture for fog overlays (NO ellipses, NO radial gradients)
  let noiseTextureCanvas = null;

  function initNoiseTexture() {
    if (noiseTextureCanvas) return;
    noiseTextureCanvas = document.createElement('canvas');
    noiseTextureCanvas.width = 512;
    noiseTextureCanvas.height = 128;
    const nctx = noiseTextureCanvas.getContext('2d');

    // Horizontal soft noise bands
    const imgData = nctx.createImageData(512, 128);
    const d = imgData.data;

    for (let y = 0; y < 128; y++) {
      // Soft Gaussian-like vertical profile centered at y=64
      const vDist = Math.abs(y - 64) / 64;
      const vAlpha = Math.max(0, 1.0 - vDist * vDist);

      for (let x = 0; x < 512; x++) {
        // Multi-frequency horizontal wave variation
        const wave = Math.sin(x * 0.03) * 0.5 + Math.sin(x * 0.08 + y * 0.05) * 0.3 + (Math.random() - 0.5) * 0.2;
        const val = Math.min(255, Math.max(0, Math.floor(180 + wave * 50)));
        const idx = (y * 512 + x) * 4;

        d[idx] = val;
        d[idx + 1] = val + 10;
        d[idx + 2] = val + 20;
        d[idx + 3] = Math.floor(vAlpha * (100 + wave * 40));
      }
    }
    nctx.putImageData(imgData, 0, 0);
  }

  /**
   * Preload an image asset.
   */
  function loadImage(src) {
    if (!imageAssets[src]) {
      const img = new Image();
      img.src = src;
      img.onload = () => {
        // Clear cached static backgrounds when image finishes loading
        Object.keys(staticBgCache).forEach(k => {
          if (k.startsWith(src)) delete staticBgCache[k];
        });
      };
      img.onerror = () => {
        if (!warnedImages.has(src)) {
          warnedImages.add(src);
          console.warn(`DroneDrill AI: Background image not found at ${src}, falling back to procedural sky.`);
        }
      };
      imageAssets[src] = img;
    }
    return imageAssets[src];
  }

  /**
   * Get horizon fraction for given terrain and time of day.
   */
  function getHorizonFraction(terrain, tod) {
    const baseTime = (tod === 'dusk') ? 'day' : tod;
    const key = `${terrain}_${baseTime}`;
    return HORIZON_FRACTIONS[key] !== undefined ? HORIZON_FRACTIONS[key] : 0.65;
  }

  /**
   * Render static background to an offscreen canvas once per session/resolution.
   * Pipeline steps:
   *   A. Background: draw photo with "cover" scaling over full canvas, fallback colour underneath.
   *   B. Time-of-day grade (linear gradients only):
   *      - day: none
   *      - dusk: multiply tint rgba(90,60,120,0.30), linear gradient at horizon from rgba(255,140,60,0.35) to transparent upward, 80% brightness.
   *      - night: night image as is, NO extra darkening, small lift (brightness 110%).
   *   E. Sensor look on background: Thermal = greyscale + contrast.
   */
  function getStaticBackgroundCanvas(terrain, tod, sensor, W, H) {
    const cacheKey = `${terrain}_${tod}_${sensor}_${W}x${H}`;
    const baseTime = (tod === 'dusk') ? 'day' : (tod || 'day');
    const imagePath = `assets/bg/${terrain}_${baseTime}.jpg`;

    const img = loadImage(imagePath);
    const isLoaded = img && img.complete && img.naturalWidth > 0;

    // Check if cache valid
    if (staticBgCache[cacheKey] && staticBgCache[cacheKey]._loaded === isLoaded) {
      return staticBgCache[cacheKey];
    }

    const bgCanvas = document.createElement('canvas');
    bgCanvas.width = W;
    bgCanvas.height = H;
    bgCanvas._loaded = isLoaded;
    const bctx = bgCanvas.getContext('2d');

    const horizonFrac = getHorizonFraction(terrain, tod);
    const horizonY = H * horizonFrac;

    // Fallback colour underneath
    bctx.fillStyle = (tod === 'night') ? '#070c14' : (tod === 'dusk' ? '#1c1524' : '#142c4a');
    bctx.fillRect(0, 0, W, H);

    if (isLoaded) {
      // Step A: Cover scaling over full canvas
      const imgRatio = img.naturalWidth / img.naturalHeight;
      const canvasRatio = W / H;
      let renderW, renderH, offsetX, offsetY;

      if (canvasRatio > imgRatio) {
        renderW = W;
        renderH = W / imgRatio;
        offsetX = 0;
        offsetY = (H - renderH) / 2;
      } else {
        renderH = H;
        renderW = H * imgRatio;
        offsetX = (W - renderW) / 2;
        offsetY = 0;
      }

      bctx.drawImage(img, offsetX, offsetY, renderW, renderH);

      // Step B: Time-of-day grade (linear gradients only)
      if (tod === 'dusk') {
        // 1. Multiply tint rgba(90,60,120,0.30) over the whole frame
        bctx.save();
        bctx.globalCompositeOperation = 'multiply';
        bctx.fillStyle = 'rgba(90, 60, 120, 0.30)';
        bctx.fillRect(0, 0, W, H);
        bctx.restore();

        // 2. Linear gradient near the horizon from rgba(255,140,60,0.35) to transparent upward
        const gradSpan = H * 0.28;
        const duskGrad = bctx.createLinearGradient(0, horizonY, 0, Math.max(0, horizonY - gradSpan));
        duskGrad.addColorStop(0.0, 'rgba(255, 140, 60, 0.35)');
        duskGrad.addColorStop(1.0, 'rgba(255, 140, 60, 0.0)');
        bctx.fillStyle = duskGrad;
        bctx.fillRect(0, Math.max(0, horizonY - gradSpan), W, gradSpan);

        // 3. About 80% brightness
        bctx.fillStyle = 'rgba(0, 0, 0, 0.20)';
        bctx.fillRect(0, 0, W, H);

      } else if (tod === 'night') {
        // Use night image as is. NO extra darkening. Small lift (brightness 110%) allowed.
        bctx.save();
        bctx.globalCompositeOperation = 'screen';
        bctx.fillStyle = 'rgba(255, 255, 255, 0.10)';
        bctx.fillRect(0, 0, W, H);
        bctx.restore();
      }
      // day: none

    } else {
      // Procedural fallback sky + terrain
      renderProceduralFallback(bctx, W, H, tod, terrain, horizonY);
    }

    // Step E: Sensor look on background (Thermal = greyscale + contrast, dark background)
    if (sensor === 'thermal') {
      applyThermalFilter(bctx, W, H);
    }

    staticBgCache[cacheKey] = bgCanvas;
    return bgCanvas;
  }

  function applyThermalFilter(ctx, W, H) {
    try {
      const imgData = ctx.getImageData(0, 0, W, H);
      const d = imgData.data;
      for (let i = 0; i < d.length; i += 4) {
        const lum = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        // High-contrast infrared terrain look
        const c = Math.min(255, Math.max(0, (lum - 128) * 1.35 + 105));
        d[i] = c * 0.70;
        d[i + 1] = c * 0.75;
        d[i + 2] = c * 0.90;
      }
      ctx.putImageData(imgData, 0, 0);
    } catch (e) {
      // Cross-origin fallback
      ctx.fillStyle = 'rgba(4, 8, 16, 0.75)';
      ctx.fillRect(0, 0, W, H);
    }
  }

  function renderProceduralFallback(ctx, W, H, tod, terrain, horizonY) {
    const skyGrad = ctx.createLinearGradient(0, 0, 0, horizonY);
    if (tod === 'night') {
      skyGrad.addColorStop(0, '#040810');
      skyGrad.addColorStop(1, '#0e1726');
    } else if (tod === 'dusk') {
      skyGrad.addColorStop(0, '#140c24');
      skyGrad.addColorStop(0.6, '#461e38');
      skyGrad.addColorStop(1, '#8e4538');
    } else {
      skyGrad.addColorStop(0, '#163255');
      skyGrad.addColorStop(0.7, '#2f5b8c');
      skyGrad.addColorStop(1, '#668fb9');
    }
    ctx.fillStyle = skyGrad;
    ctx.fillRect(0, 0, W, horizonY);

    const groundGrad = ctx.createLinearGradient(0, horizonY, 0, H);
    groundGrad.addColorStop(0, (tod === 'night') ? '#080e18' : '#1b2a1e');
    groundGrad.addColorStop(1, (tod === 'night') ? '#020509' : '#0e1710');
    ctx.fillStyle = groundGrad;
    ctx.fillRect(0, horizonY, W, H - horizonY);

    // Terrain outline
    ctx.fillStyle = (tod === 'night') ? '#060a12' : '#080d14';
    ctx.beginPath();
    ctx.moveTo(0, horizonY);
    if (terrain === 'urban') {
      let x = 0;
      while (x < W) {
        const bw = 35 + ((x * 17) % 45);
        const bh = 25 + ((x * 31) % 65);
        ctx.lineTo(x, horizonY - bh);
        ctx.lineTo(x + bw, horizonY - bh);
        x += bw;
      }
    } else if (terrain === 'hills') {
      for (let x = 0; x <= W; x += 30) {
        ctx.lineTo(x, horizonY - 15 - Math.sin(x * 0.01) * 30);
      }
    } else if (terrain === 'forest') {
      for (let x = 0; x <= W; x += 15) {
        ctx.lineTo(x, horizonY - (x % 30 === 0 ? 20 : 10));
      }
    }
    ctx.lineTo(W, horizonY);
    ctx.lineTo(W, H);
    ctx.lineTo(0, H);
    ctx.closePath();
    ctx.fill();
  }

  /**
   * One source of truth for whether an object is visible in the main view at simTime.
   * Uses the same projection and rules as server-side sensor_view.py:
   * inside the safe sky rectangle, not behind camera, distance <= 3000m,
   * not occluded, not in dropout, and simTime >= appears_at_time.
   */
  function isVisibleInMainView(obj, simTime, factors = {}, visibilityWindows = {}, W = 1920, H = 1080) {
    if (!obj) return false;

    const appearsAt = (obj.appears_at_time !== undefined) ? Number(obj.appears_at_time) : 0.0;
    if (simTime < appearsAt) return false;

    const x_m = (obj.x_m !== undefined) ? Number(obj.x_m) : (obj.start_position ? Number(obj.start_position[0]) : 0);
    const y_m = (obj.y_m !== undefined) ? Number(obj.y_m) : (obj.start_position ? Number(obj.start_position[1]) : 1000);
    const alt_m = (obj.alt_m !== undefined) ? Number(obj.alt_m) : (obj.start_position ? Number(obj.start_position[2]) : 120);

    // In front of camera: y_m must be strictly positive
    if (y_m <= 0) return false;

    const distanceM = Math.hypot(x_m, y_m);
    if (distanceM > 3000) return false; // Beyond sensor range

    const terrain = factors.terrain || 'open';
    const tod = factors.time_of_day || 'day';
    const horizonFrac = getHorizonFraction(terrain, tod);

    const minX = W * 0.10;
    const maxX = W * 0.90;
    const minY = H * 0.08;
    const maxY = H * (horizonFrac - 0.04);

    const fovScale = (W * 0.75) / Math.max(60, distanceM);
    const rawX = W / 2 + x_m * fovScale;
    const rawY = (H * horizonFrac) - (alt_m * fovScale * 1.05);

    const isInside = (rawX >= minX && rawX <= maxX && rawY >= minY && rawY <= maxY);
    if (!isInside) return false;

    // Check visibility windows for degradation blackouts (occlusion, dropout)
    const wins = (visibilityWindows && visibilityWindows[obj.id]) || obj.sensor_visibility || obj.visibility_windows;
    if (wins && Array.isArray(wins)) {
      for (let i = 0; i < wins.length; i++) {
        const w = wins[i];
        if (simTime >= w.from_t && simTime <= w.to_t) {
          if (!w.visible) return false;
          break;
        }
      }
    }

    return true;
  }

  /**
   * Project 3D telemetry into the Safe Sky Rectangle:
   * Objects live in the SKY only: y between 8% of the height and (horizon - 4%), x between 10% and 90% of the width.
   * If an object would leave the rectangle, fade it out over 1 s instead of drawing it at the edge.
   */
  function projectObjectSafeSky(obj, W, H, horizonFrac, simTime, trailState) {
    const minX = W * 0.10;
    const maxX = W * 0.90;
    const minY = H * 0.08;
    const maxY = H * (horizonFrac - 0.04);

    const x_m = (obj.x_m !== undefined) ? obj.x_m : 0;
    const y_m = (obj.y_m !== undefined) ? obj.y_m : 1000;
    const alt_m = (obj.alt_m !== undefined) ? obj.alt_m : 120;

    const distanceM = Math.hypot(x_m, y_m);
    const fovScale = (W * 0.75) / Math.max(60, distanceM);

    // Natural forward camera projection
    let rawX = W / 2 + x_m * fovScale;
    let rawY = (H * horizonFrac) - (alt_m * fovScale * 1.05);

    // Check if inside safe rectangle
    const isInside = (rawX >= minX && rawX <= maxX && rawY >= minY && rawY <= maxY);

    // Fade out over 1s when leaving safe rectangle
    if (!trailState.fade) trailState.fade = {};
    let fs = trailState.fade[obj.id];
    if (!fs) {
      fs = { lastInsideT: simTime, opacity: 1.0 };
      trailState.fade[obj.id] = fs;
    }

    let opacity = 1.0;
    if (isInside) {
      fs.lastInsideT = simTime;
      fs.opacity = 1.0;
      opacity = 1.0;
    } else {
      const elapsed = simTime - fs.lastInsideT;
      if (elapsed < 1.0) {
        opacity = Math.max(0.0, 1.0 - elapsed);
        fs.opacity = opacity;
      } else {
        opacity = 0.0;
        fs.opacity = 0.0;
      }
    }

    // Clean un-clamped screen coordinates inside safe sky rectangle
    const scrX = rawX;
    const scrY = rawY;

    // Minimum on-screen size 16 px (silhouettes scale 0.7–1.4 with distance)
    const distNorm = Math.max(0.0, Math.min(1.0, (distanceM - 300) / 2200));
    const scale = 1.4 - distNorm * (1.4 - 0.7);

    return { scrX, scrY, scale, distanceM, isInside, opacity };
  }

  /**
   * Step C: Draw Class-Specific Vector Silhouettes
   */
  function drawSilhouette(ctx, obj, x, y, scale, isNight, isThermal, simTime) {
    ctx.save();
    ctx.translate(x, y);

    const heading = (obj.heading_deg !== undefined) ? obj.heading_deg : 0;
    ctx.rotate((heading - 90) * (Math.PI / 180) * 0.65);
    ctx.scale(scale, scale);

    const cls = obj.appearance || obj.true_class || 'unknown';

    if (isThermal) {
      // Step E: Thermal = white-hot soft glows (white core, grey falloff, NO cyan)
      const glowRadius = 18;
      const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, glowRadius);
      glow.addColorStop(0.0, '#ffffff');
      glow.addColorStop(0.35, 'rgba(255, 255, 255, 0.90)');
      glow.addColorStop(0.70, 'rgba(160, 160, 160, 0.45)');
      glow.addColorStop(1.0, 'rgba(40, 40, 40, 0.0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(0, 0, glowRadius, 0, Math.PI * 2);
      ctx.fill();

      // Sharp white core
      ctx.fillStyle = '#ffffff';
    } else if (isNight) {
      if (['multirotor', 'light_aircraft', 'fixed_wing_uav'].includes(cls)) {
        ctx.fillStyle = '#cbd5e1';
      } else {
        // Pale silhouette for balloons and birds at night
        ctx.fillStyle = 'rgba(220, 235, 245, 0.95)';
      }
    } else {
      ctx.fillStyle = '#0c141f';
    }

    if (cls === 'multirotor') {
      // Body + 4 rotor discs
      ctx.beginPath();
      ctx.ellipse(0, 0, 5, 3.5, 0, 0, Math.PI * 2);
      ctx.fill();

      ctx.lineWidth = 1.6;
      ctx.strokeStyle = ctx.fillStyle;
      ctx.beginPath();
      ctx.moveTo(-11, -7); ctx.lineTo(11, 7);
      ctx.moveTo(-11, 7); ctx.lineTo(11, -7);
      ctx.stroke();

      // 4 Rotor discs
      const rColor = isThermal ? '#ffffff' : (isNight ? '#94a3b8' : '#1e293b');
      ctx.fillStyle = rColor;
      [-11, 11].forEach(rx => {
        [-7, 7].forEach(ry => {
          ctx.beginPath();
          ctx.ellipse(rx, ry, 4.5, 2, simTime * 30, 0, Math.PI * 2);
          ctx.fill();
        });
      });

      // Blinking nav light at night
      if (isNight && !isThermal) {
        const isBlinkOn = ((simTime * 2.5) % 2.0) < 1.0;
        if (isBlinkOn) {
          ctx.fillStyle = '#ff2233';
          ctx.beginPath();
          ctx.arc(0, -6, 2.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }

    } else if (cls === 'fixed_wing_uav') {
      ctx.beginPath();
      ctx.moveTo(0, -11);
      ctx.lineTo(14, 3);
      ctx.lineTo(5, 2.5);
      ctx.lineTo(2, 9);
      ctx.lineTo(-2, 9);
      ctx.lineTo(-5, 2.5);
      ctx.lineTo(-14, 3);
      ctx.closePath();
      ctx.fill();

      if (isNight && !isThermal) {
        const isBlinkOn = ((simTime * 3.0) % 2.0) < 1.0;
        if (isBlinkOn) {
          ctx.fillStyle = '#ff2233';
          ctx.beginPath();
          ctx.arc(0, -10, 2.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }

    } else if (cls === 'light_aircraft') {
      ctx.fillRect(-2.5, -9, 5, 18);
      ctx.fillRect(-17, -2.5, 34, 3.5);
      ctx.fillRect(-7, 6.5, 14, 2);

      // Blinking port (red) and starboard (green) nav lights at night
      if (isNight && !isThermal) {
        const isBlinkOn = ((simTime * 2.5) % 2.0) < 1.0;
        if (isBlinkOn) {
          ctx.fillStyle = '#ff2233'; // Port red
          ctx.beginPath();
          ctx.arc(-17, -2, 2.2, 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = '#22c55e'; // Starboard green
          ctx.beginPath();
          ctx.arc(17, -2, 2.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }

    } else if (cls === 'bird') {
      // Wing-flap animation
      const flap = Math.sin(simTime * 8.0);
      ctx.beginPath();
      ctx.arc(0, 0, 2.5, 0, Math.PI * 2);
      ctx.fill();

      ctx.lineWidth = 1.8;
      ctx.strokeStyle = ctx.fillStyle;
      ctx.beginPath();
      ctx.moveTo(-10, flap * 4.5);
      ctx.quadraticCurveTo(-4, -flap * 2, 0, 0);
      ctx.quadraticCurveTo(4, -flap * 2, 10, flap * 4.5);
      ctx.stroke();

    } else if (cls === 'balloon') {
      // Round, slow drift
      const drift = Math.sin(simTime * 0.8) * 0.08;
      ctx.rotate(drift);
      ctx.beginPath();
      ctx.arc(0, -4, 6.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillRect(-1.5, 3, 3, 3);
    } else {
      ctx.fillRect(-4, -4, 8, 8);
    }

    ctx.restore();
  }

  /**
   * Step D: Weather Overlays
   * Drawn after objects so fog dims them.
   * NO ellipses and NO radial gradients anywhere!
   */
  function renderWeatherOverlays(ctx, W, H, horizonFrac, weather, simTime) {
    if (!weather || weather === 'clear') return;

    const horizonY = H * horizonFrac;

    if (weather === 'fog' || weather === 'haze') {
      initNoiseTexture();
      const isFog = (weather === 'fog');
      const maxAlpha = isFog ? 0.65 : 0.28;
      const midAlpha = isFog ? 0.35 : 0.15;
      const topAlpha = isFog ? 0.14 : 0.05;

      // Vertical linear gradient (denser at horizon)
      const fogGrad = ctx.createLinearGradient(0, 0, 0, H);
      fogGrad.addColorStop(0.0, `rgba(205, 220, 235, ${topAlpha})`);
      fogGrad.addColorStop(Math.max(0, (horizonY - 80) / H), `rgba(210, 225, 240, ${midAlpha})`);
      fogGrad.addColorStop(horizonY / H, `rgba(220, 230, 245, ${maxAlpha})`);
      fogGrad.addColorStop(1.0, `rgba(195, 210, 225, ${midAlpha})`);
      ctx.fillStyle = fogGrad;
      ctx.fillRect(0, 0, W, H);

      // Two horizontally drifting soft noise bands from pre-rendered noise texture
      ctx.save();
      ctx.globalAlpha = isFog ? 0.35 : 0.16;
      const drift1 = (simTime * 20) % 512;
      const drift2 = (-simTime * 28) % 512;
      ctx.drawImage(noiseTextureCanvas, -drift1, horizonY - 45, W + 512, 70);
      ctx.drawImage(noiseTextureCanvas, -drift2, horizonY - 15, W + 512, 55);
      ctx.restore();

    } else if (weather === 'rain') {
      // Rain: up to 120 thin slanted lines at 25% opacity
      ctx.save();
      ctx.strokeStyle = 'rgba(215, 235, 255, 0.25)';
      ctx.lineWidth = 1.0;
      ctx.beginPath();
      const rainCount = 110;
      for (let i = 0; i < rainCount; i++) {
        const seedX = (i * 137.5) % W;
        const speed = 14 + (i % 8);
        const curY = (i * 23 + simTime * speed * 25) % (H + 30) - 20;
        const len = 12 + (i % 12);
        ctx.moveTo(seedX, curY);
        ctx.lineTo(seedX - 4, curY + len);
      }
      ctx.stroke();
      ctx.restore();

    } else if (weather === 'dust') {
      // Dust: a 12% sand tint
      ctx.fillStyle = 'rgba(210, 180, 140, 0.12)';
      ctx.fillRect(0, 0, W, H);
    }
  }

  /**
   * Step F: Subtle Degradation Overlays
   */
  function renderDegradationOverlay(ctx, W, H, degradation, simTime) {
    if (!degradation || degradation === 'none') return;

    if (degradation === 'noise') {
      // Dynamic subtle noise grain
      ctx.fillStyle = 'rgba(255, 255, 255, 0.04)';
      for (let i = 0; i < 60; i++) {
        const rx = Math.random() * W;
        const ry = Math.random() * H;
        ctx.fillRect(rx, ry, 2, 2);
      }
    } else if (degradation === 'dropout') {
      // Frame replaced periodically by dark frame with "SIGNAL LOSS"
      const isDropout = ((simTime * 0.7) % 5.0) < 0.12;
      if (isDropout) {
        ctx.fillStyle = 'rgba(8, 12, 18, 0.90)';
        ctx.fillRect(0, 0, W, H);
        ctx.fillStyle = 'rgba(255, 82, 82, 0.85)';
        ctx.font = '12px monospace';
        ctx.fillText('SIGNAL LOSS', W / 2 - 40, H / 2);
      }
    }
  }

  /**
   * ONE shared draw pipeline function for main viewport, sensor panels, and test contact sheets.
   *
   * @param {CanvasRenderingContext2D} ctx - Target 2D rendering context
   * @param {Object} state - State object { factors, activeObjects, simTime, visibilityWindows, selectedObjectId, trailState }
   * @param {Object} view - View configuration:
   *   { width, height, sensor, zoom, cropCenter, isPanel, showHUD }
   */
  function renderFrame(ctx, state, view) {
    if (!ctx) return [];

    const W = view.width || ctx.canvas.width;
    const H = view.height || ctx.canvas.height;
    const factors = state.factors || {};
    const terrain = factors.terrain || 'open';
    const tod = factors.time_of_day || 'day';
    const weather = factors.weather || 'clear';
    const degradation = factors.degradation || 'none';
    const sensor = view.sensor || factors.sensor_mode || 'EO';
    const isThermal = (sensor === 'thermal');
    const isNight = (tod === 'night');
    const simTime = state.simTime || 0.0;
    const trailState = state.trailState || {};

    const horizonFrac = getHorizonFraction(terrain, tod);
    const zoom = Math.min(2.5, Math.max(1.0, view.zoom || 1.0));
    const isCropped = (zoom > 1.0) && view.cropCenter;

    // Pixelation degradation: render to 50% canvas then scale up without smoothing
    let targetCtx = ctx;
    let pixelCanvas = null;
    let pixelCtx = null;
    if (degradation === 'pixelation') {
      pixelCanvas = document.createElement('canvas');
      pixelCanvas.width = Math.max(1, Math.floor(W * 0.5));
      pixelCanvas.height = Math.max(1, Math.floor(H * 0.5));
      pixelCtx = pixelCanvas.getContext('2d');
      targetCtx = pixelCtx;
    }

    targetCtx.save();

    // Camera sway on main view (1-2 px subtle sinusoidal platform sway)
    if (!view.isPanel) {
      const swayX = Math.sin(simTime * 1.35) * 1.5;
      const swayY = Math.cos(simTime * 0.95) * 1.0;
      targetCtx.translate(swayX, swayY);
    }

    // Centered crop transform for EO / Thermal panels
    if (isCropped) {
      targetCtx.translate(W / 2, H / 2);
      targetCtx.scale(zoom, zoom);
      targetCtx.translate(-view.cropCenter.x, -view.cropCenter.y);
    }

    // Step A, B, E: Draw pre-rendered static background (once per session/key)
    const bgCanvas = getStaticBackgroundCanvas(terrain, tod, sensor, W, H);
    targetCtx.drawImage(bgCanvas, 0, 0, W, H);

    // Step C: Project and Draw Objects (after grade, before weather)
    const activeObjects = state.activeObjects || [];
    const visibleScreenObjects = [];

    activeObjects.forEach(obj => {
      // One source of truth for visibility in main view
      if (!isVisibleInMainView(obj, simTime, factors, state.visibilityWindows, W, H)) {
        return;
      }

      const proj = projectObjectSafeSky(obj, W, H, horizonFrac, simTime, trailState);
      if (proj.opacity <= 0.001) return;

      visibleScreenObjects.push({
        id: obj.id,
        scrX: proj.scrX,
        scrY: proj.scrY,
        distanceM: proj.distanceM,
        detected: !!obj.detected,
        radius: 24,
      });

      targetCtx.save();
      // Minimum contrast: a visible object is never drawn below 35% opacity
      targetCtx.globalAlpha = Math.max(0.35, proj.opacity);

      // In cropped view, adjust scale so object remains at true size (never a giant blurry blob)
      const drawScale = isCropped ? (proj.scale / zoom) : proj.scale;

      // Draw silhouette
      drawSilhouette(
        targetCtx,
        obj,
        proj.scrX,
        proj.scrY,
        drawScale,
        isNight,
        isThermal,
        simTime
      );

      // Targeting brackets if selected or detected (NO text labels anywhere)
      if (obj.detected || obj.id === state.selectedObjectId) {
        const isSel = (obj.id === state.selectedObjectId);
        const bracketSize = Math.max(14, 12 * drawScale);
        targetCtx.strokeStyle = isSel ? '#e5484d' : (obj.detected ? '#22c55e' : 'rgba(229, 72, 77, 0.7)');
        targetCtx.lineWidth = isSel ? 2 : 1.5;
        const arm = 4;
        const bx = proj.scrX;
        const by = proj.scrY;

        targetCtx.beginPath();
        // Top-Left
        targetCtx.moveTo(bx - bracketSize, by - bracketSize + arm);
        targetCtx.lineTo(bx - bracketSize, by - bracketSize);
        targetCtx.lineTo(bx - bracketSize + arm, by - bracketSize);
        // Top-Right
        targetCtx.moveTo(bx + bracketSize - arm, by - bracketSize);
        targetCtx.lineTo(bx + bracketSize, by - bracketSize);
        targetCtx.lineTo(bx + bracketSize, by - bracketSize + arm);
        // Bottom-Left
        targetCtx.moveTo(bx - bracketSize, by + bracketSize - arm);
        targetCtx.lineTo(bx - bracketSize, by + bracketSize);
        targetCtx.lineTo(bx - bracketSize + arm, by + bracketSize);
        // Bottom-Right
        targetCtx.moveTo(bx + bracketSize - arm, by + bracketSize);
        targetCtx.lineTo(bx + bracketSize, by + bracketSize);
        targetCtx.lineTo(bx + bracketSize, by + bracketSize - arm);
        targetCtx.stroke();
      }

      targetCtx.restore();
    });

    // Step D: Weather Overlays (drawn after objects so fog dims them)
    renderWeatherOverlays(targetCtx, W, H, horizonFrac, weather, simTime);

    // Step F: Degradation Overlays
    renderDegradationOverlay(targetCtx, W, H, degradation, simTime);

    targetCtx.restore();

    // Scale up pixelation if active without smoothing
    if (degradation === 'pixelation' && pixelCanvas) {
      ctx.save();
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(pixelCanvas, 0, 0, W, H);
      ctx.imageSmoothingEnabled = true;
      ctx.restore();
    }

    // Panel reticles / overlays in uncropped viewport space
    if (view.isPanel && isCropped) {
      ctx.save();
      ctx.strokeStyle = isThermal ? '#ffffff' : '#2f6bff';
      ctx.lineWidth = 1.0;
      const cx = W / 2;
      const cy = H / 2;
      const r = 22;

      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.moveTo(cx - r - 4, cy); ctx.lineTo(cx - r + 6, cy);
      ctx.moveTo(cx + r - 6, cy); ctx.lineTo(cx + r + 4, cy);
      ctx.moveTo(cx, cy - r - 4); ctx.lineTo(cx, cy - r + 6);
      ctx.moveTo(cx, cy + r - 6); ctx.lineTo(cx, cy + r + 4);
      ctx.stroke();
      ctx.restore();
    }

    // Main HUD crosshair (subtle slate)
    if (view.showHUD && !view.isPanel) {
      ctx.save();
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
      ctx.lineWidth = 1;
      const cx = W / 2;
      const cy = H / 2;
      ctx.beginPath();
      ctx.moveTo(cx - 20, cy); ctx.lineTo(cx - 6, cy);
      ctx.moveTo(cx + 6, cy); ctx.lineTo(cx + 20, cy);
      ctx.moveTo(cx, cy - 20); ctx.lineTo(cx, cy - 6);
      ctx.moveTo(cx, cy + 6); ctx.lineTo(cx, cy + 20);
      ctx.stroke();
      ctx.restore();
    }

    return visibleScreenObjects;
  }

  // Export to window
  window.DroneDrillRenderer = {
    HORIZON_FRACTIONS,
    getHorizonFraction,
    getStaticBackgroundCanvas,
    projectObjectSafeSky,
    isVisibleInMainView,
    renderFrame,
  };
  window.renderFrame = renderFrame;
  window.isVisibleInMainView = isVisibleInMainView;

})(window);
