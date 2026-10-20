// DroneDrill AI - Simulator Client Application Logic
// Team NexxGenX - PS 26247

(function () {
  'use strict';

  // State Management
  const state = {
    traineeId: (window.CONFIG && window.CONFIG.TRAINEE_ID) || 'demo_trainee_01',
    apiBase: (window.CONFIG && window.CONFIG.API_BASE) || 'http://127.0.0.1:8000',

    activeSessionId: null,
    scenario: null,
    factors: {},
    durationS: 60.0,
    difficultyIndex: 0.5,
    mode: 'practice',
    isAdaptive: false,

    // Telemetry and Objects
    telemetryPackets: [],
    packetsByObject: {},
    visibilityWindows: {},
    scenarioObjects: [],

    // Simulation Clock
    simTime: 0.0,
    isPlaying: false,
    playbackSpeed: 1.0,
    lastTickTs: null,

    // Trainee Assessments & False Alarms
    assessments: {}, // { [object_id]: { object_id, detected, detect_time_s, classified_as, threat_level_rated, response_chosen, confidence, submitted } }
    falseAlarms: 0,
    selectedObjectId: null,

    // Decision Tree Rules
    decisionTree: null,

    // Trainee Historic Stats
    completedScenariosCount: 0,
  };

  // Components
  let canvasRenderer = null;
  let radarWidget = null;
  let feedsRenderer = null;

  // --- Safe Helper for Event Binding ---
  function safeAddListener(id, event, handler) {
    const el = document.getElementById(id);
    if (el) el.addEventListener(event, handler);
  }

  // --- Initialization ---
  window.addEventListener('DOMContentLoaded', async () => {
    canvasRenderer = new CanvasRenderer('main-canvas');
    radarWidget = new RadarWidget('radar-widget-canvas');
    feedsRenderer = new FeedsRenderer();

    setupEventListeners();
    setupCanvasClickHandler();
    resetAssessmentForm();

    // Start Animation Loop immediately so rendering loop is always alive
    requestAnimationFrame(animationLoop);

    // Check debug URL for instant demo frame (?demo=1&terrain=...&time=...&weather=...)
    // Runs 100% offline without creating session or calling API
    if (checkDebugUrl()) {
      return;
    }

    await checkApiHealth();
    await loadDecisionTree();
    await loadTraineePerformance();

    // Check for autostart=1 parameter
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('autostart') === '1' && window.DroneDrillSim && window.DroneDrillSim.handleAutostart) {
      const started = await window.DroneDrillSim.handleAutostart(state.apiBase, state.traineeId, async (sessionId, scenario, mode) => {
        state.isAdaptive = true;
        const emptyState = document.getElementById('viewport-empty-state');
        if (emptyState) emptyState.style.display = 'none';
        await initSessionData(sessionId, scenario, mode);
      });
      if (started) {
        return;
      }
    }

    // Check if launched with pending session from instructor or adaptive recommendation
    const pendingSession = sessionStorage.getItem('PENDING_SIM_SESSION');
    if (pendingSession) {
      sessionStorage.removeItem('PENDING_SIM_SESSION');
      try {
        const parsed = JSON.parse(pendingSession);
        if (parsed.sessionId && parsed.scenario) {
          const emptyState = document.getElementById('viewport-empty-state');
          if (emptyState) emptyState.style.display = 'none';
          await initSessionData(parsed.sessionId, parsed.scenario, parsed.mode || 'practice');
        }
      } catch (e) {
        console.warn('Failed to parse pending session:', e);
      }
    } else if (sessionStorage.getItem('START_ADAPTIVE') === 'true') {
      sessionStorage.removeItem('START_ADAPTIVE');
      await startAdaptiveSession();
    }
  });

  // --- API Health & Connectivity ---
  async function checkApiHealth() {
    const banner = document.getElementById('api-banner');
    const retryBtn = document.getElementById('btn-api-retry');
    if (retryBtn && !retryBtn._bound) {
      retryBtn._bound = true;
      retryBtn.addEventListener('click', async () => {
        const ok = await checkApiHealth();
        const p = new URLSearchParams(window.location.search);
        if (ok && p.get('autostart') === '1' && window.DroneDrillSim && window.DroneDrillSim.handleAutostart) {
          await window.DroneDrillSim.handleAutostart(state.apiBase, state.traineeId, async (sessionId, scenario, mode) => {
            state.isAdaptive = true;
            const emptyState = document.getElementById('viewport-empty-state');
            if (emptyState) emptyState.style.display = 'none';
            await initSessionData(sessionId, scenario, mode);
          });
        }
      });
    }

    try {
      const res = await fetch(`${state.apiBase}/health`);
      if (res.ok) {
        if (banner) banner.classList.remove('active');
        return true;
      }
    } catch (e) {
      console.warn('API health check failed:', e);
    }
    if (banner) banner.classList.add('active');
    return false;
  }

  // --- Decision Tree Protocol Loading ---
  async function loadDecisionTree() {
    try {
      const res = await fetch(`${state.apiBase}/decision-tree`);
      if (res.ok) {
        state.decisionTree = await res.json();
        populateResponseDropdown(state.decisionTree.responses || []);
      }
    } catch (e) {
      console.error('Failed to load decision tree:', e);
    }
  }

  function populateResponseDropdown(responses) {
    const select = document.getElementById('response-select');
    if (!select) return;
    select.innerHTML = '<option value="">Select response...</option>';

    const defaultResponses = [
      'ignore',
      'log_only',
      'monitor',
      'report_to_command',
      'alert_unit',
      'countermeasure_simulated',
    ];
    const list = (responses && responses.length > 0) ? responses : defaultResponses;

    // Format display labels
    const labelMap = {
      'ignore': 'Ignore Contact',
      'log_only': 'Log Only',
      'monitor': 'Monitor Track',
      'report_to_command': 'Report to Command',
      'alert_unit': 'Alert Unit',
      'countermeasure_simulated': 'Countermeasure (Simulated)',
    };

    list.forEach(r => {
      const opt = document.createElement('option');
      opt.value = r;
      opt.textContent = labelMap[r] || r.replace(/_/g, ' ');
      select.appendChild(opt);
    });
  }

  // --- Trainee Session Block Calculation ---
  async function loadTraineePerformance() {
    try {
      const res = await fetch(`${state.apiBase}/trainee/${state.traineeId}/performance`);
      if (res.ok) {
        const data = await res.json();
        const sessions = data.sessions || [];
        state.completedScenariosCount = sessions.length;
        updateSessionBlockDisplay();
      }
    } catch (e) {
      console.warn('Failed to load performance metrics:', e);
    }
  }

  function updateSessionBlockDisplay() {
    const blockNum = Math.floor(state.completedScenariosCount / 8) + 1;
    const scenarioInBlock = (state.completedScenariosCount % 8) + 1;

    const blockEl = document.getElementById('val-session-block');
    if (blockEl) blockEl.textContent = `Session ${blockNum}/6`;
    const stepEl = document.getElementById('val-scenario-step');
    if (stepEl) stepEl.textContent = `Scenario ${scenarioInBlock}/8`;
  }

  // --- Session Launching ---
  async function startAdaptiveSession() {
    try {
      showLoading(true);
      const res = await fetch(`${state.apiBase}/session/next`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trainee_id: state.traineeId }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      state.isAdaptive = true;
      await initSessionData(data.session_id, data.scenario, 'practice');
    } catch (e) {
      alert(`Error launching adaptive session: ${e.message}`);
    } finally {
      showLoading(false);
    }
  }

  async function startTestSession() {
    try {
      showLoading(true);
      const res = await fetch(`${state.apiBase}/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trainee_id: state.traineeId, mode: 'test' }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      state.isAdaptive = false;
      await initSessionData(data.session_id, data.scenario, 'test');
    } catch (e) {
      alert(`Error launching test session: ${e.message}`);
    } finally {
      showLoading(false);
    }
  }

  async function startScriptedSession(scriptedId) {
    try {
      showLoading(true);
      const res = await fetch(`${state.apiBase}/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trainee_id: state.traineeId,
          mode: 'practice',
          scripted_id: scriptedId,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      state.isAdaptive = false;
      closeModals();
      await initSessionData(data.session_id, data.scenario, 'practice');
    } catch (e) {
      alert(`Error launching scripted scenario: ${e.message}`);
    } finally {
      showLoading(false);
    }
  }

  async function initSessionData(sessionId, scenario, mode) {
    state.activeSessionId = sessionId;
    state.scenario = scenario;
    state.factors = scenario.factors || {};
    state.durationS = parseFloat(scenario.duration_s || 60.0);
    state.difficultyIndex = parseFloat(scenario.difficulty_index || 0.5);
    state.mode = mode;

    state.simTime = 0.0;
    state.isPlaying = true;
    state.lastTickTs = performance.now();
    state.assessments = {};
    state.falseAlarms = 0;
    state.selectedObjectId = null;

    // Load MAVLink-style simulated telemetry & visibility windows
    try {
      const telemRes = await fetch(`${state.apiBase}/scenario/${sessionId}/telemetry`);
      if (telemRes.ok) {
        const telemData = await telemRes.json();
        state.telemetryPackets = telemData.packets || [];
        state.visibilityWindows = telemData.visibility_windows || {};
        state.scenarioObjects = telemData.objects || scenario.objects || [];

        // Group packets by object for efficient lookup
        state.packetsByObject = {};
        state.telemetryPackets.forEach(p => {
          if (!state.packetsByObject[p.object_id]) {
            state.packetsByObject[p.object_id] = [];
          }
          state.packetsByObject[p.object_id].push(p);
        });
      } else {
        state.scenarioObjects = scenario.objects || [];
      }
    } catch (_) {
      state.scenarioObjects = scenario.objects || [];
    }

    // Set Sensor Mode in renderers (EO vs Thermal)
    const primarySensor = state.factors.sensor_mode || 'EO';
    if (canvasRenderer) {
      canvasRenderer.setSensorMode(primarySensor);
      if (canvasRenderer.preloadBackground) {
        canvasRenderer.preloadBackground(state.factors.terrain, state.factors.time_of_day);
      }
    }
    updateFeedActiveState(primarySensor);

    // Update UI Indicators
    updateConditionChips();
    updateSidebarStatus();
    renderFlaggedChips();
    resetAssessmentForm();
    updateClockDisplay();

    // Toggle Play/Pause button icons
    const playIcon = document.getElementById('icon-play');
    const pauseIcon = document.getElementById('icon-pause');
    if (playIcon) playIcon.style.display = 'none';
    if (pauseIcon) pauseIcon.style.display = 'block';

    // Hide empty state overlay
    const emptyState = document.getElementById('viewport-empty-state');
    if (emptyState) emptyState.style.display = 'none';
  }

  // --- Condition Chips & Status UI (Phase 3 Distinct Pill Colors) ---
  function updateConditionChips() {
    const tod = (state.factors.time_of_day || 'day').toLowerCase();
    const weather = (state.factors.weather || 'clear').toLowerCase();
    const terrain = (state.factors.terrain || 'open').toLowerCase();
    const degradation = (state.factors.degradation || 'none').toLowerCase();

    // Time pill: day amber, dusk violet, night indigo
    const chipTod = document.getElementById('chip-tod');
    const chipTodVal = document.getElementById('chip-tod-val');
    if (chipTod && chipTodVal) {
      chipTodVal.textContent = capitalize(tod);
      chipTod.className = 'chip ' + (tod === 'night' ? 'pill-indigo' : (tod === 'dusk' ? 'pill-violet' : 'pill-amber'));
    }

    // Weather pill: blue-grey
    const chipWeather = document.getElementById('chip-weather');
    const chipWeatherVal = document.getElementById('chip-weather-val');
    if (chipWeather && chipWeatherVal) {
      chipWeatherVal.textContent = capitalize(weather);
      chipWeather.className = 'chip pill-bluegrey';
    }

    // Terrain pill: slate-green
    const chipTerrain = document.getElementById('chip-terrain');
    const chipTerrainVal = document.getElementById('chip-terrain-val');
    if (chipTerrain && chipTerrainVal) {
      chipTerrainVal.textContent = capitalize(terrain);
      chipTerrain.className = 'chip pill-slategreen';
    }

    // Degradation pill: mild green, moderate amber, severe red
    let degLabel = 'None';
    let degPillClass = 'pill-green';
    if (degradation === 'lag' || degradation === 'noise') {
      degLabel = 'Mild';
      degPillClass = 'pill-green';
    } else if (degradation === 'dropout') {
      degLabel = 'Moderate';
      degPillClass = 'pill-amber';
    } else if (degradation === 'occlusion') {
      degLabel = 'Severe';
      degPillClass = 'pill-red';
    }

    const chipDeg = document.getElementById('chip-degradation');
    const chipDegVal = document.getElementById('chip-degradation-val');
    if (chipDeg && chipDegVal) {
      chipDeg.className = `chip ${degPillClass}`;
      chipDegVal.textContent = degLabel;
    }
  }

  function updateSidebarStatus() {
    const diffVal = state.difficultyIndex < 0.4 ? 'Low' : (state.difficultyIndex < 0.7 ? 'Medium' : 'High');
    const diffEl = document.getElementById('val-difficulty');
    if (diffEl) diffEl.textContent = diffVal;

    const badgeMode = document.getElementById('badge-mode-val');
    if (badgeMode) {
      if (state.mode === 'test') {
        badgeMode.textContent = 'Test Mode';
        badgeMode.style.color = 'var(--violet)';
        badgeMode.style.borderColor = 'var(--violet-border)';
      } else if (state.isAdaptive) {
        badgeMode.textContent = 'Adaptive ON';
        badgeMode.style.color = 'var(--green)';
        badgeMode.style.borderColor = 'var(--green-border)';
      } else {
        badgeMode.textContent = 'Practice';
        badgeMode.style.color = 'var(--blue)';
        badgeMode.style.borderColor = 'var(--blue-border)';
      }
    }
  }

  function updateFeedActiveState(primarySensor) {
    ['eo', 'thermal', 'radar'].forEach(f => {
      const card = document.getElementById(`feed-card-${f}`);
      if (card && card.dataset.mode.toLowerCase() === primarySensor.toLowerCase()) {
        card.classList.add('active-primary');
      } else if (card) {
        card.classList.remove('active-primary');
      }
    });
  }

  // --- Playback & Animation Loop ---
  function animationLoop(ts) {
    if (state.isPlaying && state.activeSessionId && state.lastTickTs !== null) {
      const dt = (ts - state.lastTickTs) / 1000.0;
      state.simTime += dt * state.playbackSpeed;

      if (state.simTime >= state.durationS) {
        state.simTime = state.durationS;
        state.isPlaying = false;
        endSession(); // Auto-submit on scenario duration completion
      }
    }
    state.lastTickTs = ts;

    // Interpolate Active Objects at current simTime
    const currentObjects = interpolateTelemetry(state.simTime);

    // Update Clocks and Progress Bar
    updateClockDisplay();

    // Render Center Canvas, Radar Scope, and Stacked Feeds
    if (canvasRenderer) {
      canvasRenderer.render(
        currentObjects,
        state.simTime,
        state.factors,
        state.visibilityWindows,
        state.selectedObjectId
      );
    }
    if (radarWidget) {
      radarWidget.render(currentObjects, state.simTime);
    }
    if (feedsRenderer) {
      feedsRenderer.render(
        currentObjects,
        state.simTime,
        state.factors,
        state.visibilityWindows,
        state.selectedObjectId
      );
    }

    requestAnimationFrame(animationLoop);
  }

  function interpolateTelemetry(simTime) {
    const result = [];

    state.scenarioObjects.forEach(obj => {
      const oid = obj.id;
      const packets = state.packetsByObject[oid] || [];

      // Find closest packet at or before simTime
      let pkt = null;
      for (let i = 0; i < packets.length; i++) {
        if (packets[i].t <= simTime) {
          pkt = packets[i];
        } else {
          break;
        }
      }

      if (pkt) {
        result.push({
          id: oid,
          appearance: obj.appearance || 'unknown',
          x_m: pkt.x_m,
          y_m: pkt.y_m,
          alt_m: pkt.alt_m,
          speed_mps: pkt.speed_mps,
          heading_deg: pkt.heading_deg,
          detected: !!(state.assessments[oid] && state.assessments[oid].detected),
        });
      }
    });

    return result;
  }

  function updateClockDisplay() {
    const rem = Math.max(0, state.durationS - state.simTime);
    const remEl = document.getElementById('time-remaining-val');
    if (remEl) remEl.textContent = formatSecondsMMSS(rem);

    const currEl = document.getElementById('sim-clock-curr');
    if (currEl) currEl.textContent = formatSecondsClock(state.simTime);

    const totalEl = document.getElementById('sim-clock-total');
    if (totalEl) totalEl.textContent = formatSecondsClock(state.durationS);

    const pct = (state.simTime / (state.durationS || 1)) * 100;
    const barEl = document.getElementById('progress-bar-fill');
    if (barEl) barEl.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  }

  // --- Canvas Interaction: Detection & False Alarms ---
  function setupCanvasClickHandler() {
    const panels = [
      { id: 'main-canvas', type: 'main' },
      { id: 'feed-canvas-eo', type: 'eo' },
      { id: 'feed-canvas-thermal', type: 'thermal' },
      { id: 'feed-canvas-radar', type: 'radar' },
      { id: 'radar-widget-canvas', type: 'radar-widget' },
    ];

    panels.forEach(({ id, type }) => {
      const el = document.getElementById(id);
      if (!el) return;

      el.addEventListener('click', (e) => {
        if (!state.activeSessionId) return;

        const rect = el.getBoundingClientRect();
        const scaleX = rect.width > 0 ? (el.width / rect.width) : 1;
        const scaleY = rect.height > 0 ? (el.height / rect.height) : 1;
        const clickX = (e.clientX - rect.left) * scaleX;
        const clickY = (e.clientY - rect.top) * scaleY;

        let hitObj = null;

        if (type === 'main') {
          hitObj = canvasRenderer.detectAtScreenCoord(clickX, clickY);
        } else if (window.DroneDrillSim && window.DroneDrillSim.hitTestPanel) {
          const active = interpolateTelemetry(state.simTime);
          hitObj = window.DroneDrillSim.hitTestPanel(
            type,
            clickX,
            clickY,
            el.width,
            el.height,
            active,
            state.simTime,
            state.visibilityWindows,
            state.selectedObjectId,
            state.factors
          );
        }

        if (hitObj) {
          // Successful Detection Event
          const oid = hitObj.id;
          if (!state.assessments[oid]) {
            state.assessments[oid] = {
              object_id: oid,
              detected: true,
              detect_time_s: Math.round(state.simTime * 100) / 100,
              classified_as: null,
              threat_level_rated: null,
              response_chosen: null,
              confidence: 0.75,
              submitted: false,
            };
          }
          selectObjectForAssessment(oid);
          renderFlaggedChips();
        } else {
          // Empty Click -> False Alarm Event
          state.falseAlarms++;
          flashFalseAlarm();
        }
      });
    });
  }

  function flashFalseAlarm() {
    const statusBox = document.getElementById('detect-status-box');
    const statusText = document.getElementById('detect-status-text');
    if (statusBox) {
      statusBox.style.borderColor = 'var(--red)';
      statusBox.style.color = 'var(--red)';
    }
    if (statusText) statusText.textContent = `Empty Sky: False Alarm Recorded (${state.falseAlarms})`;

    setTimeout(() => {
      if (!state.selectedObjectId) {
        if (statusBox) {
          statusBox.style.borderColor = '';
          statusBox.style.color = '';
        }
        if (statusText) statusText.textContent = 'Click contact on screen to detect';
      } else {
        if (statusBox) {
          statusBox.style.borderColor = 'var(--green)';
          statusBox.style.color = 'var(--green)';
        }
        if (statusText && state.assessments[state.selectedObjectId]) {
          statusText.textContent = `Contact Detected at t=${state.assessments[state.selectedObjectId].detect_time_s}s`;
        }
      }
    }, 1200);
  }

  // --- Assessment Form Management ---
  function selectObjectForAssessment(objectId) {
    state.selectedObjectId = objectId;
    const a = state.assessments[objectId];
    if (!a) return;

    // 1. Detect Box Active
    const statusBox = document.getElementById('detect-status-box');
    if (statusBox) {
      statusBox.classList.remove('dormant');
      statusBox.style.borderColor = 'var(--green)';
      statusBox.style.color = 'var(--green)';
    }
    const statusText = document.getElementById('detect-status-text');
    if (statusText) statusText.textContent = `Target Detected at t=${a.detect_time_s}s`;

    // Unlock Steps 2-5
    ['step-2-classify', 'step-3-threat', 'step-4-response', 'step-5-confidence'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.add('unlocked');
    });

    // Populate classification buttons
    document.querySelectorAll('#classify-grid .opt-btn').forEach(btn => {
      btn.disabled = false;
      if (a.classified_as && btn.dataset.class === a.classified_as) {
        btn.classList.add('selected');
      } else {
        btn.classList.remove('selected');
      }
    });

    // Populate threat rating buttons (Benign green, Low blue, Elevated amber, High red)
    document.querySelectorAll('#threat-grid .threat-btn').forEach(btn => {
      btn.disabled = false;
      if (a.threat_level_rated !== null && a.threat_level_rated !== undefined && parseInt(btn.dataset.val) === a.threat_level_rated) {
        btn.classList.add('selected');
      } else {
        btn.classList.remove('selected');
      }
    });

    // Populate response dropdown (empty / Select response... until chosen)
    const respSelect = document.getElementById('response-select');
    if (respSelect) {
      respSelect.disabled = false;
      respSelect.value = a.response_chosen || '';
    }

    // Populate confidence slider
    const confSlider = document.getElementById('confidence-slider');
    if (confSlider) {
      confSlider.disabled = false;
      const cVal = (a.confidence !== null && a.confidence !== undefined) ? a.confidence : 0.75;
      confSlider.value = Math.round(cVal * 100);
      const confText = document.getElementById('confidence-val-text');
      if (confText) confText.textContent = `${confSlider.value}%`;
    }

    // Submit button
    const btnSubmit = document.getElementById('btn-submit-assessment');
    if (btnSubmit) btnSubmit.disabled = false;

    const badge = document.getElementById('assessment-status-badge');
    if (badge) badge.textContent = a.submitted ? 'Assessed' : 'Assessing Contact';

    renderFlaggedChips();
  }

  function resetAssessmentForm() {
    state.selectedObjectId = null;
    const statusBox = document.getElementById('detect-status-box');
    if (statusBox) {
      statusBox.classList.add('dormant');
      statusBox.style.borderColor = '';
      statusBox.style.color = '';
    }
    const statusText = document.getElementById('detect-status-text');
    if (statusText) statusText.textContent = 'Click contact on screen to detect';

    ['step-2-classify', 'step-3-threat', 'step-4-response', 'step-5-confidence'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.remove('unlocked');
    });

    document.querySelectorAll('#classify-grid .opt-btn').forEach(btn => {
      btn.disabled = true;
      btn.classList.remove('selected');
    });
    document.querySelectorAll('#threat-grid .threat-btn').forEach(btn => {
      btn.disabled = true;
      btn.classList.remove('selected');
    });
    const respSelect = document.getElementById('response-select');
    if (respSelect) {
      respSelect.disabled = true;
      respSelect.value = '';
    }
    const confSlider = document.getElementById('confidence-slider');
    if (confSlider) {
      confSlider.disabled = true;
      confSlider.value = 50;
    }
    const confText = document.getElementById('confidence-val-text');
    if (confText) confText.textContent = '--%';

    const btnSubmit = document.getElementById('btn-submit-assessment');
    if (btnSubmit) btnSubmit.disabled = true;

    const badge = document.getElementById('assessment-status-badge');
    if (badge) badge.textContent = 'Standby';
  }

  function renderFlaggedChips() {
    const container = document.getElementById('flagged-chips-list');
    if (!container) return;
    const objectIds = Object.keys(state.assessments);

    if (objectIds.length === 0) {
      container.innerHTML = '<span style="font-size: 11px; color: var(--muted);">No objects detected yet</span>';
      return;
    }

    container.innerHTML = '';
    objectIds.forEach((oid, idx) => {
      const chip = document.createElement('div');
      chip.className = `flag-chip ${oid === state.selectedObjectId ? 'selected' : ''} ${state.assessments[oid].submitted ? 'assessed' : ''}`;
      chip.textContent = `Contact ${idx + 1}`;
      chip.addEventListener('click', () => selectObjectForAssessment(oid));
      container.appendChild(chip);
    });
  }

  // --- Session Evaluation Submission ---
  async function endSession() {
    if (!state.activeSessionId) return;

    state.isPlaying = false;
    showLoading(true);

    try {
      // Canonical label mappings matching backend
      const classMap = {
        'multirotor drone': 'multirotor',
        'multirotor': 'multirotor',
        'fixed-wing uav': 'fixed_wing_uav',
        'fixed wing uav': 'fixed_wing_uav',
        'fixed_wing': 'fixed_wing_uav',
        'fixed_wing_uav': 'fixed_wing_uav',
        'bird': 'bird',
        'balloon': 'balloon',
        'aircraft': 'light_aircraft',
        'light aircraft': 'light_aircraft',
        'light_aircraft': 'light_aircraft',
        'unknown': 'unknown',
      };
      const threatMap = {
        'benign': 0,
        'low': 1,
        'elevated': 2,
        'high': 3,
        0: 0,
        1: 1,
        2: 2,
        3: 3,
        '0': 0,
        '1': 1,
        '2': 2,
        '3': 3,
      };
      const responseMap = {
        'ignore contact': 'ignore',
        'ignore': 'ignore',
        'log only': 'log_only',
        'log_only': 'log_only',
        'monitor track': 'monitor',
        'monitor': 'monitor',
        'report to command': 'report_to_command',
        'report_to_command': 'report_to_command',
        'alert unit': 'alert_unit',
        'alert_unit': 'alert_unit',
        'countermeasure (simulated)': 'countermeasure_simulated',
        'countermeasure simulated': 'countermeasure_simulated',
        'countermeasure': 'countermeasure_simulated',
        'countermeasure_simulated': 'countermeasure_simulated',
      };

      // Build events list for every scenario object
      const events = state.scenarioObjects.map(obj => {
        const a = state.assessments[obj.id];
        if (a && a.detected) {
          const rawCls = a.classified_as ? String(a.classified_as).trim().toLowerCase() : null;
          const mappedCls = rawCls ? (classMap[rawCls] || rawCls) : null;

          const rawThreat = a.threat_level_rated !== null && a.threat_level_rated !== undefined
            ? (typeof a.threat_level_rated === 'string' ? a.threat_level_rated.trim().toLowerCase() : a.threat_level_rated)
            : null;
          const mappedThreat = rawThreat !== null ? (threatMap[rawThreat] !== undefined ? threatMap[rawThreat] : rawThreat) : null;

          const rawResp = a.response_chosen ? String(a.response_chosen).trim().toLowerCase() : null;
          const mappedResp = rawResp ? (responseMap[rawResp] || rawResp) : null;

          let conf = a.confidence;
          if (conf !== null && conf !== undefined) {
            conf = parseFloat(conf);
            if (isNaN(conf) || !isFinite(conf)) conf = 0.5;
            else if (conf > 1.0 && conf <= 100.0) conf = conf / 100.0;
            conf = Math.max(0.0, Math.min(1.0, conf));
          } else {
            conf = null;
          }

          let dt = a.detect_time_s;
          if (dt !== null && dt !== undefined) {
            dt = parseFloat(dt);
            if (isNaN(dt) || !isFinite(dt) || dt < 0) dt = 0.0;
          } else {
            dt = null;
          }

          return {
            object_id: obj.id,
            detected: true,
            detect_time_s: dt,
            classified_as: mappedCls,
            threat_level_rated: mappedThreat,
            response_chosen: mappedResp,
            confidence: conf,
          };
        } else {
          return {
            object_id: obj.id,
            detected: false,
            detect_time_s: null,
            classified_as: null,
            threat_level_rated: null,
            response_chosen: null,
            confidence: null,
          };
        }
      });

      const res = await fetch(`${state.apiBase}/session/result`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: state.activeSessionId,
          events: events,
          false_alarms: state.falseAlarms,
        }),
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText);
      }
      const resultData = await res.json();

      // Show Results Modal
      displayResultsModal(resultData);
      state.completedScenariosCount++;
      updateSessionBlockDisplay();
    } catch (e) {
      // Show request errors inside the popup modal instead of alert()
      displayResultsModal(null, e.message);
    } finally {
      showLoading(false);
    }
  }

  function displayResultsModal(res, errorMsg = null) {
    if (window.DroneDrillSim && window.DroneDrillSim.showResultsModal) {
      window.DroneDrillSim.showResultsModal(res, errorMsg);
      return;
    }

    const modal = document.getElementById('modal-results');
    const errBox = document.getElementById('results-error-msg');

    if (errorMsg) {
      if (errBox) {
        let displayMsg = errorMsg;
        try {
          const parsed = typeof errorMsg === 'string' ? JSON.parse(errorMsg) : errorMsg;
          displayMsg = parsed.detail || parsed.error || parsed.message || errorMsg;
        } catch (_) {}
        errBox.textContent = `Request Failed: ${displayMsg}`;
        errBox.style.display = 'block';
      }
      const ovEl = document.getElementById('result-overall-score');
      if (ovEl) ovEl.textContent = '--%';
    } else {
      if (errBox) errBox.style.display = 'none';

      const overall = (res.overall_score !== null && res.overall_score !== undefined)
        ? res.overall_score
        : res.overall;
      const ovEl = document.getElementById('result-overall-score');
      if (ovEl) ovEl.textContent = formatScoreVal(overall);

      const det = (res.detection_score !== undefined && res.detection_score !== null)
        ? res.detection_score
        : (res.detection && typeof res.detection === 'object' ? res.detection.score : null);
      const cls = (res.classification_score !== undefined && res.classification_score !== null)
        ? res.classification_score
        : (res.classification && typeof res.classification === 'object' ? res.classification.score : null);
      const dec = (res.decision_score !== undefined && res.decision_score !== null)
        ? res.decision_score
        : (res.decision && typeof res.decision === 'object' ? res.decision.score : null);
      const time = (res.timeliness_score !== undefined && res.timeliness_score !== null)
        ? res.timeliness_score
        : (res.timeliness && typeof res.timeliness === 'object' ? res.timeliness.score : null);
      const cal = (res.calibration_score !== undefined && res.calibration_score !== null)
        ? res.calibration_score
        : (res.calibration && typeof res.calibration === 'object' ? res.calibration.score : null);

      const detEl = document.getElementById('skill-val-detection');
      if (detEl) detEl.textContent = formatScoreVal(det);
      const clsEl = document.getElementById('skill-val-classification');
      if (clsEl) clsEl.textContent = formatScoreVal(cls);
      const decEl = document.getElementById('skill-val-decision');
      if (decEl) decEl.textContent = formatScoreVal(dec);
      const timeEl = document.getElementById('skill-val-timeliness');
      if (timeEl) timeEl.textContent = formatScoreVal(time);
      const calEl = document.getElementById('skill-val-calibration');
      if (calEl) calEl.textContent = formatScoreVal(cal);
    }

    if (modal) modal.classList.add('active');
  }

  // --- AAR Modal ---
  async function openAARModal(sessionId) {
    const targetSessionId = sessionId || state.activeSessionId;
    if (!targetSessionId) {
      alert('No active or recent session to review.');
      return;
    }

    const modalAAR = document.getElementById('modal-aar');
    const modalBody = document.getElementById('aar-modal-body');
    if (modalAAR) modalAAR.classList.add('active');

    try {
      if (window.DroneDrillAAR && modalBody) {
        window.DroneDrillAAR.renderLoading(modalBody);
      }
      const res = await fetch(`${state.apiBase}/aar/${targetSessionId}`);
      if (!res.ok) throw new Error(await res.text());
      const aar = await res.json();

      if (window.DroneDrillAAR && modalBody) {
        window.DroneDrillAAR.renderAAR(modalBody, aar, {
          isModal: true,
          onCloseModal: () => closeModals(),
          onNextScenario: () => {
            closeModals();
            startAdaptiveSession();
          },
          onOpenFullPage: (sid) => {
            window.location.href = `aar.html?session=${encodeURIComponent(sid)}`;
          },
        });
      }
    } catch (e) {
      if (window.DroneDrillAAR && modalBody) {
        window.DroneDrillAAR.renderError(modalBody, e.message, () => openAARModal(targetSessionId));
      }
    }
  }

  // --- Scripted Scenarios Modal ---
  async function openScenariosLibrary() {
    try {
      showLoading(true);
      const res = await fetch(`${state.apiBase}/scenarios`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      const container = document.getElementById('scenarios-list-container');
      if (container) {
        container.innerHTML = '';
        (data.scenarios || []).forEach(scen => {
          const item = document.createElement('div');
          item.className = 'scenario-pick-item';
          item.style.padding = '12px';
          item.style.background = 'var(--panel-2)';
          item.style.border = '1px solid var(--border)';
          item.style.borderRadius = '8px';
          item.style.marginBottom = '8px';
          item.style.cursor = 'pointer';
          item.innerHTML = `
            <div style="font-weight: 700; font-size: 13px; color: var(--text);">${scen.title}</div>
            <div style="font-size: 11px; color: var(--muted); margin-top: 2px;">${scen.description}</div>
            <div style="margin-top: 6px; font-size: 10px; color: var(--blue);">Difficulty: ${(scen.difficulty_index * 100).toFixed(0)}% | Objects: ${scen.object_count}</div>
          `;
          item.addEventListener('click', () => startScriptedSession(scen.id));
          container.appendChild(item);
        });
      }

      const modal = document.getElementById('modal-scenarios');
      if (modal) modal.classList.add('active');
    } catch (e) {
      alert(`Error loading scenarios library: ${e.message}`);
    } finally {
      showLoading(false);
    }
  }

  // --- UI Event Listeners ---
  function setupEventListeners() {
    // Top & Empty Viewport Action Buttons
    safeAddListener('btn-start-next', 'click', startAdaptiveSession);
    safeAddListener('btn-start-test', 'click', startTestSession);
    safeAddListener('btn-open-scenarios', 'click', openScenariosLibrary);
    safeAddListener('btn-end-session', 'click', endSession);

    // Fullscreen Controller
    initFullscreen();

    // Sidebar Navigation
    safeAddListener('nav-btn-training', 'click', () => closeModals());
    safeAddListener('nav-btn-scenarios', 'click', openScenariosLibrary);
    safeAddListener('nav-btn-aar', 'click', () => {
      window.location.href = state.activeSessionId ? `aar.html?session=${state.activeSessionId}` : 'aar.html';
    });
    safeAddListener('nav-btn-skills', 'click', () => {
      window.location.href = 'skills.html';
    });
    safeAddListener('nav-btn-instructor', 'click', () => {
      window.location.href = 'instructor.html';
    });

    // Classification option buttons
    document.querySelectorAll('#classify-grid .opt-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (!state.selectedObjectId) return;
        document.querySelectorAll('#classify-grid .opt-btn').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
        if (state.assessments[state.selectedObjectId]) {
          state.assessments[state.selectedObjectId].classified_as = btn.dataset.class;
        }
      });
    });

    // Threat level buttons (Benign, Low, Elevated, High)
    document.querySelectorAll('#threat-grid .threat-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (!state.selectedObjectId) return;
        document.querySelectorAll('#threat-grid .threat-btn').forEach(b => b.classList.remove('selected'));
        btn.classList.add('selected');
        if (state.assessments[state.selectedObjectId]) {
          state.assessments[state.selectedObjectId].threat_level_rated = parseInt(btn.dataset.val);
        }
      });
    });

    // Response select dropdown
    const respSelect = document.getElementById('response-select');
    if (respSelect) {
      respSelect.addEventListener('change', (e) => {
        if (!state.selectedObjectId) return;
        if (state.assessments[state.selectedObjectId]) {
          state.assessments[state.selectedObjectId].response_chosen = e.target.value;
        }
      });
    }

    // Confidence slider
    const confSlider = document.getElementById('confidence-slider');
    if (confSlider) {
      confSlider.addEventListener('input', (e) => {
        const val = parseInt(e.target.value);
        const confText = document.getElementById('confidence-val-text');
        if (confText) confText.textContent = `${val}%`;
        if (state.selectedObjectId && state.assessments[state.selectedObjectId]) {
          state.assessments[state.selectedObjectId].confidence = val / 100.0;
        }
      });
    }

    // Submit assessment for current object
    safeAddListener('btn-submit-assessment', 'click', () => {
      if (!state.selectedObjectId || !state.assessments[state.selectedObjectId]) return;
      state.assessments[state.selectedObjectId].submitted = true;
      renderFlaggedChips();
      const badge = document.getElementById('assessment-status-badge');
      if (badge) badge.textContent = 'Assessed';
    });

    // Playback controls (Play/Pause)
    const playPauseBtn = document.getElementById('btn-play-pause');
    if (playPauseBtn) {
      playPauseBtn.addEventListener('click', () => {
        state.isPlaying = !state.isPlaying;
        if (state.isPlaying) {
          state.lastTickTs = performance.now();
        }
        const playIcon = document.getElementById('icon-play');
        const pauseIcon = document.getElementById('icon-pause');
        if (playIcon) playIcon.style.display = state.isPlaying ? 'none' : 'block';
        if (pauseIcon) pauseIcon.style.display = state.isPlaying ? 'block' : 'none';
      });
    }

    // Speed Toggle Button
    const speedBtn = document.getElementById('btn-speed-toggle');
    if (speedBtn) {
      speedBtn.addEventListener('click', () => {
        state.playbackSpeed = state.playbackSpeed === 1.0 ? 2.0 : 1.0;
        speedBtn.textContent = `${state.playbackSpeed}x`;
        speedBtn.classList.toggle('active', state.playbackSpeed > 1.0);
      });
    }

    // Stacked / PIP Feed Clicks: click tile to swap into main view; click again to restore base scenario sensor
    ['eo', 'thermal', 'radar'].forEach(mode => {
      const card = document.getElementById(`feed-card-${mode}`);
      if (card) {
        card.addEventListener('click', () => {
          const m = card.dataset.mode;
          const currentMode = canvasRenderer ? canvasRenderer.activeSensorMode : 'EO';
          const defaultSensor = (state.factors && state.factors.sensor) || 'EO';
          const targetMode = (currentMode && currentMode.toLowerCase() === m.toLowerCase()) ? defaultSensor : m;
          if (canvasRenderer) canvasRenderer.setSensorMode(targetMode);
          updateFeedActiveState(targetMode);
        });
      }
    });

    // Modal Close buttons
    safeAddListener('btn-close-results', 'click', closeModals);
    safeAddListener('btn-close-scenarios', 'click', closeModals);
    safeAddListener('btn-close-aar', 'click', closeModals);

    safeAddListener('btn-modal-aar', 'click', () => {
      closeModals();
      openAARModal(state.activeSessionId);
    });
    safeAddListener('btn-modal-next', 'click', () => {
      closeModals();
      startAdaptiveSession();
    });
  }

  // --- Fullscreen Manager (Supports Fullscreen API and CSS Fallback) ---
  function initFullscreen() {
    const root = document.getElementById('simulator-root');
    const toggleBtn = document.getElementById('btn-toggle-fullscreen');
    const iconEnter = document.getElementById('icon-fs-enter');
    const iconExit = document.getElementById('icon-fs-exit');
    const labelFs = document.getElementById('label-fullscreen');

    function isFullscreenActive() {
      return !!(document.fullscreenElement || (root && root.classList.contains('sim-fullscreen')));
    }

    function updateFullscreenUI(active) {
      if (root) {
        root.classList.toggle('sim-fullscreen', active);
      }
      if (iconEnter) iconEnter.style.display = active ? 'none' : 'block';
      if (iconExit) iconExit.style.display = active ? 'block' : 'none';
      if (labelFs) labelFs.textContent = active ? 'Exit (Esc)' : 'Fullscreen (F)';
      if (toggleBtn) {
        toggleBtn.title = active ? 'Exit Fullscreen (Esc or F)' : 'Enter Fullscreen (F)';
        toggleBtn.classList.toggle('active', active);
      }

      // Resize canvas to fill new viewport geometry without losing session
      setTimeout(() => {
        if (canvasRenderer && typeof canvasRenderer.resize === 'function') {
          canvasRenderer.resize();
        }
      }, 60);
    }

    async function toggleFullscreen() {
      if (!root) return;
      if (!isFullscreenActive()) {
        try {
          if (root.requestFullscreen) {
            await root.requestFullscreen();
          } else if (root.webkitRequestFullscreen) {
            await root.webkitRequestFullscreen();
          } else {
            updateFullscreenUI(true);
          }
        } catch (err) {
          console.warn('Fullscreen API error, using CSS fallback:', err);
          updateFullscreenUI(true);
        }
      } else {
        try {
          if (document.fullscreenElement && document.exitFullscreen) {
            await document.exitFullscreen();
          } else {
            updateFullscreenUI(false);
          }
        } catch (err) {
          updateFullscreenUI(false);
        }
      }
    }

    if (toggleBtn) {
      toggleBtn.addEventListener('click', toggleFullscreen);
    }

    // Keyboard shortcuts: F key toggles fullscreen; Esc exits
    document.addEventListener('keydown', (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT')) {
        return;
      }
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        toggleFullscreen();
      } else if (e.key === 'Escape' && isFullscreenActive()) {
        if (!document.fullscreenElement) {
          updateFullscreenUI(false);
        }
      }
    });

    document.addEventListener('fullscreenchange', () => {
      const active = (document.fullscreenElement === root);
      updateFullscreenUI(active);
    });
    document.addEventListener('webkitfullscreenchange', () => {
      const active = (document.webkitFullscreenElement === root);
      updateFullscreenUI(active);
    });
  }

  function closeModals() {
    document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
  }

  function showLoading(show) {
    document.body.style.cursor = show ? 'wait' : 'default';
  }

  // --- Utility Helpers ---
  function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  function formatSecondsMMSS(sec) {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  }

  function formatSecondsClock(sec) {
    const m = Math.floor(sec / 60);
    const s = (sec % 60).toFixed(1);
    return `${m.toString().padStart(2, '0')}:${s.padStart(4, '0')}`;
  }

  function formatScoreVal(v) {
    return (v !== null && v !== undefined && !isNaN(v)) ? `${Math.round(v * 100)}%` : '--';
  }

  // --- Debug URL Frame Renderer (?terrain=urban&time=night&weather=fog&sensor=EO&demo=1) ---
  function checkDebugUrl() {
    const params = new URLSearchParams(window.location.search);
    const isDemo = (params.get('demo') === '1');
    const hasDebug = isDemo || params.has('terrain') || params.has('time') || params.has('tod') || params.has('weather') || params.has('sensor');
    if (!hasDebug) return false;

    const terrain = (params.get('terrain') || 'urban').toLowerCase();
    const tod = (params.get('time') || params.get('tod') || 'night').toLowerCase();
    const weather = (params.get('weather') || 'fog').toLowerCase();
    const degradation = (params.get('degradation') || 'none').toLowerCase();
    const sensorMode = params.get('sensor') || 'EO';
    const flaggedParam = params.get('flagged');

    state.activeSessionId = 'debug_demo_frame';
    state.mode = 'practice';
    state.durationS = 120.0;
    state.simTime = 5.0;
    state.isPlaying = true;
    state.lastTickTs = performance.now();
    state.factors = {
      terrain: terrain,
      time_of_day: tod,
      weather: weather,
      degradation: degradation,
      sensor_mode: sensorMode,
      distractors: 'birds',
    };

    populateResponseDropdown([]);

    if (canvasRenderer) {
      canvasRenderer.setSensorMode(sensorMode);
      if (canvasRenderer.preloadBackground) {
        canvasRenderer.preloadBackground(state.factors.terrain, state.factors.time_of_day);
      }
    }

    // Demo contacts comfortably placed in safe sky rectangle
    state.scenarioObjects = [
      { id: 'demo_multirotor', appearance: 'multirotor', true_class: 'multirotor', true_threat_level: 3 },
      { id: 'demo_fixed_wing', appearance: 'fixed_wing_uav', true_class: 'fixed_wing_uav', true_threat_level: 2 },
      { id: 'demo_bird', appearance: 'bird', true_class: 'bird', true_threat_level: 0 },
      { id: 'demo_aircraft', appearance: 'light_aircraft', true_class: 'light_aircraft', true_threat_level: 1 },
      { id: 'demo_balloon', appearance: 'balloon', true_class: 'balloon', true_threat_level: 1 },
    ];

    state.packetsByObject = {
      demo_multirotor: [],
      demo_fixed_wing: [],
      demo_bird: [],
      demo_aircraft: [],
      demo_balloon: [],
    };

    for (let t = 0; t <= 120; t += 0.2) {
      // Primary multirotor: hovered in clear center-left sky
      state.packetsByObject.demo_multirotor.push({
        t: t,
        x_m: -60 + Math.sin(t * 0.25) * 40,
        y_m: 850 + Math.cos(t * 0.15) * 30,
        alt_m: 145 + Math.sin(t * 0.3) * 8,
        speed_mps: 8,
        heading_deg: 70,
      });

      // Fixed wing: high-speed flight
      state.packetsByObject.demo_fixed_wing.push({
        t: t,
        x_m: 160 + Math.cos(t * 0.3) * 80,
        y_m: 1100 + Math.sin(t * 0.2) * 50,
        alt_m: 210 + Math.sin(t * 0.15) * 12,
        speed_mps: 26,
        heading_deg: 240,
      });

      // Bird: flapping flight
      state.packetsByObject.demo_bird.push({
        t: t,
        x_m: 240 + Math.sin(t * 0.5) * 30,
        y_m: 650 + Math.cos(t * 0.4) * 20,
        alt_m: 90 + Math.sin(t * 0.8) * 10,
        speed_mps: 12,
        heading_deg: 115,
      });

      // Aircraft: distant high altitude
      state.packetsByObject.demo_aircraft.push({
        t: t,
        x_m: -220 + Math.sin(t * 0.12) * 60,
        y_m: 1550 + Math.cos(t * 0.08) * 40,
        alt_m: 280 + Math.sin(t * 0.05) * 8,
        speed_mps: 42,
        heading_deg: 90,
      });

      // Balloon: slow wind drift
      state.packetsByObject.demo_balloon.push({
        t: t,
        x_m: -150 + Math.sin(t * 0.04) * 15,
        y_m: 980 + (t * 0.2),
        alt_m: 175 + Math.sin(t * 0.06) * 5,
        speed_mps: 2,
        heading_deg: 10,
      });
    }

    // Flag contact only if explicitly requested
    if (flaggedParam && flaggedParam !== 'false') {
      const flaggedId = (flaggedParam !== 'true') ? flaggedParam : 'demo_multirotor';
      state.selectedObjectId = flaggedId;
      state.assessments[flaggedId] = {
        object_id: flaggedId,
        detected: true,
        detect_time_s: 3.5,
        classified_as: null,
        threat_level_rated: null,
        response_chosen: null,
        confidence: 0.75,
        submitted: false,
      };
      selectObjectForAssessment(flaggedId);
    } else {
      resetAssessmentForm();
    }

    const emptyState = document.getElementById('viewport-empty-state');
    if (emptyState) emptyState.style.display = 'none';

    updateConditionChips();
    updateSidebarStatus();
    renderFlaggedChips();
    updateFeedActiveState(sensorMode);

    const modeBadge = document.getElementById('badge-mode-val');
    if (modeBadge) modeBadge.textContent = 'DEMO FRAME';

    const diffVal = document.getElementById('val-difficulty');
    if (diffVal) diffVal.textContent = `${terrain.toUpperCase()} · ${tod.toUpperCase()}`;

    return true;
  }

})();
