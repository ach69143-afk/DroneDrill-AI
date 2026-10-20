class SimpleChart {
  static PALETTE = ['#2f6bff', '#22c55e', '#f5b53d', '#8b5cf6', '#e5484d'];

  static renderLineChart(canvasId, labels, datasets) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // 1. If vendored Chart.js is available on window
    if (window.Chart) {
      if (canvas._chartInstance) {
        canvas._chartInstance.destroy();
      }
      canvas._chartInstance = new window.Chart(canvas, {
        type: 'line',
        data: {
          labels: labels,
          datasets: datasets.map((d, i) => {
            const color = d.borderColor || SimpleChart.PALETTE[i % SimpleChart.PALETTE.length];
            return {
              label: d.label,
              data: d.data,
              borderColor: color,
              backgroundColor: d.backgroundColor || `${color}20`,
              borderWidth: 2,
              tension: 0.25,
              pointRadius: 4,
              pointHoverRadius: 6,
            };
          })
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              min: 0,
              max: 1.0,
              ticks: {
                color: '#8e8e99',
                callback: v => `${Math.round(v * 100)}%`
              },
              grid: { color: 'rgba(255, 255, 255, 0.05)' }
            },
            x: {
              ticks: { color: '#8e8e99' },
              grid: { color: 'rgba(255, 255, 255, 0.05)' }
            }
          },
          plugins: {
            legend: {
              labels: { color: '#ececf0', font: { family: 'Inter', weight: 600 } }
            }
          }
        }
      });
      return;
    }

    // 2. High-fidelity Offline Canvas Fallback (if vendor script not yet fetched)
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.parentElement.clientWidth || 600;
    const h = canvas.height = canvas.parentElement.clientHeight || 260;

    ctx.clearRect(0, 0, w, h);

    const padL = 50, padR = 20, padT = 30, padB = 40;
    const chartW = w - padL - padR;
    const chartH = h - padT - padB;

    // Y Axis Grid
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.fillStyle = '#8e8e99';
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = 'right';

    for (let i = 0; i <= 4; i++) {
      const yVal = i * 0.25;
      const yPos = padT + chartH - (i * chartH) / 4;
      ctx.beginPath();
      ctx.moveTo(padL, yPos);
      ctx.lineTo(w - padR, yPos);
      ctx.stroke();
      ctx.fillText(`${Math.round(yVal * 100)}%`, padL - 8, yPos + 3);
    }

    if (!labels || labels.length === 0) return;

    // Draw Datasets
    datasets.forEach((ds, i) => {
      if (!ds.data || ds.data.length === 0) return;

      const color = ds.borderColor || SimpleChart.PALETTE[i % SimpleChart.PALETTE.length];
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.fillStyle = color;

      ctx.beginPath();
      ds.data.forEach((val, idx) => {
        const xPos = padL + (idx / Math.max(1, labels.length - 1)) * chartW;
        const vClamped = Math.max(0, Math.min(1.0, val !== null ? val : 0));
        const yPos = padT + chartH - vClamped * chartH;

        if (idx === 0) ctx.moveTo(xPos, yPos);
        else ctx.lineTo(xPos, yPos);
      });
      ctx.stroke();

      // Points
      ds.data.forEach((val, idx) => {
        if (val === null) return;
        const xPos = padL + (idx / Math.max(1, labels.length - 1)) * chartW;
        const vClamped = Math.max(0, Math.min(1.0, val));
        const yPos = padT + chartH - vClamped * chartH;
        ctx.beginPath();
        ctx.arc(xPos, yPos, 4, 0, Math.PI * 2);
        ctx.fill();
      });
    });

    // Legend
    ctx.textAlign = 'left';
    let legX = padL;
    datasets.forEach((ds, i) => {
      ctx.fillStyle = ds.borderColor || SimpleChart.PALETTE[i % SimpleChart.PALETTE.length];
      ctx.fillRect(legX, 10, 10, 10);
      ctx.fillStyle = '#e6eaf2';
      ctx.font = "11px 'Inter', sans-serif";
      ctx.fillText(ds.label, legX + 16, 19);
      legX += ctx.measureText(ds.label).width + 36;
    });
  }

  static renderBarChart(canvasId, labels, data, barColor = '#2f6bff') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    if (window.Chart) {
      if (canvas._chartInstance) {
        canvas._chartInstance.destroy();
      }
      canvas._chartInstance = new window.Chart(canvas, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: 'Sessions Count',
            data: data,
            backgroundColor: barColor,
            borderRadius: 4,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          scales: {
            y: {
              beginAtZero: true,
              ticks: { color: '#8e8e99' },
              grid: { color: 'rgba(255, 255, 255, 0.05)' }
            },
            x: {
              ticks: { color: '#8e8e99' },
              grid: { color: 'rgba(255, 255, 255, 0.05)' }
            }
          },
          plugins: {
            legend: { display: false }
          }
        }
      });
      return;
    }

    // Canvas fallback for bar chart
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.parentElement.clientWidth || 500;
    const h = canvas.height = canvas.parentElement.clientHeight || 220;

    ctx.clearRect(0, 0, w, h);
    const padL = 40, padR = 20, padT = 20, padB = 30;
    const chartW = w - padL - padR;
    const chartH = h - padT - padB;

    const maxVal = Math.max(1, ...data);

    // Draw bars
    const barWidth = (chartW / labels.length) * 0.65;
    const step = chartW / labels.length;

    labels.forEach((lbl, idx) => {
      const val = data[idx] || 0;
      const bHeight = (val / maxVal) * chartH;
      const x = padL + idx * step + (step - barWidth) / 2;
      const y = padT + chartH - bHeight;

      ctx.fillStyle = barColor;
      ctx.fillRect(x, y, barWidth, bHeight);

      // Label
      ctx.fillStyle = '#8e8e99';
      ctx.font = "10px 'JetBrains Mono', monospace";
      ctx.textAlign = 'center';
      ctx.fillText(lbl, x + barWidth / 2, h - 10);

      // Value atop bar
      if (val > 0) {
        ctx.fillStyle = '#fff';
        ctx.fillText(val, x + barWidth / 2, y - 4);
      }
    });
  }
}

window.SimpleChart = SimpleChart;
