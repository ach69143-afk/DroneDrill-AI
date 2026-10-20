// DroneDrill AI - After Action Review (AAR) Page Controller
// Connects session history picker and loads data into DroneDrillAAR renderer

(function () {
  'use strict';

  const apiBase = (window.CONFIG && window.CONFIG.API_BASE) || 'http://127.0.0.1:8000';
  const traineeId = (window.CONFIG && window.CONFIG.TRAINEE_ID) || 'demo_trainee_01';

  let currentSessionId = null;

  window.addEventListener('DOMContentLoaded', async () => {
    const urlParams = new URLSearchParams(window.location.search);
    const querySessionId = urlParams.get('session');

    setupPrintButton();
    await initSessionPicker(querySessionId);
  });

  function setupPrintButton() {
    const btn = document.getElementById('btn-print-aar');
    if (btn) {
      btn.addEventListener('click', () => window.print());
    }
  }

  async function initSessionPicker(preferredSessionId) {
    const select = document.getElementById('session-select');
    const container = document.getElementById('aar-page-container');

    try {
      if (window.DroneDrillAAR && container) {
        window.DroneDrillAAR.renderLoading(container);
      }

      const res = await fetch(`${apiBase}/trainee/${traineeId}/performance`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const sessions = data.sessions || [];

      if (sessions.length === 0) {
        select.innerHTML = '<option value="">No completed sessions found</option>';
        if (window.DroneDrillAAR && container) {
          window.DroneDrillAAR.renderEmpty(container, 'No completed training sessions found in database. Complete a scenario in the simulator first.');
        }
        return;
      }

      select.innerHTML = '';
      // Reverse to show most recent first
      const revSessions = [...sessions].reverse();

      revSessions.forEach((s, idx) => {
        const opt = document.createElement('option');
        opt.value = s.session_id;
        const scorePct = s.overall !== null ? `${Math.round(s.overall * 100)}%` : '--';
        const dateStr = s.date ? String(s.date).substring(0, 10) : '';
        opt.textContent = `Session ${sessions.length - idx} (${s.mode || 'practice'}) - Score: ${scorePct} [${s.session_id.substring(0, 8)}] ${dateStr}`;
        select.appendChild(opt);
      });

      // Select preferred or first
      if (preferredSessionId && sessions.some(s => s.session_id === preferredSessionId)) {
        select.value = preferredSessionId;
      } else {
        select.value = revSessions[0].session_id;
      }

      currentSessionId = select.value;
      select.addEventListener('change', (e) => {
        currentSessionId = e.target.value;
        loadAARData(currentSessionId);
      });

      if (currentSessionId) {
        await loadAARData(currentSessionId);
      }
    } catch (e) {
      console.error('Failed to load session history:', e);
      const banner = document.getElementById('api-banner');
      if (banner) banner.classList.add('active');
      if (window.DroneDrillAAR && container) {
        window.DroneDrillAAR.renderError(container, e.message, () => initSessionPicker(preferredSessionId));
      }
    }
  }

  async function loadAARData(sessionId) {
    if (!sessionId) return;
    const container = document.getElementById('aar-page-container');

    try {
      if (window.DroneDrillAAR && container) {
        window.DroneDrillAAR.renderLoading(container);
      }

      const res = await fetch(`${apiBase}/aar/${sessionId}`);
      if (!res.ok) throw new Error(await res.text());
      const aar = await res.json();

      // Update sidebar session review box
      const scoreVal = aar.overall_score !== null && aar.overall_score !== undefined
        ? `${Math.round(aar.overall_score * 100)}%`
        : '--%';
      const overallEl = document.getElementById('aar-overall-score');
      if (overallEl) overallEl.textContent = scoreVal;
      const traineeEl = document.getElementById('aar-trainee-id');
      if (traineeEl) traineeEl.textContent = aar.trainee_id || traineeId;

      // Render full unified AAR
      if (window.DroneDrillAAR && container) {
        window.DroneDrillAAR.renderAAR(container, aar, { isModal: false });
      }
    } catch (e) {
      console.error('Failed to load AAR data:', e);
      if (window.DroneDrillAAR && container) {
        window.DroneDrillAAR.renderError(container, e.message, () => loadAARData(sessionId));
      }
    }
  }

  // Legacy backward-compatible export for timeline rendering delegated to DroneDrillAAR
  window.renderTimelineSVG = function (container, aar) {
    if (window.DroneDrillAAR) {
      window.DroneDrillAAR.renderAAR(container || document.getElementById('aar-page-container'), aar);
    }
  };

})();
