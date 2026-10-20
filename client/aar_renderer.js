// DroneDrill AI - Unified After Action Review (AAR) Renderer
// Shared by both the end-of-session modal and the full aar.html page

(function (window) {
  'use strict';

  function formatPct(val) {
    if (val === null || val === undefined || isNaN(val)) return '--%';
    return `${Math.round(val * 100)}%`;
  }

  function getScoreBandClass(scoreVal) {
    if (scoreVal === null || scoreVal === undefined || isNaN(scoreVal)) return 'band-amber';
    if (scoreVal >= 0.75) return 'band-green';
    if (scoreVal >= 0.50) return 'band-amber';
    return 'band-red';
  }

  function renderDeltaPill(deltaVal) {
    if (deltaVal === null || deltaVal === undefined || isNaN(deltaVal)) return '';
    const num = Number(deltaVal);
    if (num > 0) {
      return `<span class="score-delta-pill delta-up">+${num.toFixed(1)}%</span>`;
    } else if (num < 0) {
      return `<span class="score-delta-pill delta-down">${num.toFixed(1)}%</span>`;
    }
    return `<span class="score-delta-pill delta-flat">0.0%</span>`;
  }

  function renderConditionChip(caption, val, pillClass) {
    return `
      <div class="condition-chip-item" style="display: flex; flex-direction: column; gap: 2px;">
        <span class="chip-caption" style="font-family: var(--font-mono); font-size: 9px; color: var(--muted); text-transform: uppercase;">${caption}</span>
        <div class="chip ${pillClass}" style="padding: 3px 8px; font-size: 11px;">
          <span class="chip-dot"></span><span>${val}</span>
        </div>
      </div>
    `;
  }

  function generatePlainLanguageVerdict(overall, detection, classification, decision, timeliness, calibration) {
    const ov = overall !== null && overall !== undefined ? overall : 0;
    if (ov >= 0.85) {
      return 'Exemplary operational execution: Rapid detection, flawless target discrimination, and well-calibrated threat response.';
    } else if (ov >= 0.75) {
      return 'Strong operational readiness: High target detection and disciplined threat assessment under simulated conditions.';
    } else if (ov >= 0.60) {
      return 'Competent operational standard: Sound procedural decision-making with minor classification delays or missed cues.';
    } else if (ov >= 0.40) {
      return 'Moderate operational performance: Targeted training recommended in classification speed and threat discrimination under degraded conditions.';
    }
    return 'Critical training deficiency: High target miss rate or severe identification errors. Review sensor degradation guidelines and retry.';
  }

  /**
   * Main render method for AAR data into any container DOM element.
   */
  function renderAAR(containerEl, aar, options = {}) {
    if (!containerEl) return;
    if (!aar) {
      renderEmpty(containerEl);
      return;
    }

    const isModal = !!options.isModal;
    const scores = aar.scores || {};
    const deltas = aar.deltas || {};
    const overall = (aar.overall_score !== null && aar.overall_score !== undefined) ? aar.overall_score : scores.overall;
    const det = (scores.detection_score !== undefined) ? scores.detection_score : (scores.detection?.score ?? null);
    const cls = (scores.classification_score !== undefined) ? scores.classification_score : (scores.classification?.score ?? null);
    const dec = (scores.decision_score !== undefined) ? scores.decision_score : (scores.decision?.score ?? null);
    const time = (scores.timeliness_score !== undefined) ? scores.timeliness_score : (scores.timeliness?.score ?? null);
    const cal = (scores.calibration_score !== undefined) ? scores.calibration_score : (scores.calibration?.score ?? null);

    const factors = aar.factors || {};
    const tod = factors.time_of_day || 'Day';
    const weather = factors.weather || 'Clear';
    const terrain = factors.terrain || 'Open';
    const sensor = factors.sensor || 'EO';
    const degradation = factors.degradation || 'None';
    const mode = (aar.mode || 'practice').toUpperCase();
    const diffPct = Math.round((aar.difficulty_index || 0.5) * 100);

    // Weather pill class
    const todPill = (tod.toLowerCase() === 'night') ? 'pill-indigo' : (tod.toLowerCase() === 'dusk' ? 'pill-violet' : 'pill-amber');
    const degPill = (degradation.toLowerCase() === 'none') ? 'pill-green' : 'pill-red';

    const verdict = generatePlainLanguageVerdict(overall, det, cls, dec, time, cal);

    // Filter state for timeline
    let currentFilter = 'All';

    // Build timeline items
    const timelineItems = (aar.timeline || []).map((t, idx) => {
      const gt = t.ground_truth || {};
      const act = t.trainee_action || {};
      const vis = t.sensor_visibility || [];
      const isDetected = !!(act.detected && act.detect_time_s !== null);
      const isCorrectClass = isDetected && (act.classified_as === gt.true_class);
      const isCorrectThreat = isDetected && (act.threat_level_rated === gt.true_threat_level);
      const isCorrectResp = isDetected && (act.response_chosen === gt.expected_response);
      const isAllCorrect = isDetected && isCorrectClass && isCorrectThreat && isCorrectResp;
      const isMissed = !isDetected;
      const isWrong = isDetected && (!isCorrectClass || !isCorrectThreat || !isCorrectResp);

      // Find first and last visibility window times
      let fromT = gt.appears_at_time || 0.0;
      let toT = fromT + 10.0;
      if (vis && vis.length > 0) {
        fromT = Math.min(...vis.map(w => w.from_t));
        toT = Math.max(...vis.map(w => w.to_t));
      }

      return {
        idx,
        objectId: t.object_id,
        gt,
        act,
        vis,
        fromT,
        toT,
        isDetected,
        isMissed,
        isWrong,
        isAllCorrect,
        isCorrectClass,
        isCorrectThreat,
        isCorrectResp,
      };
    });

    // Determine max simulation time
    let maxT = 60.0;
    timelineItems.forEach(item => {
      maxT = Math.max(maxT, item.toT + 2);
      if (item.act.detect_time_s) maxT = Math.max(maxT, item.act.detect_time_s + 4);
    });
    maxT = Math.ceil(maxT / 10) * 10;

    // Build HTML layout
    containerEl.innerHTML = `
      <div class="aar-unified-container">

        <!-- 1. Header Banner -->
        <div class="aar-header-panel">
          <div class="aar-header-top">
            <div>
              <div class="aar-session-title">${aar.scenario_title || 'Session Review'}</div>
              <div class="aar-session-meta">
                <span>Session ID: <strong style="color: var(--text);">${(aar.session_id || '').substring(0, 12)}</strong></span>
                <span>•</span>
                <span>Mode: <strong style="color: var(--blue);">${mode}</strong></span>
                <span>•</span>
                <span>Date: ${aar.date ? String(aar.date).substring(0, 16) : new Date().toISOString().substring(0, 10)}</span>
                <span>•</span>
                <span>Difficulty: <strong>${diffPct}%</strong></span>
              </div>
            </div>
          </div>
          <div class="aar-chips-row">
            ${renderConditionChip('STATUS', 'COMPLETED', 'pill-green')}
            ${renderConditionChip('TIME', tod, todPill)}
            ${renderConditionChip('WEATHER', weather, 'pill-bluegrey')}
            ${renderConditionChip('TERRAIN', terrain, 'pill-slategreen')}
            ${renderConditionChip('SENSOR', sensor, 'pill-indigo')}
            ${renderConditionChip('DEGRADATION', degradation, degPill)}
          </div>
        </div>

        <!-- 2. Score Row: 6 Cards (Overall + 5 Skills) -->
        <div class="aar-score-grid">
          <div class="aar-score-card ${getScoreBandClass(overall)}">
            <span class="score-card-lbl">Overall Score</span>
            <div class="score-card-val-row">
              <span class="score-card-val" style="color: var(--blue);">${formatPct(overall)}</span>
              ${renderDeltaPill(deltas.overall)}
            </div>
          </div>
          <div class="aar-score-card ${getScoreBandClass(det)}">
            <span class="score-card-lbl">Detection</span>
            <div class="score-card-val-row">
              <span class="score-card-val">${formatPct(det)}</span>
              ${renderDeltaPill(deltas.detection)}
            </div>
          </div>
          <div class="aar-score-card ${getScoreBandClass(cls)}">
            <span class="score-card-lbl">Classification</span>
            <div class="score-card-val-row">
              <span class="score-card-val">${formatPct(cls)}</span>
              ${renderDeltaPill(deltas.classification)}
            </div>
          </div>
          <div class="aar-score-card ${getScoreBandClass(dec)}">
            <span class="score-card-lbl">Decision</span>
            <div class="score-card-val-row">
              <span class="score-card-val">${formatPct(dec)}</span>
              ${renderDeltaPill(deltas.decision)}
            </div>
          </div>
          <div class="aar-score-card ${getScoreBandClass(time)}">
            <span class="score-card-lbl">Timeliness</span>
            <div class="score-card-val-row">
              <span class="score-card-val">${formatPct(time)}</span>
              ${renderDeltaPill(deltas.timeliness)}
            </div>
          </div>
          <div class="aar-score-card ${getScoreBandClass(cal)}">
            <span class="score-card-lbl">Calibration</span>
            <div class="score-card-val-row">
              <span class="score-card-val">${formatPct(cal)}</span>
              ${renderDeltaPill(deltas.calibration)}
            </div>
          </div>
        </div>

        <!-- Verdict Banner -->
        <div class="aar-verdict-banner">
          <strong>Operational Verdict:</strong> ${verdict}
        </div>

        <!-- 3. Key Findings (Color-Coded Feedback) -->
        <div class="aar-findings-panel">
          <div class="aar-findings-title">
            <span>Key Pedagogical Findings & Diagnostic Notes</span>
            <span style="font-family: var(--font-mono); font-size: 11px; color: var(--muted);">${aar.feedback_sentences?.length || 0} findings</span>
          </div>
          <div class="aar-findings-list" id="aar-findings-container">
            ${renderFindingsList(aar)}
          </div>
        </div>

        <!-- 4. Clean Horizontal Timeline -->
        <div class="aar-timeline-panel">
          <div class="aar-timeline-top">
            <div style="font-family: var(--font-heading); font-size: 14px; font-weight: 600; color: var(--text);">
              Target Engagement Timeline
            </div>
            <div class="timeline-legend">
              <div class="legend-item"><span class="legend-swatch swatch-grey"></span><span>Visibility Window</span></div>
              <div class="legend-item"><span class="legend-swatch swatch-blue"></span><span>Detection</span></div>
              <div class="legend-item"><span class="legend-swatch swatch-amber"></span><span>Response</span></div>
              <div class="legend-item"><span class="legend-swatch swatch-green">✓</span><span>Correct</span></div>
              <div class="legend-item"><span class="legend-swatch swatch-red">✕</span><span>Missed</span></div>
            </div>
            <div class="timeline-filter-chips" id="timeline-filters">
              <button class="timeline-filter-btn active" data-filter="All">All (${timelineItems.length})</button>
              <button class="timeline-filter-btn" data-filter="Missed">Missed (${timelineItems.filter(i => i.isMissed).length})</button>
              <button class="timeline-filter-btn" data-filter="Wrong">Wrong (${timelineItems.filter(i => i.isWrong).length})</button>
              <button class="timeline-filter-btn" data-filter="Correct">Correct (${timelineItems.filter(i => i.isAllCorrect).length})</button>
            </div>
          </div>

          <div class="timeline-scroll-container">
            <div class="timeline-grid-wrap" id="timeline-grid-wrap">
              <!-- Rendered by renderTimelineRows -->
            </div>
          </div>
        </div>

        <!-- 5. Sortable Contact Table -->
        <div class="aar-table-panel">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
            <div style="font-family: var(--font-heading); font-size: 14px; font-weight: 600; color: var(--text);">
              Target Engagement Details & Ground Truth
            </div>
            <span style="font-size: 11px; color: var(--muted); font-family: var(--font-mono);">Click column header to sort</span>
          </div>
          <div id="aar-table-container">
            <!-- Rendered by renderContactTable -->
          </div>
        </div>

        <!-- 6. Secondary Grid: False Alarms & Not Scored Sections -->
        <div class="aar-two-col-grid">
          <div class="aar-info-box">
            <div class="aar-info-box-title" style="display: flex; justify-content: space-between;">
              <span>False Alarms</span>
              <span style="font-family: var(--font-mono); font-size: 11px; color: ${aar.errors?.false_alarms > 0 ? 'var(--amber)' : 'var(--green)'};">
                ${aar.errors?.false_alarms || 0} event(s)
              </span>
            </div>
            <p style="font-size: 12px; color: var(--text); line-height: 1.5;">
              ${aar.errors?.false_alarms > 0
                ? `${aar.errors.false_alarms} click(s) logged on empty airspace windows. Precision penalty was applied to Detection.`
                : 'Zero clicks on empty airspace. 100% false-alarm free vigilance maintained.'}
            </p>
          </div>

          <div class="aar-info-box">
            <div class="aar-info-box-title" style="display: flex; justify-content: space-between;">
              <span>Not Scored Airspace Contacts</span>
              <span style="font-family: var(--font-mono); font-size: 11px; color: var(--muted);">
                ${aar.not_scored?.length || 0} contact(s)
              </span>
            </div>
            <p style="font-size: 12px; color: var(--text); line-height: 1.5;">
              ${(aar.not_scored && aar.not_scored.length > 0)
                ? `${aar.not_scored.length} object(s) (${aar.not_scored.join(', ')}) never entered the safe sky main view and were excluded from scoring.`
                : 'All scenario contacts satisfied the minimum visibility window threshold and were included in the score.'}
            </p>
          </div>
        </div>

        <!-- 7. Modal Bottom Actions (If in Modal Mode) -->
        ${isModal ? `
          <div class="aar-modal-actions">
            <button class="btn-secondary" id="btn-aar-modal-back" style="padding: 8px 16px;">Back to Simulator</button>
            <button class="btn-secondary" id="btn-aar-modal-full" style="padding: 8px 16px;">Open Full AAR Page ↗</button>
            <button class="btn-primary" id="btn-aar-modal-next" style="padding: 8px 18px;">Next Adaptive Scenario</button>
          </div>
        ` : ''}

      </div>
    `;

    // Render timeline rows
    renderTimelineRows(containerEl.querySelector('#timeline-grid-wrap'), timelineItems, maxT, currentFilter);

    // Setup filter chip click listeners
    const filterBtns = containerEl.querySelectorAll('.timeline-filter-btn');
    filterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentFilter = btn.dataset.filter;
        renderTimelineRows(containerEl.querySelector('#timeline-grid-wrap'), timelineItems, maxT, currentFilter);
      });
    });

    // Render contact table with sorting
    let tableSortCol = 'contact';
    let tableSortAsc = true;
    renderContactTable(containerEl.querySelector('#aar-table-container'), timelineItems, tableSortCol, tableSortAsc);

    // Setup modal action buttons
    if (isModal) {
      const backBtn = containerEl.querySelector('#btn-aar-modal-back');
      if (backBtn) {
        backBtn.addEventListener('click', () => {
          if (typeof options.onCloseModal === 'function') options.onCloseModal();
          else {
            document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
          }
        });
      }

      const fullBtn = containerEl.querySelector('#btn-aar-modal-full');
      if (fullBtn) {
        fullBtn.addEventListener('click', () => {
          if (typeof options.onOpenFullPage === 'function') {
            options.onOpenFullPage(aar.session_id);
          } else {
            window.location.href = `aar.html?session=${encodeURIComponent(aar.session_id)}`;
          }
        });
      }

      const nextBtn = containerEl.querySelector('#btn-aar-modal-next');
      if (nextBtn) {
        nextBtn.addEventListener('click', () => {
          if (typeof options.onNextScenario === 'function') {
            options.onNextScenario();
          } else if (window.startAdaptiveSession) {
            document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
            window.startAdaptiveSession();
          }
        });
      }
    }
  }

  function renderFindingsList(aar) {
    const items = [];
    const sentences = aar.feedback_sentences || [];

    sentences.forEach(s => {
      const sLower = s.toLowerCase();
      let itemClass = 'finding-amber';
      let icon = '⚠';

      if (sLower.includes('missed') || sLower.includes('lost')) {
        itemClass = 'finding-red';
        icon = '✕';
      } else if (sLower.includes('exemplary') || sLower.includes('well-calibrated') || sLower.includes('zero') || sLower.includes('flawless')) {
        itemClass = 'finding-green';
        icon = '✓';
      } else if (sLower.includes('overconfidence') || sLower.includes('misclassified') || sLower.includes('threat') || sLower.includes('decision rules')) {
        itemClass = 'finding-amber';
        icon = '⚠';
      }

      items.push(`
        <div class="aar-finding-item ${itemClass}">
          <span class="finding-icon">${icon}</span>
          <span>${s}</span>
        </div>
      `);
    });

    // Confidence calibration note
    if (aar.confidence_vs_correctness) {
      const calLower = aar.confidence_vs_correctness.toLowerCase();
      let calClass = 'finding-green';
      let calIcon = '✓';
      if (calLower.includes('warning') || calLower.includes('overconfidence')) {
        calClass = 'finding-amber';
        calIcon = '⚠';
      } else if (calLower.includes('notice') || calLower.includes('hesitant')) {
        calClass = 'finding-info';
        calIcon = 'ℹ';
      }
      items.push(`
        <div class="aar-finding-item ${calClass}">
          <span class="finding-icon">${calIcon}</span>
          <span><strong>Calibration:</strong> ${aar.confidence_vs_correctness}</span>
        </div>
      `);
    }

    // Not scored note
    if (aar.not_scored && aar.not_scored.length > 0) {
      items.push(`
        <div class="aar-finding-item finding-info">
          <span class="finding-icon">ℹ</span>
          <span>${aar.not_scored.length} object(s) never appeared in the main view and were not scored.</span>
        </div>
      `);
    }

    return items.join('');
  }

  function renderTimelineRows(container, items, maxT, filter) {
    if (!container) return;

    let filtered = items;
    if (filter === 'Missed') filtered = items.filter(i => i.isMissed);
    else if (filter === 'Wrong') filtered = items.filter(i => i.isWrong);
    else if (filter === 'Correct') filtered = items.filter(i => i.isAllCorrect);

    // Build time axis tick marks every 10s
    const ticks = [];
    for (let t = 0; t <= maxT; t += 10) {
      const pct = (t / maxT) * 100;
      ticks.push({ t, pct });
    }

    const axisTicksHtml = ticks.map(tk => `
      <span class="timeline-tick-label" style="left: ${tk.pct}%;">${tk.t}s</span>
    `).join('');

    const gridLinesHtml = ticks.map(tk => `
      <div class="timeline-vgrid-line" style="left: ${tk.pct}%;"></div>
    `).join('');

    const rowsHtml = filtered.map(item => {
      const gt = item.gt;
      const act = item.act;

      // Span bar geometry
      const barLeft = Math.max(0, Math.min(100, (item.fromT / maxT) * 100));
      const barWidth = Math.max(2, Math.min(100 - barLeft, ((item.toT - item.fromT) / maxT) * 100));

      // Detection marker position
      let detMarkerHtml = '';
      if (item.isDetected) {
        const detPct = Math.max(0, Math.min(100, (act.detect_time_s / maxT) * 100));
        detMarkerHtml = `
          <div class="timeline-marker-detect" style="left: ${detPct}%;" title="Detected @ ${act.detect_time_s}s"></div>
        `;
      }

      // Response marker position
      let respMarkerHtml = '';
      if (item.isDetected && act.response_chosen) {
        const respTime = (act.detect_time_s || item.fromT) + 1.5;
        const respPct = Math.max(0, Math.min(100, (respTime / maxT) * 100));
        respMarkerHtml = `
          <div class="timeline-marker-resp" style="left: ${respPct}%;" title="Response: ${act.response_chosen}"></div>
        `;
      }

      // End-of-window status badge
      let endBadgeHtml = '';
      const endPct = barLeft + barWidth;
      if (item.isMissed) {
        endBadgeHtml = `
          <div class="timeline-badge-end badge-missed" style="left: ${Math.min(endPct, 92)}%;">
            <span>✕</span><span>Missed</span>
          </div>
        `;
      } else if (item.isAllCorrect) {
        endBadgeHtml = `
          <div class="timeline-badge-end badge-ok" style="left: ${Math.min(endPct, 92)}%;">
            <span>✓</span><span>Correct</span>
          </div>
        `;
      }

      return `
        <div class="timeline-contact-row">
          <div class="timeline-contact-info">
            <div class="contact-info-title">
              <span>Contact ${item.idx + 1}</span>
              <span style="font-weight: 400; color: var(--muted); font-size: 11px;">(${gt.true_class})</span>
            </div>
            <div class="contact-info-sub">
              Thr ${gt.true_threat_level} | ${gt.expected_response}
            </div>
          </div>
          <div class="timeline-bars-track">
            ${gridLinesHtml}
            <div class="timeline-span-bar" style="left: ${barLeft}%; width: ${barWidth}%;" title="Visible: ${item.fromT.toFixed(1)}s - ${item.toT.toFixed(1)}s"></div>
            ${detMarkerHtml}
            ${respMarkerHtml}
            ${endBadgeHtml}
          </div>
        </div>
      `;
    }).join('');

    container.innerHTML = `
      <div class="timeline-axis-header">
        <div class="timeline-contact-header">Contact & Threat</div>
        <div class="timeline-ticks-area">
          ${axisTicksHtml}
        </div>
      </div>
      ${rowsHtml || '<div style="padding: 24px; text-align: center; color: var(--muted); font-size: 12px;">No contacts match the selected filter.</div>'}
    `;
  }

  function renderContactTable(container, items, sortCol, sortAsc) {
    if (!container) return;

    // Clone and sort
    const sorted = [...items].sort((a, b) => {
      let va, vb;
      switch (sortCol) {
        case 'contact':
          va = a.idx;
          vb = b.idx;
          break;
        case 'gtClass':
          va = a.gt.true_class || '';
          vb = b.gt.true_class || '';
          break;
        case 'traineeClass':
          va = a.act.classified_as || '';
          vb = b.act.classified_as || '';
          break;
        case 'threat':
          va = a.gt.true_threat_level || 0;
          vb = b.gt.true_threat_level || 0;
          break;
        case 'response':
          va = a.gt.expected_response || '';
          vb = b.gt.expected_response || '';
          break;
        case 'detectTime':
          va = a.act.detect_time_s !== null ? a.act.detect_time_s : 9999;
          vb = b.act.detect_time_s !== null ? b.act.detect_time_s : 9999;
          break;
        case 'status':
          va = a.isAllCorrect ? 1 : (a.isMissed ? 3 : 2);
          vb = b.isAllCorrect ? 1 : (b.isMissed ? 3 : 2);
          break;
        default:
          va = a.idx;
          vb = b.idx;
      }
      if (va < vb) return sortAsc ? -1 : 1;
      if (va > vb) return sortAsc ? 1 : -1;
      return 0;
    });

    const sortArrow = (col) => {
      if (sortCol !== col) return '';
      return sortAsc ? ' ▲' : ' ▼';
    };

    const rowsHtml = sorted.map(item => {
      const gt = item.gt;
      const act = item.act;

      let badgeHtml = '';
      if (item.isMissed) {
        badgeHtml = `<span class="badge-status status-missed">✕ Missed</span>`;
      } else if (item.isAllCorrect) {
        badgeHtml = `<span class="badge-status status-correct">✓ Correct</span>`;
      } else if (!item.isCorrectClass) {
        badgeHtml = `<span class="badge-status status-wrong">Misclassified</span>`;
      } else {
        badgeHtml = `<span class="badge-status status-wrong">Proc. Variance</span>`;
      }

      const detTimeStr = (act.detect_time_s !== null && act.detect_time_s !== undefined)
        ? `${act.detect_time_s.toFixed(2)}s`
        : '—';

      const contribStr = item.isAllCorrect ? '+100%' : (item.isDetected ? '+50%' : '0%');

      return `
        <tr>
          <td><strong style="color: var(--text);">Contact ${item.idx + 1}</strong> <span style="font-family: var(--font-mono); font-size: 10px; color: var(--muted);">(${item.objectId})</span></td>
          <td><span style="font-family: var(--font-mono);">${gt.true_class}</span></td>
          <td><span style="font-family: var(--font-mono); color: ${act.classified_as ? (item.isCorrectClass ? 'var(--green)' : 'var(--red)') : 'var(--muted)'};">${act.classified_as || '—'}</span></td>
          <td><span style="font-family: var(--font-mono);">${gt.true_threat_level} vs ${act.threat_level_rated ?? '—'}</span></td>
          <td><span style="font-family: var(--font-mono);">${gt.expected_response} vs ${act.response_chosen || '—'}</span></td>
          <td><span style="font-family: var(--font-mono);">${detTimeStr}</span></td>
          <td><span style="font-family: var(--font-mono); font-weight: 700; color: ${item.isAllCorrect ? 'var(--green)' : (item.isDetected ? 'var(--amber)' : 'var(--red)')};">${contribStr}</span></td>
          <td>${badgeHtml}</td>
        </tr>
      `;
    }).join('');

    container.innerHTML = `
      <table class="aar-data-table">
        <thead>
          <tr>
            <th data-sort="contact">Contact${sortArrow('contact')}</th>
            <th data-sort="gtClass">Ground Truth${sortArrow('gtClass')}</th>
            <th data-sort="traineeClass">Trainee Class${sortArrow('traineeClass')}</th>
            <th data-sort="threat">Threat (Exp vs Rated)${sortArrow('threat')}</th>
            <th data-sort="response">Response (Exp vs Chosen)${sortArrow('response')}</th>
            <th data-sort="detectTime">Detect Time${sortArrow('detectTime')}</th>
            <th data-sort="contrib">Contribution</th>
            <th data-sort="status">Status${sortArrow('status')}</th>
          </tr>
        </thead>
        <tbody>
          ${rowsHtml}
        </tbody>
      </table>
    `;

    // Add click listeners to headers
    container.querySelectorAll('th[data-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.sort;
        if (sortCol === col) {
          sortAsc = !sortAsc;
        } else {
          sortCol = col;
          sortAsc = true;
        }
        renderContactTable(container, items, sortCol, sortAsc);
      });
    });
  }

  function renderLoading(containerEl) {
    if (!containerEl) return;
    containerEl.innerHTML = `
      <div style="padding: 60px 20px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 14px;">
        <div style="width: 32px; height: 32px; border: 3px solid rgba(47, 107, 255, 0.2); border-top-color: var(--blue); border-radius: 50%; animation: spin 0.8s linear infinite;"></div>
        <div style="font-family: var(--font-mono); font-size: 12px; color: var(--muted);">Loading session After Action Review data from API...</div>
      </div>
    `;
  }

  function renderError(containerEl, errorMsg, onRetry) {
    if (!containerEl) return;
    containerEl.innerHTML = `
      <div style="padding: 40px 20px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 12px;">
        <div style="color: var(--red); font-size: 28px;">⚠</div>
        <div style="font-family: var(--font-heading); font-size: 15px; font-weight: 600; color: var(--text);">Failed to load AAR review</div>
        <div style="font-size: 12px; color: var(--muted); max-width: 480px;">${errorMsg || 'Unable to retrieve session review data from the backend.'}</div>
        ${typeof onRetry === 'function' ? '<button class="btn-secondary" id="btn-aar-retry" style="margin-top: 8px;">Retry Request</button>' : ''}
      </div>
    `;
    if (typeof onRetry === 'function') {
      const retryBtn = containerEl.querySelector('#btn-aar-retry');
      if (retryBtn) retryBtn.addEventListener('click', onRetry);
    }
  }

  function renderEmpty(containerEl, message) {
    if (!containerEl) return;
    containerEl.innerHTML = `
      <div style="padding: 60px 20px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 10px;">
        <div style="color: var(--muted); font-size: 24px;">📊</div>
        <div style="font-family: var(--font-heading); font-size: 15px; font-weight: 600; color: var(--text);">No Session Selected</div>
        <div style="font-size: 12px; color: var(--muted); max-width: 440px;">${message || 'Select a completed session from the dropdown above to inspect detailed After Action Review data.'}</div>
      </div>
    `;
  }

  window.DroneDrillAAR = {
    renderAAR,
    renderLoading,
    renderError,
    renderEmpty,
  };

})(window);
