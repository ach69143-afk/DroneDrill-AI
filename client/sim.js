// DroneDrill AI - Simulator Client Engine (sim.js)
// Handles session result score parsing, error modal presentation,
// minimum contrast rendering, night visual enhancements, and multi-panel interaction.

(function (window) {
  'use strict';

  /**
   * Format a fractional score (0.0 - 1.0) as a clean percentage string.
   */
  function formatPercent(val) {
    if (val === null || val === undefined || isNaN(val)) {
      return '--';
    }
    const num = Number(val);
    if (!isFinite(num)) return '--';
    return `${Math.round(num * 100)}%`;
  }

  /**
   * Extract real score keys from /session/result response JSON.
   */
  function parseSessionResult(res) {
    if (!res || typeof res !== 'object') {
      return {
        overall: null,
        detection: null,
        classification: null,
        decision: null,
        timeliness: null,
        calibration: null,
      };
    }

    const overall = (res.overall_score !== undefined && res.overall_score !== null)
      ? res.overall_score
      : (res.overall !== undefined ? res.overall : null);

    const detection = (res.detection_score !== undefined && res.detection_score !== null)
      ? res.detection_score
      : (res.detection && typeof res.detection === 'object' ? res.detection.score : null);

    const classification = (res.classification_score !== undefined && res.classification_score !== null)
      ? res.classification_score
      : (res.classification && typeof res.classification === 'object' ? res.classification.score : null);

    const decision = (res.decision_score !== undefined && res.decision_score !== null)
      ? res.decision_score
      : (res.decision && typeof res.decision === 'object' ? res.decision.score : null);

    const timeliness = (res.timeliness_score !== undefined && res.timeliness_score !== null)
      ? res.timeliness_score
      : (res.timeliness && typeof res.timeliness === 'object' ? res.timeliness.score : null);

    const calibration = (res.calibration_score !== undefined && res.calibration_score !== null)
      ? res.calibration_score
      : (res.calibration && typeof res.calibration === 'object' ? res.calibration.score : null);

    return {
      overall,
      detection,
      classification,
      decision,
      timeliness,
      calibration,
    };
  }

  /**
   * Display evaluation results or request error inside the score popup modal (uses unified DroneDrillAAR renderer).
   */
  async function showResultsModal(resultData, errorMsg) {
    const modal = document.getElementById('modal-results');
    const bodyEl = document.getElementById('results-modal-body') || (modal ? modal.querySelector('.modal-body') : null);

    if (modal) modal.classList.add('active');

    if (errorMsg) {
      if (window.DroneDrillAAR && bodyEl) {
        window.DroneDrillAAR.renderError(bodyEl, errorMsg);
      }
      return;
    }

    if (!bodyEl) return;

    if (window.DroneDrillAAR) {
      window.DroneDrillAAR.renderLoading(bodyEl);
    }

    const sessionId = (resultData && (resultData.session_id || resultData.sessionId)) || (window.state && window.state.activeSessionId);
    let aarData = null;

    if (sessionId) {
      try {
        const apiBase = (window.CONFIG && window.CONFIG.API_BASE) || 'http://127.0.0.1:8000';
        const res = await fetch(`${apiBase}/aar/${sessionId}`);
        if (res.ok) {
          aarData = await res.json();
        }
      } catch (err) {
        console.warn('Failed to fetch full AAR in modal:', err);
      }
    }

    if (!aarData) {
      aarData = {
        session_id: sessionId || 'session',
        overall_score: resultData ? (resultData.overall_score ?? resultData.overall) : 0,
        scores: resultData || {},
        feedback_sentences: [],
        timeline: [],
        errors: { missed: [], false_alarms: 0 },
      };
    }

    if (window.DroneDrillAAR) {
      window.DroneDrillAAR.renderAAR(bodyEl, aarData, {
        isModal: true,
        onCloseModal: () => {
          if (modal) modal.classList.remove('active');
        },
        onNextScenario: () => {
          if (modal) modal.classList.remove('active');
          if (typeof window.startAdaptiveSession === 'function') window.startAdaptiveSession();
        },
        onOpenFullPage: (sid) => {
          window.location.href = `aar.html?session=${encodeURIComponent(sid)}`;
        },
      });
    }
  }

  /**
   * Minimum contrast styling rule:
   * - A visible object is never drawn below 35% opacity.
   * - At night:
   *   - Faint blinking nav-light or thermal-style glow for multirotor, light_aircraft, fixed_wing_uav.
   *   - Pale silhouette for balloons and birds.
   */
  function getSilhouetteStyle(cls, isVisible, tod, isThermal, simTime) {
    // Opacity is never below 35% (0.35) for any visible object
    let opacity = isVisible ? 1.0 : 0.45;
    opacity = Math.max(0.35, opacity);

    const isNight = (tod === 'night');
    let fillStyle = '#0a1017';
    let shadowColor = 'transparent';
    let shadowBlur = 0;
    let drawNavLight = false;

    if (isThermal) {
      fillStyle = '#ffffff';
      shadowColor = 'rgba(255, 255, 255, 0.45)'; // White-hot greyscale glow
      shadowBlur = 8;
    } else if (isNight) {
      if (['multirotor', 'light_aircraft', 'fixed_wing_uav'].includes(cls)) {
        // Metallic visible silhouette with subtle red beacon glow and nav light
        fillStyle = '#cbd5e1';
        shadowColor = 'rgba(239, 68, 68, 0.5)';
        shadowBlur = 7;
        drawNavLight = true;
      } else {
        // Pale silhouette for birds and balloons so they stand out against night sky
        fillStyle = 'rgba(215, 230, 245, 0.9)';
        shadowColor = 'rgba(255, 255, 255, 0.5)';
        shadowBlur = 5;
      }
    } else {
      fillStyle = isVisible ? '#0a1017' : 'rgba(10, 16, 23, 0.5)';
    }

    return {
      opacity,
      fillStyle,
      shadowColor,
      shadowBlur,
      drawNavLight,
      isBlinkOn: ((simTime * 2.5) % 2.0) < 1.0,
    };
  }

  /**
   * Handle autostart when URL has ?autostart=1, ?scripted_id=..., ?mode=test, or ?session_id=...
   * Shows a red banner with a Retry button if the API is unreachable.
   */
  async function handleAutostart(apiBase, traineeId, onStartScenario) {
    const urlParams = new URLSearchParams(window.location.search);
    const autostart = urlParams.get('autostart');
    const scriptedId = urlParams.get('scripted_id');
    const modeParam = urlParams.get('mode');
    const sessionIdParam = urlParams.get('session_id');

    if (autostart !== '1' && !scriptedId && modeParam !== 'test' && !sessionIdParam) {
      return false; // Simulator keeps normal standby options
    }

    const banner = document.getElementById('api-banner');
    const retryBtn = document.getElementById('btn-api-retry');

    async function executeLaunch() {
      try {
        if (banner) banner.classList.remove('active');

        // 1. Session from Builder stored in sessionStorage
        if (sessionIdParam) {
          const cached = sessionStorage.getItem('BUILDER_SESSION_' + sessionIdParam);
          if (cached) {
            try {
              const data = JSON.parse(cached);
              if (typeof onStartScenario === 'function') {
                await onStartScenario(data.session_id, data.scenario, 'practice');
              }
              return true;
            } catch (_) {}
          }
        }

        // 2. Scripted scenario launch
        if (scriptedId) {
          const res = await fetch(`${apiBase}/session/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              trainee_id: traineeId,
              mode: 'practice',
              scripted_id: scriptedId,
            }),
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
          const data = await res.json();
          if (typeof onStartScenario === 'function') {
            await onStartScenario(data.session_id, data.scenario, 'practice');
          }
          return true;
        }

        // 3. Test mode launch (held-out cells)
        if (modeParam === 'test') {
          const res = await fetch(`${apiBase}/session/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              trainee_id: traineeId,
              mode: 'test',
            }),
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
          const data = await res.json();
          if (typeof onStartScenario === 'function') {
            await onStartScenario(data.session_id, data.scenario, 'test');
          }
          return true;
        }

        // 4. Default adaptive autostart (POST /session/next)
        const res = await fetch(`${apiBase}/session/next`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ trainee_id: traineeId }),
        });
        if (!res.ok) {
          throw new Error(`API returned HTTP ${res.status}: ${res.statusText}`);
        }
        const data = await res.json();
        if (typeof onStartScenario === 'function') {
          await onStartScenario(data.session_id, data.scenario, 'practice');
        }
        return true;
      } catch (err) {
        console.error('DroneDrill AI autostart error:', err);
        if (banner) {
          banner.classList.add('active');
          const msgSpan = banner.querySelector('span');
          if (msgSpan) {
            msgSpan.textContent = `API Server Offline (${apiBase}). Ensure the DroneDrill AI service is running.`;
          }
        }
        return false;
      }
    }

    if (retryBtn) {
      retryBtn.onclick = (e) => {
        e.preventDefault();
        executeLaunch();
      };
    }

    return await executeLaunch();
  }

  /**
   * Hit detection in secondary panels (EO, Thermal, Radar).
   */
  function hitTestPanel(panelType, clickX, clickY, width, height, activeObjects, simTime, visibilityWindows, selectedObjectId = null, factors = null) {
    const hitRadius = 35;

    // Check exact rendered screen objects from FeedsRenderer if available
    if (panelType === 'eo' && window.feedsRenderer && window.feedsRenderer.screenObjectsEO) {
      for (let scr of window.feedsRenderer.screenObjectsEO) {
        if (Math.hypot(clickX - scr.scrX, clickY - scr.scrY) <= hitRadius) {
          const matched = activeObjects.find(o => o.id === scr.id) || scr;
          if (!window.isVisibleInMainView || window.isVisibleInMainView(matched, simTime, factors, visibilityWindows)) {
            return matched;
          }
        }
      }
    }
    if (panelType === 'thermal' && window.feedsRenderer && window.feedsRenderer.screenObjectsThermal) {
      for (let scr of window.feedsRenderer.screenObjectsThermal) {
        if (Math.hypot(clickX - scr.scrX, clickY - scr.scrY) <= hitRadius) {
          const matched = activeObjects.find(o => o.id === scr.id) || scr;
          if (!window.isVisibleInMainView || window.isVisibleInMainView(matched, simTime, factors, visibilityWindows)) {
            return matched;
          }
        }
      }
    }

    let flaggedObj = null;
    if (selectedObjectId) {
      flaggedObj = activeObjects.find(o => o.id === selectedObjectId);
    }
    if (!flaggedObj) {
      flaggedObj = activeObjects.find(o => o.detected);
    }

    // In magnified crop mode on EO or Thermal, contact is centered
    if ((panelType === 'eo' || panelType === 'thermal') && flaggedObj) {
      const cx = width / 2;
      const cy = height / 2;
      const d = Math.hypot(clickX - cx, clickY - cy);
      if (d <= hitRadius * 1.5) {
        if (!window.isVisibleInMainView || window.isVisibleInMainView(flaggedObj, simTime, factors, visibilityWindows)) {
          return flaggedObj;
        }
      }
    }

    for (let i = 0; i < activeObjects.length; i++) {
      const obj = activeObjects[i];

      // Objects not visible anywhere must not be clickable
      if (window.isVisibleInMainView && !window.isVisibleInMainView(obj, simTime, factors, visibilityWindows)) {
        continue;
      }

      let scrX = null;
      let scrY = null;
      let isVisible = true;

      if (panelType === 'eo' || panelType === 'thermal') {
        scrX = (obj.x_m / 5000 + 0.5) * width;
        const baseHorizon = height * 0.65;
        const altOffset = (obj.alt_m / 600) * (height * 0.4);
        scrY = Math.max(10, Math.min(height - 10, baseHorizon - altOffset));
      } else if (panelType === 'radar') {
        const cx = width / 2;
        const cy = height / 2;
        scrX = cx + (obj.x_m / 3000) * (width * 0.42);
        scrY = cy - (obj.y_m / 3000) * (height * 0.42);
      } else if (panelType === 'radar-widget') {
        const cx = width / 2;
        const cy = height / 2;
        const r = Math.min(cx, cy) - 6;
        scrX = cx + (obj.x_m / 3000) * r;
        scrY = cy - (obj.y_m / 3000) * r;
      }

      if (scrX !== null && scrY !== null && isVisible) {
        const d = Math.hypot(clickX - scrX, clickY - scrY);
        if (d <= hitRadius) {
          return obj;
        }
      }
    }
    return null;
  }

  // Export to window
  window.DroneDrillSim = {
    formatPercent,
    parseSessionResult,
    showResultsModal,
    getSilhouetteStyle,
    hitTestPanel,
    handleAutostart,
  };

})(window);
