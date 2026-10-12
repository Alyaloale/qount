/**
 * qount Simplified Frontend Application
 * Native JS + ECharts (no build steps, no framework dependencies)
 */

let activeTab = 'account';
let chartInstance = null;
let currentLineDetail = null;

const API_BASE = ''; // Same origin

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

async function initApp() {
  await Promise.all([
    fetchAccountData(),
    fetchLiveAccountData(),
    fetchPaperLines(),
  ]);
}

function switchTab(tabName) {
  activeTab = tabName;
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.screen-view').forEach(view => view.classList.remove('active'));

  const activeBtn = document.getElementById(`tab-${tabName}`);
  const activeView = document.getElementById(`screen-${tabName}`);

  if (activeBtn) activeBtn.classList.add('active');
  if (activeView) activeView.classList.add('active');

  // Trigger chart resize if switching to paper tab while detail is open
  if (tabName === 'paper' && chartInstance) {
    setTimeout(() => chartInstance.resize(), 50);
  }
}

async function refreshData() {
  const btn = document.getElementById('btn-refresh');
  if (btn) btn.innerText = '加载中...';
  await initApp();
  if (btn) btn.innerText = '↻ 刷新';
}

// -------------------------------------------------------------
// ACCOUNT SCREEN
// -------------------------------------------------------------
async function fetchAccountData() {
  try {
    const res = await fetch(`${API_BASE}/account`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderAccount(data);
  } catch (err) {
    console.error('Failed to load account:', err);
    document.getElementById('acc-nav').innerText = '¥-- (错误)';
  }
}

// -------------------------------------------------------------
// LIVE READ-ONLY EXCHANGE ACCOUNT
// Kept visually separate from the PAPER column: this one is money, the other is a simulation.
// -------------------------------------------------------------
async function fetchLiveAccountData() {
  const errBox = document.getElementById('live-error');
  try {
    const res = await fetch(`${API_BASE}/account/live`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const navElem = document.getElementById('live-nav');
    const cashElem = document.getElementById('live-cash');
    const currElem = document.getElementById('live-currency');
    const noteElem = document.getElementById('live-positions-note');
    const asOfElem = document.getElementById('live-as-of');
    const srcElem = document.getElementById('live-source-path');

    const currency = data.currency || '--';
    const fmt = v => Number(v || 0).toLocaleString('en-US', {
      minimumFractionDigits: 2, maximumFractionDigits: 8,
    });

    if (data.error) {
      // No observation available: say so, and show no number at all.
      if (navElem) navElem.innerText = '--';
      if (cashElem) cashElem.innerText = '--';
      if (currElem) currElem.innerText = currency;
      if (noteElem) noteElem.innerText = '暂无读数';
      if (asOfElem) asOfElem.innerText = '--';
      if (srcElem) srcElem.innerText = data.source?.path || '--';
      if (errBox) {
        errBox.innerText = `真实账户读数不可用：${data.error.split(':')[0]}`;
        errBox.classList.remove('hidden');
      }
      return;
    }

    if (errBox) errBox.classList.add('hidden');
    if (navElem) navElem.innerText = `${fmt(data.nav)} ${currency}`;
    if (cashElem) cashElem.innerText = `${fmt(data.cash)} ${currency}`;
    if (currElem) currElem.innerText = currency;
    if (noteElem) noteElem.innerText = `持仓 ${(data.positions || []).length} 项 · 只读`;
    if (asOfElem) asOfElem.innerText = data.as_of || '--';
    if (srcElem) srcElem.innerText = data.source?.path || '--';
  } catch (err) {
    console.error('Failed to load live account:', err);
    const navElem = document.getElementById('live-nav');
    if (navElem) navElem.innerText = '--';
    if (errBox) {
      errBox.innerText = '无法连接 API 获取真实账户读数';
      errBox.classList.remove('hidden');
    }
  }
}

function renderAccount(data) {
  const navElem = document.getElementById('acc-nav');
  const cashElem = document.getElementById('acc-cash');
  const posCountElem = document.getElementById('acc-position-count');
  const asOfElem = document.getElementById('acc-as-of');
  const headerAsOf = document.getElementById('header-as-of');
  const sourcePath = document.getElementById('acc-source-path');
  const sourceSha = document.getElementById('acc-source-sha256');
  const sourceProd = document.getElementById('acc-source-produced');

  const formattedNav = Number(data.nav || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const formattedCash = Number(data.cash || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  if (navElem) navElem.innerText = `¥${formattedNav}`;
  if (cashElem) cashElem.innerText = `¥${formattedCash}`;
  if (posCountElem) posCountElem.innerText = `${(data.positions || []).length} 只标的`;
  if (asOfElem) asOfElem.innerText = formatDate(data.as_of);
  if (headerAsOf) headerAsOf.innerText = `数据日期: ${formatDate(data.as_of)}`;

  // An unavailable paper package carries no NAV; surface the reason instead of ¥0.00, which
  // reads like a real (if alarming) balance.
  const accErrBox = document.getElementById('acc-error');
  if (accErrBox) {
    if (data.error) {
      accErrBox.innerText = `模拟盘数据不可用：${data.error.split(':')[0]}`;
      accErrBox.classList.remove('hidden');
      if (navElem) navElem.innerText = '--';
      if (cashElem) cashElem.innerText = '--';
    } else {
      accErrBox.classList.add('hidden');
    }
  }

  if (sourcePath) sourcePath.innerText = data.source?.path || '--';
  if (sourceSha) sourceSha.innerText = data.source?.sha256 ? data.source.sha256.substring(0, 16) + '...' : '--';
  if (sourceProd) sourceProd.innerText = data.source?.produced_at ? formatDate(data.source.produced_at) : '--';

  // Render positions table
  const tbody = document.getElementById('account-positions-body');
  if (!tbody) return;

  tbody.innerHTML = '';
  if (!data.positions || data.positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="table-empty">当前 100% 现金空仓，处于大周期空头保护状态</td></tr>';
    return;
  }

  data.positions.forEach(pos => {
    const tr = document.createElement('tr');
    const pct = (Number(pos.weight || 0) * 100).toFixed(1) + '%';
    const entry = pos.entry_date ? formatDate(pos.entry_date) : '--';

    tr.innerHTML = `
      <td><strong>${escapeHtml(pos.symbol)}</strong></td>
      <td><span style="color: var(--accent-green); font-weight: 700; font-family: var(--font-mono);">${pct}</span></td>
      <td>${entry}</td>
      <td>大周期趋势择时 (MA120)</td>
      <td><span class="status-badge status-active">🟢 满仓吃 Beta</span></td>
    `;
    tbody.appendChild(tr);
  });
}

// -------------------------------------------------------------
// PAPER SIMULATION SCREEN
// -------------------------------------------------------------
async function fetchPaperLines() {
  try {
    const res = await fetch(`${API_BASE}/paper/lines`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const lines = await res.json();
    renderPaperLines(lines);
  } catch (err) {
    console.error('Failed to load paper lines:', err);
    const tbody = document.getElementById('paper-lines-body');
    if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="table-empty">加载模拟盘研究线失败</td></tr>';
  }
}

function renderPaperLines(lines) {
  const tbody = document.getElementById('paper-lines-body');
  const countBadge = document.getElementById('paper-lines-count');
  if (countBadge) countBadge.innerText = `共 ${lines.length} 条研究线`;
  if (!tbody) return;

  tbody.innerHTML = '';
  if (lines.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="table-empty">暂无注册的研究线</td></tr>';
    return;
  }

  lines.forEach(line => {
    const tr = document.createElement('tr');

    // Status badge formatting
    let statusBadge = '';
    if (line.status === 'ACTIVE_PAPER') {
      statusBadge = '<span class="status-badge status-active">● 模拟运行</span>';
    } else if (line.status === 'ARCHIVED') {
      statusBadge = '<span class="status-badge status-archived">○ 封存保留</span>';
    } else if (line.status === 'STOPPED') {
      statusBadge = '<span class="status-badge status-stopped">⊘ 停止/失败</span>';
    } else if (line.status === 'MISSING') {
      statusBadge = '<span class="status-badge status-missing">✕ 无数据源</span>';
    } else {
      statusBadge = `<span class="status-badge status-archived">${escapeHtml(line.status)}</span>`;
    }

    // Freshness
    let freshnessBadge = '';
    if (line.freshness === 'FRESH') {
      freshnessBadge = '<span class="fresh-fresh">● 正常</span>';
    } else if (line.freshness === 'STALE') {
      freshnessBadge = '<span class="fresh-stale">◌ 待更新</span>';
    } else {
      freshnessBadge = '<span class="fresh-missing">✕ 缺失</span>';
    }

    // Category label
    const categoryMap = {
      assistant: '交易助手',
      equity: 'A股/美股',
      macro: '全球宏观',
      crypto: '加密资产',
      mixed: '多资产组合',
    };
    const catLabel = categoryMap[line.category] || line.category;

    // A line whose source could not be read carries an error and no figures. Surface that
    // plainly instead of rendering dashes that look like a quiet zero.
    const unavailable = !!line.error || !line.metrics || (line.nav_series && line.nav_series.length === 0);

    // Return display
    let returnStr = '--';
    if (line.metrics?.cagr_pct != null) {
      const val = line.metrics.cagr_pct;
      const sign = val > 0 ? '+' : '';
      returnStr = `${sign}${val.toFixed(2)}% (CAGR)`;
    } else if (line.metrics?.ytd_return_pct != null) {
      const val = line.metrics.ytd_return_pct;
      const sign = val > 0 ? '+' : '';
      returnStr = `${sign}${val.toFixed(1)}% (YTD)`;
    }
    if (unavailable) {
      returnStr = '<span class="data-unavailable">数据不可用</span>';
    }

    // MaxDD display
    let ddStr = '--';
    if (line.metrics?.max_drawdown_pct != null) {
      ddStr = `-${Math.abs(line.metrics.max_drawdown_pct).toFixed(1)}%`;
    }
    if (unavailable) {
      ddStr = '<span class="data-unavailable">—</span>';
    }

    tr.innerHTML = `
      <td><strong>${escapeHtml(line.name)}</strong><br><small style="color: var(--text-muted); font-family: var(--font-mono);">${escapeHtml(line.line_id)}</small></td>
      <td>${escapeHtml(catLabel)}</td>
      <td>${statusBadge}</td>
      <td style="font-family: var(--font-mono);">${formatDate(line.as_of)}</td>
      <td>${freshnessBadge}</td>
      <td style="font-family: var(--font-mono); font-weight: 700; color: ${returnStr.startsWith('+') ? 'var(--accent-green)' : 'inherit'};">${returnStr}</td>
      <td style="font-family: var(--font-mono); color: var(--accent-red);">${ddStr}</td>
      <td><button class="btn-action" onclick="showLineDetail('${escapeHtml(line.line_id)}')">展开详情</button></td>
    `;
    tbody.appendChild(tr);
  });
}

// -------------------------------------------------------------
// DETAIL DRAWER & ECHARTS
// -------------------------------------------------------------
async function showLineDetail(lineId) {
  const panel = document.getElementById('line-detail-panel');
  if (panel) panel.classList.remove('hidden');

  try {
    const res = await fetch(`${API_BASE}/paper/lines/${lineId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentLineDetail = data;
    renderLineDetail(data);

    // Smooth scroll to panel
    panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    console.error('Failed to load line details:', err);
    alert(`加载研究线详情失败: ${err.message}`);
  }
}

function closeDetailPanel() {
  const panel = document.getElementById('line-detail-panel');
  if (panel) panel.classList.add('hidden');
}

function renderLineDetail(data) {
  document.getElementById('detail-title').innerText = `${data.name} (${data.line_id})`;
  document.getElementById('detail-adjudication').innerText = `【研究裁决与事实】: ${data.adjudication || '暂无详细裁决'}`;

  document.getElementById('detail-source-path').innerText = data.source?.path || '--';
  document.getElementById('detail-source-sha256').innerText = data.source?.sha256 || '未核验/未生成单独哈希';

  // Render metrics pills
  const metricsGrid = document.getElementById('detail-metrics-grid');
  if (metricsGrid) {
    metricsGrid.innerHTML = '';
    const m = data.metrics || {};
    const items = [
      { title: '自起年化 (CAGR)', val: m.cagr_pct != null ? `${m.cagr_pct}%` : (m.ytd_return_pct != null ? `${m.ytd_return_pct}% (YTD)` : '--') },
      { title: '历史最大回撤', val: m.max_drawdown_pct != null ? `-${Math.abs(m.max_drawdown_pct)}%` : '--', color: 'var(--accent-red)' },
      { title: '夏普比率 (Sharpe)', val: m.sharpe != null ? m.sharpe.toFixed(2) : '--' },
      { title: '卡玛比率 (Calmar)', val: m.calmar != null ? m.calmar.toFixed(2) : '--' },
      { title: '已交易笔数', val: m.trade_count != null ? `${m.trade_count} 笔` : '--' },
      { title: '历史跨度天数', val: m.days != null ? `${m.days} 天` : '--' },
      { title: '数据新鲜度', val: data.freshness || '--' },
      { title: '运行状态', val: data.status || '--' },
    ];

    items.forEach(it => {
      const pill = document.createElement('div');
      pill.className = 'metric-pill';
      pill.innerHTML = `
        <div class="metric-pill-title">${escapeHtml(it.title)}</div>
        <div class="metric-pill-val" style="${it.color ? 'color: ' + it.color : ''}">${escapeHtml(String(it.val))}</div>
      `;
      metricsGrid.appendChild(pill);
    });
  }

  // Render ECharts
  renderNavChart(data.nav_series || []);
}

function renderNavChart(navSeries) {
  const chartDom = document.getElementById('echarts-container');
  if (!chartDom) return;

  if (chartInstance) {
    chartInstance.dispose();
  }
  chartInstance = echarts.init(chartDom, 'dark', { renderer: 'canvas' });

  const dates = navSeries.map(pt => pt.date);
  const stratNav = navSeries.map(pt => pt.nav);
  const benchNav = navSeries.map(pt => pt.benchmark_nav);

  const rangeMeta = document.getElementById('chart-range');
  if (rangeMeta && dates.length > 0) {
    rangeMeta.innerText = `${dates[0]} 至 ${dates[dates.length - 1]} (${dates.length} 个观测点)`;
  }

  const option = {
    backgroundColor: '#0d1117',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', label: { backgroundColor: '#21262d' } },
      formatter: function (params) {
        if (!params || !params.length) return '';
        let res = `<div style="font-size: 12px; font-weight: bold; margin-bottom: 4px;">${params[0].axisValue}</div>`;
        params.forEach(p => {
          const val = Number(p.value).toFixed(4);
          res += `<div style="display: flex; justify-content: space-between; gap: 16px;">
            <span>${p.marker} ${p.seriesName}:</span>
            <strong style="font-family: monospace;">${val}</strong>
          </div>`;
        });
        return res;
      }
    },
    legend: {
      data: ['策略净值 (Strategy NAV)', '基准净值 (Benchmark NAV)'],
      top: 0,
      textStyle: { color: '#8b949e' }
    },
    grid: {
      left: '3%',
      right: '3%',
      bottom: '12%',
      top: '12%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: '#30363d' } },
      axisLabel: { color: '#8b949e', fontSize: 11 }
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: '#21262d' } },
      axisLabel: {
        color: '#8b949e',
        formatter: (v) => v.toFixed(2)
      }
    },
    dataZoom: [
      {
        type: 'inside',
        start: 0,
        end: 100
      },
      {
        type: 'slider',
        bottom: 5,
        height: 20,
        borderColor: '#30363d',
        textStyle: { color: '#8b949e' },
        handleStyle: { color: '#58a6ff' }
      }
    ],
    series: [
      {
        name: '策略净值 (Strategy NAV)',
        type: 'line',
        data: stratNav,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color: '#3fb950' },
        itemStyle: { color: '#3fb950' },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(63, 185, 80, 0.25)' },
            { offset: 1, color: 'rgba(63, 185, 80, 0.00)' }
          ])
        }
      },
      {
        name: '基准净值 (Benchmark NAV)',
        type: 'line',
        data: benchNav,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.5, color: '#8b949e', type: 'dashed' },
        itemStyle: { color: '#8b949e' }
      }
    ]
  };

  chartInstance.setOption(option);
  window.addEventListener('resize', () => {
    if (chartInstance) chartInstance.resize();
  });
}

// -------------------------------------------------------------
// UTILS
// -------------------------------------------------------------
function formatDate(dStr) {
  if (!dStr) return '--';
  dStr = String(dStr).trim();
  if (dStr.includes('T')) {
    return dStr.split('T')[0];
  }
  if (dStr.length === 8 && /^\d+$/.test(dStr)) {
    return `${dStr.substring(0, 4)}-${dStr.substring(4, 6)}-${dStr.substring(6, 8)}`;
  }
  return dStr;
}

function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
