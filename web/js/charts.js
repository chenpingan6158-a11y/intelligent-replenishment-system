/* 轻量图表库：纯 Canvas 绘制，无外部依赖，保证离线可用。 */
(function (global) {
  const COLOR = {
    primary: '#10695c',
    primaryLight: '#4c9c8d',
    amber: '#d97706',
    red: '#b91c1c',
    blue: '#1d4ed8',
    grid: '#eef2f2',
    axis: '#cfd6d7',
    text: '#8b9b98',
  };

  function setup(canvas, height) {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.parentElement.clientWidth || 520;
    const h = height || canvas.dataset.height || 200;
    canvas.width = width * dpr;
    canvas.height = h * dpr;
    canvas.style.width = width + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, h);
    return { ctx, width, height: h };
  }

  function niceMax(value) {
    if (value <= 0) return 10;
    const exp = Math.floor(Math.log10(value));
    const base = Math.pow(10, exp);
    const norm = value / base;
    let step = 1;
    if (norm <= 1) step = 1;
    else if (norm <= 2) step = 2;
    else if (norm <= 5) step = 5;
    else step = 10;
    return step * base;
  }

  function line(canvas, opts) {
    const { ctx, width, height } = setup(canvas, opts.height);
    const pad = { top: 14, right: 12, bottom: 26, left: 44 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const labels = opts.labels || [];
    const series = opts.series || [];
    let max = 0;
    series.forEach((s) => s.data.forEach((v) => (max = Math.max(max, v))));
    max = niceMax(max || 1);

    // 网格与 Y 轴
    ctx.font = '10px "PingFang SC", sans-serif';
    ctx.fillStyle = COLOR.text;
    ctx.strokeStyle = COLOR.grid;
    ctx.lineWidth = 1;
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) {
      const y = pad.top + (plotH * i) / ticks;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + plotW, y);
      ctx.stroke();
      const value = max - (max * i) / ticks;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(opts.formatY ? opts.formatY(value) : Math.round(value), pad.left - 8, y);
    }

    // X 轴标签（稀疏）
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const stepX = labels.length > 1 ? plotW / (labels.length - 1) : plotW;
    const labelStep = Math.ceil(labels.length / (opts.maxLabels || 7));
    labels.forEach((label, i) => {
      if (i % labelStep !== 0 && i !== labels.length - 1) return;
      ctx.fillText(label, pad.left + stepX * i, pad.top + plotH + 8);
    });

    // 数据线
    series.forEach((s) => {
      const color = s.color || COLOR.primary;
      if (opts.area !== false && series.length === 1) {
        const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
        grad.addColorStop(0, 'rgba(16,105,92,0.18)');
        grad.addColorStop(1, 'rgba(16,105,92,0.01)');
        ctx.beginPath();
        ctx.moveTo(pad.left, pad.top + plotH);
        s.data.forEach((v, i) => {
          const x = pad.left + stepX * i;
          const y = pad.top + plotH - (v / max) * plotH;
          ctx.lineTo(x, y);
        });
        ctx.lineTo(pad.left + stepX * (s.data.length - 1), pad.top + plotH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
      }
      ctx.beginPath();
      s.data.forEach((v, i) => {
        const x = pad.left + stepX * i;
        const y = pad.top + plotH - (v / max) * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.stroke();

      // 终点标记
      const lastX = pad.left + stepX * (s.data.length - 1);
      const lastY = pad.top + plotH - (s.data[s.data.length - 1] / max) * plotH;
      ctx.beginPath();
      ctx.arc(lastX, lastY, 3.2, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });
  }

  function bars(canvas, opts) {
    const { ctx, width, height } = setup(canvas, opts.height);
    const pad = { top: 14, right: 12, bottom: 28, left: 44 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const values = opts.values || [];
    const labels = opts.labels || [];
    const max = niceMax(Math.max(...values, 1));

    ctx.font = '10px "PingFang SC", sans-serif';
    ctx.strokeStyle = COLOR.grid;
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + (plotH * i) / 4;
      ctx.beginPath();
      ctx.moveTo(pad.left, y);
      ctx.lineTo(pad.left + plotW, y);
      ctx.stroke();
      ctx.fillStyle = COLOR.text;
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      ctx.fillText(Math.round(max - (max * i) / 4), pad.left - 8, y);
    }

    const slot = plotW / Math.max(1, values.length);
    const barW = Math.min(26, slot * 0.55);
    values.forEach((v, i) => {
      const x = pad.left + slot * i + (slot - barW) / 2;
      const h = (v / max) * plotH;
      const y = pad.top + plotH - h;
      const grad = ctx.createLinearGradient(0, y, 0, pad.top + plotH);
      grad.addColorStop(0, opts.color || COLOR.primary);
      grad.addColorStop(1, opts.color2 || COLOR.primaryLight);
      ctx.fillStyle = grad;
      const r = Math.min(4, barW / 2);
      ctx.beginPath();
      ctx.moveTo(x, pad.top + plotH);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.lineTo(x + barW - r, y);
      ctx.quadraticCurveTo(x + barW, y, x + barW, y + r);
      ctx.lineTo(x + barW, pad.top + plotH);
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = COLOR.text;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(labels[i] || '', x + barW / 2, pad.top + plotH + 8);
    });
  }

  function donut(canvas, opts) {
    const dpr = window.devicePixelRatio || 1;
    const size = opts.size || 148;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = size + 'px';
    canvas.style.height = size + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);

    const total = opts.items.reduce((sum, i) => sum + i.value, 0);
    const cx = size / 2;
    const cy = size / 2;
    const outer = size / 2 - 2;
    const inner = outer * 0.66;
    let angle = -Math.PI / 2;

    if (total === 0) {
      ctx.beginPath();
      ctx.arc(cx, cy, (outer + inner) / 2, 0, Math.PI * 2);
      ctx.strokeStyle = '#eef2f2';
      ctx.lineWidth = outer - inner;
      ctx.stroke();
    } else {
      opts.items.forEach((item) => {
        const sweep = (item.value / total) * Math.PI * 2;
        if (sweep <= 0) return;
        ctx.beginPath();
        ctx.arc(cx, cy, (outer + inner) / 2, angle, angle + sweep);
        ctx.strokeStyle = item.color;
        ctx.lineWidth = outer - inner;
        ctx.lineCap = 'butt';
        ctx.stroke();
        angle += sweep;
      });
    }

    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#17201f';
    ctx.font = '600 20px "PingFang SC", sans-serif';
    ctx.fillText(String(opts.centerValue != null ? opts.centerValue : total), cx, cy - 4);
    ctx.fillStyle = COLOR.text;
    ctx.font = '11px "PingFang SC", sans-serif';
    ctx.fillText(opts.centerLabel || '', cx, cy + 15);
  }

  global.Charts = { line, bars, donut, COLOR };
})(window);
