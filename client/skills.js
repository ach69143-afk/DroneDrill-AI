// DroneDrill AI - Skill Profile & Analytics Screen Logic
// SIH 2026, PS 26247, Team NexxGenX

(function () {
  'use strict';

  const apiBase = (window.CONFIG && window.CONFIG.API_BASE) || 'http://127.0.0.1:8000';
  let activeTraineeId = (window.CONFIG && window.CONFIG.TRAINEE_ID) || 'demo_trainee_01';
  let allTrainees = [];

  const FACTOR_COLUMNS = [
    { factor: 'time_of_day', levels: ['day', 'dusk', 'night'] },
    { factor: 'weather', levels: ['clear', 'haze', 'fog', 'rain', 'dust'] },
    { factor: 'terrain', levels: ['open', 'urban', 'forest', 'hills'] },
    { factor: 'sensor_mode', levels: ['EO', 'thermal'] },
    { factor: 'degradation', levels: ['none', 'noise', 'lag', 'dropout', 'occlusion'] },
    { factor: 'distractors', levels: ['none', 'birds', 'clutter'] },
  ];

  const SKILL_ROWS = ['detection', 'classification', 'decision', 'timeliness', 'calibration'];

  window.addEventListener('DOMContentLoaded', async () => {
    await initTraineeSelector();
    await loadTraineeData(activeTraineeId);
  });

  async function initTraineeSelector() {
    const sel = document.getElementById('trainee-select');
    try {
      const res = await fetch(`${apiBase}/trainees`);
      if (!res.ok) throw new Error(await res.text());
      allTrainees = await res.json();

      sel.innerHTML = '';
      allTrainees.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.id;
        opt.textContent = t.is_demo ? `${t.name} [DEMO]` : t.name;
        if (t.id === activeTraineeId) opt.selected = true;
        sel.appendChild(opt);
      });

      sel.addEventListener('change', (e) => {
        activeTraineeId = e.target.value;
        if (window.CONFIG) window.CONFIG.TRAINEE_ID = activeTraineeId;
        loadTraineeData(activeTraineeId);
      });

      updateDemoBadge(activeTraineeId);
    } catch (e) {
      console.error('Failed to load trainees list:', e);
      document.getElementById('api-banner').classList.add('active');
    }
  }

  function updateDemoBadge(tid) {
    const t = allTrainees.find(item => item.id === tid);
    const badge = document.getElementById('demo-badge-indicator');
    if (t && t.is_demo) {
      badge.style.display = 'inline-flex';
    } else {
      badge.style.display = 'none';
    }
  }

  async function loadTraineeData(tid) {
    updateDemoBadge(tid);
    await Promise.all([
      loadSkillsMatrix(tid),
      loadPerformanceTrend(tid),
      loadGeneralizationAndCoverage(tid),
      loadAdaptivePlan(tid),
    ]);
  }

  // 1. Skill Matrix Heatmap
  async function loadSkillsMatrix(tid) {
    const table = document.getElementById('heatmap-table');
    table.innerHTML = '<tr><td colspan="20" style="padding: 20px; color: var(--text-muted); text-align: center;">Loading skill posteriors...</td></tr>';

    try {
      const res = await fetch(`${apiBase}/trainee/${tid}/skills`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const cells = data.factor_level_cells || {};

      // Header row: factor levels
      let headerHtml = '<thead><tr><th style="text-align: left; padding-left: 12px;">Skill</th>';
      FACTOR_COLUMNS.forEach(grp => {
        grp.levels.forEach(lvl => {
          headerHtml += `<th title="${grp.factor}: ${lvl}">${lvl}</th>`;
        });
      });
      headerHtml += '</tr></thead>';

      // Rows for each of the 5 skills
      let bodyHtml = '<tbody>';
      SKILL_ROWS.forEach(sk => {
        bodyHtml += `<tr><td class="skill-label">${capitalize(sk)}</td>`;

        FACTOR_COLUMNS.forEach(grp => {
          grp.levels.forEach(lvl => {
            const cellKey = `${sk}:${grp.factor}:${lvl}`;
            const cData = cells[cellKey] || { mean: 0.5, sd: 0.28, n: 0 };
            const m = cData.mean;
            const n = cData.n;
            const sd = cData.sd || 0.0;

            // Color gradient: <0.5 red, 0.5-0.7 amber, >0.7 cyan/green
            let bgRgb = '0, 229, 255';
            if (m < 0.45) bgRgb = '255, 61, 0';
            else if (m < 0.65) bgRgb = '255, 179, 0';
            else bgRgb = '0, 230, 118';

            // Faded opacity when n is low
            const alpha = Math.max(0.18, Math.min(0.9, 0.2 + (n / 6) * 0.7));
            const tooltip = `${capitalize(sk)} x ${lvl}\nMean: ${(m * 100).toFixed(1)}%\nSD: ${sd.toFixed(2)}\nn: ${n} observations`;

            bodyHtml += `
              <td class="heatmap-cell" style="background: rgba(${bgRgb}, ${alpha}); color: #fff;" title="${tooltip}" data-tooltip="${tooltip}">
                ${(m * 100).toFixed(0)}%
              </td>
            `;
          });
        });
        bodyHtml += '</tr>';
      });
      bodyHtml += '</tbody>';

      table.innerHTML = headerHtml + bodyHtml;
    } catch (e) {
      table.innerHTML = `<tr><td colspan="20" style="padding: 20px; color: var(--accent-red); text-align: center;">Error loading skill heatmap: ${e.message}</td></tr>`;
    }
  }

  // 2. Performance Trend Line Chart
  async function loadPerformanceTrend(tid) {
    try {
      const res = await fetch(`${apiBase}/trainee/${tid}/performance`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      const sessions = data.sessions || [];

      // Update sidebar overview
      document.getElementById('side-total-sessions').textContent = `${sessions.length} sessions`;
      if (sessions.length > 0) {
        const avg = sessions.reduce((acc, s) => acc + (s.overall || 0), 0) / sessions.length;
        document.getElementById('side-mean-score').textContent = `${Math.round(avg * 100)}%`;
      } else {
        document.getElementById('side-mean-score').textContent = '--';
      }

      // Prepare line chart datasets
      const labels = sessions.map((s, idx) => `Sess ${idx + 1}`);
      const practiceData = sessions.map(s => (s.mode === 'practice' ? s.overall : null));
      const testData = sessions.map(s => (s.mode === 'test' ? s.overall : null));

      SimpleChart.renderLineChart('performance-chart', labels, [
        { label: 'Practice Sessions', data: practiceData, borderColor: '#2f6bff', backgroundColor: 'rgba(47, 107, 255, 0.14)' },
        { label: 'Test Sessions (Held-Out)', data: testData, borderColor: '#8b5cf6', backgroundColor: 'rgba(139, 92, 246, 0.14)' },
      ]);
    } catch (e) {
      console.warn('Failed to render performance trend chart:', e);
    }
  }

  // 3. Generalization & Rote Indicators + Cell Coverage
  async function loadGeneralizationAndCoverage(tid) {
    try {
      const res = await fetch(`${apiBase}/trainee/${tid}/generalization`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      // Generalization Score
      const gen = data.generalization_score || {};
      const genEl = document.getElementById('val-gen-score');
      const genNoteEl = document.getElementById('note-gen-score');
      if (gen.score !== null && gen.score !== undefined) {
        genEl.textContent = `${(gen.score * 100).toFixed(1)}%`;
        genNoteEl.textContent = `${gen.note} (n_test=${gen.n_test}, n_matched=${gen.n_matched}).`;
      } else {
        genEl.textContent = 'Not enough data yet';
        genNoteEl.textContent = `${gen.note || 'Requires at least 2 test and 2 matched practice sessions.'} (n_test=${gen.n_test ?? 0}, n_matched=${gen.n_matched ?? 0})`;
      }

      // Rote Indicator
      const rote = data.rote_indicator || {};
      const roteEl = document.getElementById('val-rote-gap');
      const roteNoteEl = document.getElementById('note-rote-gap');
      if (rote.gap !== null && rote.gap !== undefined) {
        const sign = rote.gap > 0 ? '+' : '';
        roteEl.textContent = `${sign}${(rote.gap * 100).toFixed(1)}%`;
        roteNoteEl.textContent = `${rote.note} (n_repeat=${rote.n_repeat}, n_novel=${rote.n_novel}).`;
      } else {
        roteEl.textContent = 'Not enough data yet';
        roteNoteEl.textContent = `${rote.note || 'Requires at least 2 repeated and 2 matched novel sessions.'} (n_repeat=${rote.n_repeat ?? 0}, n_novel=${rote.n_novel ?? 0})`;
      }

      // Cell Coverage Bar
      const cov = data.coverage_report || {};
      const fraction = cov.coverage || 0.0;
      const seen = cov.seen || 0;
      const total = cov.total || 1440;
      const pct = (fraction * 100).toFixed(1);

      document.getElementById('coverage-fraction-text').textContent = `${seen} / ${total} practice cells (${pct}%)`;
      document.getElementById('coverage-bar-fill').style.width = `${Math.min(100, fraction * 100)}%`;
    } catch (e) {
      console.warn('Failed to load generalization metrics:', e);
    }
  }

  // 4. Adaptive Recommendation Plan
  async function loadAdaptivePlan(tid) {
    try {
      const res = await fetch(`${apiBase}/trainee/${tid}/plan`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      const reason = data.reason || 'Optimal pedagogical progression based on Bayesian posterior variance.';
      const scen = data.scenario || {};
      const diff = scen.difficulty_index !== undefined ? `${Math.round(scen.difficulty_index * 100)}% difficulty` : '';

      document.getElementById('plan-reason-text').innerHTML = `
        <div style="font-weight: 700; color: var(--text-primary); margin-bottom: 4px;">Recommended: ${capitalize(scen.factors?.terrain || 'airspace')} (${diff})</div>
        <div>${reason}</div>
      `;

      // Wire 'Start in simulator' button
      const startBtn = document.getElementById('btn-start-recommended');
      if (startBtn) {
        startBtn.onclick = () => {
          sessionStorage.setItem('START_ADAPTIVE', 'true');
        };
      }
    } catch (e) {
      document.getElementById('plan-reason-text').textContent = 'Adaptive recommendation generator available.';
    }
  }

  function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

})();
