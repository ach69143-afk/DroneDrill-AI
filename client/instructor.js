// DroneDrill AI - Instructor Unit Dashboard Logic
// SIH 2026, PS 26247, Team NexxGenX

(function () {
  'use strict';

  const apiBase = (window.CONFIG && window.CONFIG.API_BASE) || 'http://127.0.0.1:8000';
  const defaultTraineeId = (window.CONFIG && window.CONFIG.TRAINEE_ID) || 'demo_trainee_01';

  let traineesData = [];
  let currentSortCol = 'mean_overall';
  let currentSortAsc = false;

  window.addEventListener('DOMContentLoaded', async () => {
    setupTableSorting();
    setupTableFilter();
    setupLauncherForm();

    await Promise.all([
      loadTrainees(),
      loadUnitSummary(),
      loadDecisionTreeRules(),
    ]);
  });

  // 1. Load & Render Trainees Roster
  async function loadTrainees() {
    try {
      const res = await fetch(`${apiBase}/trainees`);
      if (!res.ok) throw new Error(await res.text());
      traineesData = await res.json();

      document.getElementById('top-cohort-count').textContent = `Unit: ${traineesData.length} Trainees`;
      renderTraineeTable();
    } catch (e) {
      console.error('Failed to load trainees:', e);
      document.getElementById('api-banner').classList.add('active');
    }
  }

  function renderTraineeTable() {
    const tbody = document.getElementById('trainee-table-body');
    const filterText = (document.getElementById('trainee-filter-input').value || '').toLowerCase();

    let filtered = traineesData.filter(t => {
      const nameMatch = (t.name || '').toLowerCase().includes(filterText);
      const idMatch = (t.id || '').toLowerCase().includes(filterText);
      return nameMatch || idMatch;
    });

    // Sort
    filtered.sort((a, b) => {
      let valA = a[currentSortCol];
      let valB = b[currentSortCol];

      if (valA === null || valA === undefined) valA = -999;
      if (valB === null || valB === undefined) valB = -999;

      if (typeof valA === 'string') {
        return currentSortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
      }
      return currentSortAsc ? valA - valB : valB - valA;
    });

    if (filtered.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; padding: 20px; color: var(--text-muted);">No trainees found matching query.</td></tr>';
      return;
    }

    tbody.innerHTML = '';
    filtered.forEach(t => {
      const tr = document.createElement('tr');

      const meanScoreStr = t.mean_overall !== null ? `${Math.round(t.mean_overall * 100)}%` : '--';
      const genScoreStr = t.generalization_score !== null ? `${(t.generalization_score * 100).toFixed(1)}%` : '<span style="color: var(--text-muted);">N/A</span>';
      const roteGapStr = t.rote_gap !== null ? `${t.rote_gap > 0 ? '+' : ''}${(t.rote_gap * 100).toFixed(1)}%` : '<span style="color: var(--text-muted);">N/A</span>';

      const demoBadge = t.is_demo ? '<span class="badge-demo">DEMO DATA (synthetic)</span>' : '<span style="color: var(--accent-green); font-size: 11px;">Active</span>';

      tr.innerHTML = `
        <td style="font-weight: 700; color: var(--text-primary);">${t.name}</td>
        <td style="font-family: var(--font-mono); font-size: 11px;">${t.id}</td>
        <td>${demoBadge}</td>
        <td style="text-align: right; font-family: var(--font-mono);">${t.sessions}</td>
        <td style="text-align: right; font-family: var(--font-mono); font-weight: 700; color: var(--accent-cyan);">${meanScoreStr}</td>
        <td style="text-align: right; font-family: var(--font-mono);">${genScoreStr}</td>
        <td style="text-align: right; font-family: var(--font-mono);">${roteGapStr}</td>
        <td style="text-align: center;">
          <a href="skills.html" class="btn-secondary" style="text-decoration: none; font-size: 10px; padding: 4px 8px;" onclick="window.CONFIG && (window.CONFIG.TRAINEE_ID = '${t.id}')">
            View Skills
          </a>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  function setupTableSorting() {
    document.querySelectorAll('#trainee-table th[data-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.sort;
        if (currentSortCol === col) {
          currentSortAsc = !currentSortAsc;
        } else {
          currentSortCol = col;
          currentSortAsc = false;
        }
        renderTraineeTable();
      });
    });
  }

  function setupTableFilter() {
    const input = document.getElementById('trainee-filter-input');
    if (input) {
      input.addEventListener('input', () => renderTraineeTable());
    }
  }

  // 2. Load & Render Unit Cohort Analytics
  async function loadUnitSummary() {
    try {
      const res = await fetch(`${apiBase}/unit/summary`);
      if (!res.ok) throw new Error(await res.text());
      const summary = await res.json();

      // Top metrics
      const covPct = ((summary.mean_coverage || 0) * 100).toFixed(1);
      document.getElementById('top-mean-coverage').textContent = `Mean Coverage: ${covPct}%`;

      const dist = summary.score_distribution || {};
      document.getElementById('side-cohort-sessions').textContent = `${dist.total_sessions || 0} sessions`;
      document.getElementById('side-cohort-mean').textContent = dist.unit_mean !== null ? `${Math.round(dist.unit_mean * 100)}%` : '--%';

      // Score distribution chart
      const chartLabels = ['0-20%', '20-40%', '40-60%', '60-80%', '80-100%'];
      const chartData = [
        dist['0.0-0.2'] || 0,
        dist['0.2-0.4'] || 0,
        dist['0.4-0.6'] || 0,
        dist['0.6-0.8'] || 0,
        dist['0.8-1.0'] || 0,
      ];
      SimpleChart.renderBarChart('score-dist-chart', chartLabels, chartData, '#2f6bff');

      // Top confusion pairs
      const confList = document.getElementById('confusion-pairs-list');
      const confusions = summary.top_confusion_pairs || [];
      if (confusions.length === 0) {
        confList.innerHTML = '<span style="font-size: 11px; color: var(--accent-green);">Zero target misclassifications across unit.</span>';
      } else {
        confList.innerHTML = '';
        confusions.forEach(c => {
          const row = document.createElement('div');
          row.style = 'display: flex; justify-content: space-between; padding: 6px 8px; background: rgba(255,255,255,0.03); border-radius: 4px; font-size: 11px;';
          row.innerHTML = `
            <span style="font-family: var(--font-mono); color: var(--accent-red);">${c.pair}</span>
            <span style="font-weight: 700; color: var(--text-primary);">${c.count} error(s)</span>
          `;
          confList.appendChild(row);
        });
      }

      // Weakest conditions
      const weakList = document.getElementById('weakest-conditions-list');
      const weakConditions = summary.weakest_conditions || [];
      if (weakConditions.length === 0) {
        weakList.innerHTML = '<span style="font-size: 11px; color: var(--text-muted);">No weak condition levels logged.</span>';
      } else {
        weakList.innerHTML = '';
        weakConditions.forEach(w => {
          const row = document.createElement('div');
          row.style = 'display: flex; justify-content: space-between; padding: 6px 8px; background: rgba(255,255,255,0.03); border-radius: 4px; font-size: 11px;';
          row.innerHTML = `
            <span>${w.factor}: <strong>${w.level}</strong></span>
            <span style="font-family: var(--font-mono); font-weight: 700; color: var(--accent-amber);">${(w.mean_proficiency * 100).toFixed(0)}% (n=${w.n_observations})</span>
          `;
          weakList.appendChild(row);
        });
      }
    } catch (e) {
      console.warn('Failed to load unit summary:', e);
    }
  }

  // 3. Load & Render Decision Tree Protocol Matrix
  async function loadDecisionTreeRules() {
    try {
      const res = await fetch(`${apiBase}/decision-tree`);
      if (!res.ok) throw new Error(await res.text());
      const tree = await res.json();

      document.getElementById('tree-status-text').textContent = tree._status || 'Instructor-editable draft. Pending expert review. Not validated.';

      const grid = document.getElementById('rules-tree-grid');
      grid.innerHTML = '';

      const rules = tree.rules || {};
      Object.keys(rules).forEach(key => {
        const r = rules[key];
        const card = document.createElement('div');
        card.className = 'rule-tree-card';

        const responsesList = Object.entries(r.responses || {})
          .map(([resp, weight]) => `<div class="rule-resp-row"><span>${resp.replace(/_/g, ' ')}</span><span style="font-family: var(--font-mono); font-weight: 700; color: ${weight > 0 ? 'var(--accent-cyan)' : 'var(--text-muted)'};">${weight.toFixed(1)}</span></div>`)
          .join('');

        card.innerHTML = `
          <div class="rule-key-header">${key}</div>
          <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 4px;">Expected Threat Priority: <strong>Level ${r.expected_threat_level}</strong></div>
          <div style="display: flex; flex-direction: column; gap: 2px;">${responsesList}</div>
        `;
        grid.appendChild(card);
      });
    } catch (e) {
      console.error('Failed to load decision tree rules:', e);
    }
  }

  // 4. Scenario Constraint Launcher Form Handler
  function setupLauncherForm() {
    const form = document.getElementById('launcher-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const feedback = document.getElementById('launcher-feedback-area');
      feedback.style.display = 'block';
      feedback.innerHTML = '<div style="color: var(--accent-cyan); font-size: 12px;">Querying constraint matcher...</div>';

      const constraints = {};
      const fields = [
        { id: 'launch-tod', key: 'time_of_day' },
        { id: 'launch-weather', key: 'weather' },
        { id: 'launch-terrain', key: 'terrain' },
        { id: 'launch-sensor', key: 'sensor_mode' },
        { id: 'launch-degradation', key: 'degradation' },
        { id: 'launch-distractors', key: 'distractors' },
        { id: 'launch-count', key: 'object_count' },
      ];

      fields.forEach(f => {
        const val = document.getElementById(f.id).value;
        if (val) constraints[f.key] = val;
      });

      try {
        const res = await fetch(`${apiBase}/session/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            trainee_id: defaultTraineeId,
            mode: 'practice',
            constraints: constraints,
          }),
        });

        if (!res.ok) {
          const errData = await res.json();
          feedback.innerHTML = `
            <div style="background: rgba(255, 61, 0, 0.12); border: 1px solid var(--accent-red); padding: 12px; border-radius: 6px; font-size: 12px; color: #fff;">
              <strong>Constraint Filter Error:</strong> ${errData.detail || 'No practice cell matches this pinned combination.'}
            </div>
          `;
          return;
        }

        const data = await res.json();
        const scen = data.scenario || {};

        // Store in sessionStorage so when user clicks 'Open in simulator', it launches directly
        sessionStorage.setItem('PENDING_SIM_SESSION', JSON.stringify({
          sessionId: data.session_id,
          scenario: scen,
          mode: 'practice'
        }));

        feedback.innerHTML = `
          <div style="background: rgba(0, 230, 118, 0.12); border: 1px solid var(--accent-green); padding: 14px; border-radius: 6px; font-size: 12px;">
            <div style="font-weight: 700; color: var(--accent-green); margin-bottom: 6px;">✓ Targeted Scenario Generated Successfully</div>
            <div><strong>Session ID:</strong> <code>${data.session_id}</code></div>
            <div><strong>Source:</strong> ${scen.source || 'instructor_launched'}</div>
            <div><strong>Cell:</strong> [${(scen.cell || []).join(', ')}]</div>
            <div><strong>Difficulty:</strong> ${Math.round((scen.difficulty_index || 0.5) * 100)}% | <strong>Objects:</strong> ${(scen.objects || []).length}</div>
            <div style="margin-top: 10px;">
              <a href="simulator.html" class="btn-primary" style="text-decoration: none; display: inline-flex; font-size: 12px; padding: 6px 12px;">
                Open in simulator
              </a>
            </div>
            <div style="margin-top: 12px;">
              <span style="font-weight: 600; color: var(--text-secondary); display: block; margin-bottom: 4px;">Scenario Spec JSON:</span>
              <pre style="background: rgba(0,0,0,0.45); border: 1px solid var(--border-subtle); padding: 10px; border-radius: 4px; max-height: 220px; overflow-y: auto; font-family: var(--font-mono); font-size: 11px; color: #a5d6a7; line-height: 1.4;">${JSON.stringify(scen, null, 2)}</pre>
            </div>
          </div>
        `;
      } catch (err) {
        feedback.innerHTML = `
          <div style="background: rgba(255, 61, 0, 0.12); border: 1px solid var(--accent-red); padding: 12px; border-radius: 6px; font-size: 12px; color: #fff;">
            Error communicating with launcher endpoint: ${err.message}
          </div>
        `;
      }
    });
  }

})();
