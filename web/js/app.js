/* 连锁餐饮门店订货与库存智能补货系统 —— 前端应用
 * 纯原生 JS + Canvas 图表，无构建步骤、无 CDN 依赖，保证离线可运行。
 */
(function () {
  'use strict';

  // ------------------------------------------------------------------ 基础工具
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const S = {
    token: localStorage.getItem('cr_token') || '',
    user: null,
    stores: [],
    storeId: null,
    view: 'dashboard',
    cache: {},
  };

  const ROLE = {
    ADMIN: '系统管理员',
    HQ_PLANNER: '总部计划员',
    REGION_MANAGER: '区域经理',
    STORE_MANAGER: '门店店长',
    STORE_CLERK: '门店员工',
    WAREHOUSE: '中央厨房',
  };

  const STATUS_LABEL = {
    DRAFT: ['草稿', 'grey'],
    SUBMITTED: ['待审批', 'amber'],
    APPROVED: ['已批准', 'blue'],
    REJECTED: ['已驳回', 'red'],
    CONFIRMED: ['配送中', 'blue'],
    RECEIVED: ['已收货', 'green'],
    CLOSED: ['已归档', 'grey'],
    CANCELLED: ['已取消', 'grey'],
  };

  const ACTION_LABEL = {
    SUBMIT: '提交',
    APPROVE: '审批通过',
    REJECT: '驳回',
    CONFIRM: '发货',
    RECEIVE: '收货',
    CANCEL: '取消',
    CLOSE: '归档',
  };

  const MOVEMENT_LABEL = {
    IN: ['入库', 'green'],
    OUT: ['出库', 'grey'],
    ADJUST: ['盘点调整', 'blue'],
    LOSS: ['报损', 'red'],
    TRANSFER_IN: ['调拨入', 'blue'],
    TRANSFER_OUT: ['调拨出', 'blue'],
  };

  const ALERT_LABEL = {
    LOW_STOCK: '低库存',
    STOCKOUT_RISK: '断货风险',
    NEAR_EXPIRY: '临期',
    SLOW_MOVING: '滞销',
  };

  const REASON_LABEL = {
    EXPIRED: '过期',
    DAMAGED: '破损',
    PROCESS_LOSS: '加工损耗',
    OTHER: '其他',
  };

  function fmtMoney(cents) {
    if (cents == null) return '—';
    return '¥' + (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtMoneyShort(cents) {
    if (cents == null) return '—';
    const v = cents / 100;
    if (v >= 10000) return '¥' + (v / 10000).toFixed(1) + '万';
    return '¥' + v.toFixed(0);
  }
  function fmtPct(rate, digits) {
    if (rate == null) return '—';
    return (rate * 100).toFixed(digits == null ? 1 : digits) + '%';
  }
  function fmtDateTime(iso) {
    if (!iso) return '—';
    return iso.replace('T', ' ').slice(0, 16);
  }
  function fmtDate(iso) {
    if (!iso) return '—';
    return iso.slice(0, 10);
  }
  function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ------------------------------------------------------------------ API
  async function request(path, options) {
    const opts = Object.assign({ method: 'GET', headers: {} }, options || {});
    if (S.token) opts.headers['Authorization'] = 'Bearer ' + S.token;
    if (opts.body && typeof opts.body !== 'string') {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, opts);
    let payload = null;
    try {
      payload = await res.json();
    } catch (e) {
      payload = { code: res.status, message: '服务返回异常', data: null };
    }
    if (!res.ok || (payload && payload.code !== 0)) {
      if (res.status === 401) {
        logout(true);
      }
      throw new Error((payload && payload.message) || '请求失败');
    }
    return payload ? payload.data : null;
  }
  const API = {
    get: (p) => request(p),
    post: (p, body) => request(p, { method: 'POST', body: body || {} }),
    put: (p, body) => request(p, { method: 'PUT', body: body || {} }),
  };

  // ------------------------------------------------------------------ 反馈组件
  let toastTimer = null;
  function toast(message, type) {
    const node = $('#toast');
    node.textContent = message;
    node.className = 'toast show ' + (type || '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      node.className = 'toast ' + (type || '');
    }, 2600);
  }

  function openModal(config) {
    const root = $('#modal-root');
    const mask = document.createElement('div');
    mask.className = 'modal-mask';
    mask.innerHTML = `
      <div class="modal ${config.wide ? 'wide' : ''}">
        <div class="modal-head">
          <h3>${escapeHtml(config.title || '')}</h3>
          <button type="button" data-close>×</button>
        </div>
        <div class="modal-body">${config.body || ''}</div>
        ${config.footer === false ? '' : `<div class="modal-foot">${config.footer || '<button class="btn" data-close>关闭</button>'}</div>`}
      </div>`;
    root.appendChild(mask);
    const close = () => mask.remove();
    mask.addEventListener('click', (e) => {
      if (e.target === mask || e.target.hasAttribute('data-close')) close();
    });
    return { el: mask, close, body: $('.modal-body', mask) };
  }

  // ------------------------------------------------------------------ 登录 / 注册
  async function doLogin(username, password) {
    const data = await request('/api/auth/login', { method: 'POST', body: { username, password } });
    S.token = data.token;
    S.user = data.user;
    localStorage.setItem('cr_token', data.token);
    await bootApp();
  }

  // 注册表单选项与联动
  const regState = { options: null };
  const QUOTA_HINT = { store: '每门店', region: '每大区', global: '全系统' };
  async function initRegisterForm() {
    if (regState.options) return;
    regState.options = await request('/api/auth/options');
    const q = regState.options.quotas || {};
    $('#reg-role').innerHTML = regState.options.roles
      .map((r) => {
        const quota = q[r.value];
        const hint = quota ? `（${QUOTA_HINT[quota.scope]}上限 ${quota.limit} 名）` : '';
        return `<option value="${r.value}">${r.label}${hint}</option>`;
      })
      .join('');
    $('#reg-store').innerHTML = regState.options.stores
      .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
      .join('');
    $('#reg-region').innerHTML = regState.options.regions
      .map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`)
      .join('');
    syncRegisterRows();
  }
  function syncRegisterRows() {
    const role = $('#reg-role').value;
    $('#reg-store-row').classList.toggle('hidden', role !== 'STORE_MANAGER' && role !== 'STORE_CLERK');
    $('#reg-region-row').classList.toggle('hidden', role !== 'REGION_MANAGER');
  }
  async function doRegister(payload) {
    const data = await request('/api/auth/register', { method: 'POST', body: payload });
    S.token = data.token;
    S.user = data.user;
    localStorage.setItem('cr_token', data.token);
    await bootApp();
  }

  function logout(silent) {
    S.token = '';
    S.user = null;
    localStorage.removeItem('cr_token');
    $('#app-view').classList.add('hidden');
    $('#login-view').classList.remove('hidden');
    if (!silent) toast('已退出登录');
  }

  // ------------------------------------------------------------------ 初始化
  async function bootApp() {
    if (!S.user) {
      S.user = await API.get('/api/auth/me');
    }
    S.stores = await API.get('/api/master/stores');
    if (!S.storeId) S.storeId = S.user.storeId || (S.stores[0] && S.stores[0].id) || null;

    $('#login-view').classList.add('hidden');
    $('#app-view').classList.remove('hidden');
    $('#user-name').textContent = S.user.fullName || S.user.username;
    $('#user-role').textContent = S.user.roleLabel || ROLE[S.user.role] || S.user.role;
    $('#user-avatar').textContent = (S.user.fullName || '用').slice(0, 1);

    const multi = S.user.role !== 'STORE_MANAGER' && S.user.role !== 'STORE_CLERK';
    const switcher = $('#store-switcher');
    if (multi) {
      switcher.classList.remove('hidden');
      const select = $('#store-select');
      const allowAll = S.user.role === 'ADMIN' || S.user.role === 'HQ_PLANNER';
      select.innerHTML =
        (allowAll ? '<option value="">全部门店（汇总）</option>' : '') +
        S.stores.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
      select.value = S.storeId ? String(S.storeId) : '';
      select.onchange = () => {
        S.storeId = select.value ? Number(select.value) : null;
        render();
      };
    } else {
      switcher.classList.add('hidden');
    }

    const initial = location.hash.replace('#', '');
    navigate(VIEWS[initial] ? initial : 'dashboard');
    refreshBadges();
  }

  async function refreshBadges() {
    try {
      const [alerts, pending] = await Promise.all([
        API.get('/api/alerts/summary'),
        API.get('/api/orders/pending'),
      ]);
      const alertBadge = $('#nav-alerts');
      alertBadge.textContent = alerts.total || '';
      alertBadge.classList.toggle('hidden', !alerts.total);
      const pendingBadge = $('#nav-pending');
      pendingBadge.textContent = pending.length || '';
      pendingBadge.classList.toggle('hidden', !pending.length);
    } catch (e) {
      /* 忽略角标错误 */
    }
  }

  // ------------------------------------------------------------------ 路由
  const VIEW_META = {
    dashboard: ['经营看板', '关键指标、消耗趋势与预警概览'],
    replenish: ['智能补货', '基于历史消耗与补货策略生成建议订货量，可解释、可调整'],
    orders: ['订货单', '订单全生命周期：提交 → 审批 → 发货 → 收货'],
    inventory: ['库存管理', '实时库存、批次效期、库存流水与出入库作业'],
    alerts: ['预警中心', '低库存、断货风险、临期与滞销预警'],
    master: ['基础数据', '商品、补货策略与配方'],
  };

  function navigate(view, fromHash) {
    if (!VIEWS[view]) view = 'dashboard';
    S.view = view;
    if (!fromHash && location.hash !== '#' + view) {
      history.replaceState(null, '', '#' + view);
    }
    $$('.nav-item').forEach((el) => el.classList.toggle('active', el.dataset.view === view));
    const meta = VIEW_META[view] || ['', ''];
    $('#page-title').textContent = meta[0];
    $('#page-sub').textContent = meta[1];
    render();
  }

  async function render() {
    const root = $('#view-root');
    root.innerHTML = '<div class="empty">加载中…</div>';
    try {
      const fn = VIEWS[S.view];
      if (!fn) return;
      await fn(root);
    } catch (err) {
      root.innerHTML = `<div class="empty"><strong>加载失败</strong>${escapeHtml(err.message)}</div>`;
    }
    refreshBadges();
  }

  // ------------------------------------------------------------------ 视图：经营看板
  const VIEWS = {};

  VIEWS.dashboard = async function (root) {
    const q = S.storeId ? '?store_id=' + S.storeId : '';
    const data = await API.get('/api/dashboard/overview' + q);
    const storeName = (S.stores.find((s) => s.id === S.storeId) || {}).name || '全部门店';
    const alertSum = data.alertSummary || { total: 0, byType: {} };

    const turnover = data.turnover.turnoverDays;
    const cards = [
      {
        label: '缺货率',
        value: fmtPct(data.stockout.rate),
        foot: `${data.stockout.zero} / ${data.stockout.total} 个门店-SKU 可用库存为 0`,
        cls: data.stockout.rate > 0.1 ? 'bad' : data.stockout.rate > 0.05 ? 'warn' : 'good',
      },
      {
        label: '库存周转天数',
        value: turnover == null ? '—' : turnover,
        unit: '天',
        foot: `日均消耗 ${data.turnover.dailyAvg}（最小单位）`,
        cls: turnover != null && turnover > 15 ? 'warn' : 'good',
      },
      {
        label: '损耗率（30 天）',
        value: fmtPct(data.loss.rate),
        foot: `报损 ${fmtMoney(data.loss.lossCents)} / 出库 ${fmtMoney(data.loss.outCents)}`,
        cls: data.loss.rate > 0.05 ? 'bad' : 'good',
      },
      {
        label: '订货达成率（30 天）',
        value: fmtPct(data.fulfillment.rate),
        foot: `${data.fulfillment.received} / ${data.fulfillment.total} 单已完成收货`,
        cls: data.fulfillment.rate < 0.8 ? 'warn' : 'good',
      },
    ];

    root.innerHTML = `
      <div class="grid grid-4">
        ${cards
          .map(
            (c) => `<div class="card metric ${c.cls}">
              <div class="metric-label">${c.label}</div>
              <div class="metric-value">${c.value}${c.unit ? `<small>${c.unit}</small>` : ''}</div>
              <div class="metric-foot">${escapeHtml(c.foot)}</div>
            </div>`
          )
          .join('')}
      </div>

      <div class="section-gap"></div>

      <div class="grid grid-3-1">
        <div class="card">
          <div class="card-head">
            <h3>原料消耗趋势（近 14 天）</h3>
            <span class="hint">${escapeHtml(storeName)} · 单位：最小计量单位</span>
          </div>
          <div class="card-body">
            <div class="chart-wrap"><canvas id="trend-chart" data-height="210"></canvas></div>
            <div class="chart-legend"><span><i style="background:#10695c"></i>日消耗量</span></div>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h3>预警分布</h3><span class="hint">共 ${alertSum.total} 条</span></div>
          <div class="card-body" style="display:flex;flex-direction:column;align-items:center;gap:10px">
            <canvas id="alert-donut"></canvas>
            <div class="chart-legend" style="justify-content:center">
              ${Object.keys(ALERT_LABEL)
                .map(
                  (key, i) =>
                    `<span><i style="background:${['#b91c1c', '#d97706', '#1d4ed8', '#8b9b98'][i]}"></i>${ALERT_LABEL[key]} ${
                      alertSum.byType[key] || 0
                    }</span>`
                )
                .join('')}
            </div>
          </div>
        </div>
      </div>

      <div class="section-gap"></div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-head"><h3>消耗 TOP 8</h3><span class="hint">近 30 天累计</span></div>
          <div class="card-body">
            <div class="rank-list">
              ${data.topMoving.length
                ? (() => {
                    const max = Math.max(...data.topMoving.map((m) => m.totalBase), 1);
                    return data.topMoving
                      .map(
                        (m, i) => `<div class="rank-item">
                          <span class="rank-no">${i + 1}</span>
                          <span class="rank-name">${escapeHtml(m.productName)}</span>
                          <span class="rank-bar"><i style="width:${Math.max(4, (m.totalBase / max) * 100)}%"></i></span>
                          <span class="rank-val">${m.totalBase.toLocaleString('zh-CN')}</span>
                        </div>`
                      )
                      .join('');
                  })()
                : '<div class="empty">暂无消耗数据</div>'}
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h3>待办提醒</h3><button class="btn btn-sm" id="go-alerts">查看全部</button></div>
          <div class="card-body">
            <div class="stack-alerts" id="alert-preview">
              <div class="empty">加载中…</div>
            </div>
          </div>
        </div>
      </div>`;

    // 图表
    const trend = data.consumptionTrend || [];
    Charts.line($('#trend-chart'), {
      labels: trend.map((d) => fmtDate(d.date).slice(5)),
      series: [{ data: trend.map((d) => d.qty), color: Charts.COLOR.primary }],
      formatY: (v) => (v >= 10000 ? (v / 10000).toFixed(0) + '万' : Math.round(v)),
      height: 210,
    });

    Charts.donut($('#alert-donut'), {
      centerValue: alertSum.total,
      centerLabel: '待处理预警',
      items: [
        { value: alertSum.byType.STOCKOUT_RISK || 0, color: '#b91c1c' },
        { value: alertSum.byType.LOW_STOCK || 0, color: '#d97706' },
        { value: alertSum.byType.NEAR_EXPIRY || 0, color: '#1d4ed8' },
        { value: alertSum.byType.SLOW_MOVING || 0, color: '#8b9b98' },
      ],
    });

    $('#go-alerts').onclick = () => navigate('alerts');

    const alerts = await API.get('/api/alerts?status=OPEN');
    const box = $('#alert-preview');
    if (!alerts.length) {
      box.innerHTML = '<div class="empty">暂无待处理预警</div>';
    } else {
      box.innerHTML = alerts
        .slice(0, 6)
        .map(
          (a) => `<div class="alert-line">
            <span class="dot ${a.level === 'CRITICAL' ? 'red' : a.level === 'WARN' ? 'amber' : 'grey'}"></span>
            <span class="msg">${escapeHtml(a.productName)} · ${escapeHtml(a.message)}</span>
            <span class="tag tag-grey">${ALERT_LABEL[a.type] || a.type}</span>
          </div>`
        )
        .join('');
    }
  };

  // ------------------------------------------------------------------ 视图：智能补货
  let cart = {};
  VIEWS.replenish = async function (root) {
    const token = (S._repToken = (S._repToken || 0) + 1);
    const sid = S.storeId || (S.stores[0] || {}).id;
    const list = await API.get('/api/replenishment/suggestions?store_id=' + sid + '&only_needed=false');
    if (token !== S._repToken) return;
    cart = {};
    const storeName = (S.stores.find((s) => s.id === sid) || {}).name || '';

    root.innerHTML = `
      <div class="card">
        <div class="card-head">
          <h3>补货建议清单</h3>
          <div class="toolbar">
            <input type="text" id="rep-search" placeholder="搜索商品 / SKU" style="width:180px" />
            <label style="display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--text-2)">
              <input type="checkbox" id="rep-only" checked /> 仅显示需补货
            </label>
            <button class="btn btn-sm" id="rep-expand">展开全部依据</button>
          </div>
        </div>
        <div class="card-body" style="padding:0">
          <table id="rep-table">
            <thead>
              <tr>
                <th style="width:36px"><input type="checkbox" id="rep-all" /></th>
                <th>商品</th>
                <th class="num">可用库存</th>
                <th class="num">补货点</th>
                <th class="num">预计断货</th>
                <th class="num">建议订货</th>
                <th class="num">订货量</th>
                <th class="num">单价</th>
              </tr>
            </thead>
            <tbody id="rep-body"></tbody>
          </table>
        </div>
      </div>
      <div class="cart-bar hidden" id="cart-bar">
        <div class="cart-info">已选 <strong id="cart-count">0</strong> 项，预计金额 <strong id="cart-amount">¥0</strong></div>
        <div class="toolbar">
          <button class="btn btn-ghost" id="cart-clear" style="color:#cfe7e1;border-color:rgba(255,255,255,.2)">清空</button>
          <button class="btn btn-primary" id="cart-submit">生成订货单</button>
        </div>
      </div>
      <p style="margin:12px 2px;color:var(--muted);font-size:12px">
        门店：${escapeHtml(storeName)} · 建议量由「近 28 天消耗 + 星期因子 + 趋势 + 安全库存」计算，点击任意行可查看完整推导过程。
      </p>`;

    const onlyCheckbox = $('#rep-only');
    const search = $('#rep-search');

    function visibleRows() {
      const kw = search.value.trim().toLowerCase();
      return list.filter((r) => {
        if (onlyCheckbox.checked && !(r.needsReorder && r.suggestQtyBase > 0)) return false;
        if (kw && !(r.productName.toLowerCase().includes(kw) || r.sku.toLowerCase().includes(kw))) return false;
        return true;
      });
    }

    function renderRows(expandAll) {
      const rows = visibleRows();
      const body = $('#rep-body');
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="8"><div class="empty"><strong>没有符合条件的商品</strong>当前筛选下无需补货，库存状态良好</div></td></tr>';
        updateCart();
        return;
      }
      body.innerHTML = rows
        .map((r) => {
          const selected = cart[r.productId] != null;
          const d = r.detail;
          const days = r.stockoutInDays;
          const daysTag =
            days == null
              ? '<span class="tag tag-grey">充足</span>'
              : days <= 1
              ? '<span class="tag tag-red">≤1 天</span>'
              : days <= 3
              ? `<span class="tag tag-amber">${days} 天</span>`
              : `<span class="tag tag-grey">${days} 天</span>`;
          return `
            <tr class="suggest-row" data-id="${r.productId}">
              <td><input type="checkbox" data-pick="${r.productId}" ${selected ? 'checked' : ''} /></td>
              <td>
                <div style="font-weight:500">${escapeHtml(r.productName)}</div>
                <div style="color:var(--muted);font-size:11.5px">${escapeHtml(r.sku)} · ${r.orderUnit} = ${r.basePerOrderUnit}${r.baseUnit}</div>
              </td>
              <td class="num">${escapeHtml(r.availableText)}</td>
              <td class="num">${Math.round(d.rop).toLocaleString('zh-CN')}</td>
              <td class="num">${daysTag}</td>
              <td class="num"><strong style="color:${r.suggestQtyBase > 0 ? 'var(--primary)' : 'var(--muted)'}">${
                  r.suggestQtyBase > 0 ? r.suggestQtyOrder + ' ' + r.orderUnit : '—'
                }</strong></td>
              <td class="num">
                <div class="qty-adjust">
                  <button type="button" data-step="-1" data-id="${r.productId}">−</button>
                  <input type="number" min="0" data-qty="${r.productId}" value="${selected ? cart[r.productId].qty : r.suggestQtyOrder}" />
                  <button type="button" data-step="1" data-id="${r.productId}">+</button>
                </div>
              </td>
              <td class="num">${fmtMoney(r.unitPriceCents)}<span style="color:var(--muted)">/箱</span></td>
            </tr>
            <tr class="detail-panel ${expandAll ? '' : 'hidden'}" data-panel="${r.productId}">
              <td colspan="8">
                <div class="explain-grid">
                  <div class="explain-cell"><span>现存 / 锁定</span><strong>${d.onHand} / ${d.locked}</strong></div>
                  <div class="explain-cell"><span>在途</span><strong>${d.inTransit}</strong></div>
                  <div class="explain-cell"><span>覆盖期需求</span><strong>${Math.round(d.forecastDemand)}</strong></div>
                  <div class="explain-cell accent"><span>建议订货</span><strong>${r.suggestQtyOrder} ${r.orderUnit}</strong></div>
                </div>
                <div class="explain-reason">${escapeHtml(r.reason)}</div>
                <div class="formula">
                  Q = 覆盖期需求(${Math.round(d.forecastDemand)}) + 安全库存(${Math.round(d.safetyStock)}) − 可用库存(${d.available}) − 在途(${d.inTransit}) = ${Math.round(
                    d.forecastDemand + d.safetyStock - d.available - d.inTransit
                  )}<br />
                  基线 ${d.baseline} · 趋势 ${(d.trend * 100).toFixed(1)}%/天 · 提前期 ${d.coverageDays - 3} 天 + 订货周期 3 天 · 星期因子 [${d.weekdayFactors
                    .map((f) => f.toFixed(2))
                    .join(', ')}] ${d.coldStart ? '· 冷启动降级' : ''}
                </div>
              </td>
            </tr>`;
        })
        .join('');
      updateCart();
    }

    function updateCart() {
      const items = Object.values(cart);
      const count = items.length;
      const amount = items.reduce((sum, i) => sum + i.qty * i.unitPriceCents, 0);
      $('#cart-count').textContent = count;
      $('#cart-amount').textContent = fmtMoney(amount);
      $('#cart-bar').classList.toggle('hidden', count === 0);
    }

    function syncRow(productId, forceQty) {
      const row = list.find((r) => r.productId === productId);
      const input = $(`[data-qty="${productId}"]`);
      const qty = forceQty != null ? forceQty : Number(input.value || 0);
      if (qty > 0) {
        cart[productId] = { qty, unitPriceCents: row.unitPriceCents, name: row.productName };
      } else {
        delete cart[productId];
      }
      const box = $(`[data-pick="${productId}"]`);
      if (box) box.checked = qty > 0;
      updateCart();
    }

    $('#rep-body').addEventListener('click', (e) => {
      const step = e.target.closest('[data-step]');
      if (step) {
        const id = Number(step.dataset.id);
        const input = $(`[data-qty="${id}"]`);
        const next = Math.max(0, Number(input.value || 0) + Number(step.dataset.step));
        input.value = next;
        syncRow(id, next);
        return;
      }
      if (e.target.matches('[data-pick]')) {
        const id = Number(e.target.dataset.pick);
        const row = list.find((r) => r.productId === id);
        const qty = e.target.checked ? Math.max(1, row.suggestQtyOrder) : 0;
        $(`[data-qty="${id}"]`).value = qty;
        syncRow(id, qty);
        return;
      }
      if (e.target.closest('.qty-adjust')) return;
      const tr = e.target.closest('tr.suggest-row');
      if (tr) {
        const panel = $(`[data-panel="${tr.dataset.id}"]`);
        if (panel) panel.classList.toggle('hidden');
      }
    });

    $('#rep-body').addEventListener('change', (e) => {
      if (e.target.matches('[data-qty]')) {
        syncRow(Number(e.target.dataset.qty));
      }
    });

    onlyCheckbox.onchange = () => renderRows(false);
    search.oninput = () => renderRows(false);
    $('#rep-all').onchange = (e) => {
      visibleRows().forEach((r) => {
        if (!r.needsReorder || r.suggestQtyBase <= 0) return;
        const id = r.productId;
        $(`[data-qty="${id}"]`).value = e.target.checked ? r.suggestQtyOrder : 0;
        syncRow(id, e.target.checked ? r.suggestQtyOrder : 0);
      });
    };
    $('#rep-expand').onclick = () => {
      const panels = $$('[data-panel]');
      const expand = panels.some((p) => p.classList.contains('hidden'));
      panels.forEach((p) => p.classList.toggle('hidden', !expand));
      $('#rep-expand').textContent = expand ? '收起全部依据' : '展开全部依据';
    };
    $('#cart-clear').onclick = () => {
      cart = {};
      $$('[data-qty]').forEach((i) => (i.value = 0));
      $$('[data-pick]').forEach((i) => (i.checked = false));
      updateCart();
    };
    $('#cart-submit').onclick = () => submitCart(list, sid);

    renderRows(false);
  };

  async function submitCart(list, storeId) {
    const items = Object.entries(cart).map(([productId, item]) => {
      const row = list.find((r) => r.productId === Number(productId));
      return {
        product_id: Number(productId),
        order_qty: item.qty,
        suggest_qty: row ? row.suggestQtyOrder : 0,
        adjust_reason: row && item.qty !== row.suggestQtyOrder ? '人工调整' : '按建议量',
      };
    });
    if (!items.length) return toast('请先选择要订货的商品', 'error');
    try {
      const order = await API.post('/api/orders', { store_id: storeId, items, remark: '由补货建议生成' });
      toast('订货单 ' + order.orderNo + ' 已创建', 'success');
      cart = {};
      const res = await API.post('/api/orders/' + order.id + '/submit', {});
      if (res.autoApproved) {
        toast('已自动通过审批（命中免审规则）', 'success');
      } else {
        toast('已提交，等待审批：' + (res.approvalReasons[0] || ''), 'success');
      }
      navigate('orders');
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  // ------------------------------------------------------------------ 视图：订货单
  VIEWS.orders = async function (root) {
    const q = S.storeId ? '?store_id=' + S.storeId : '';
    const orders = await API.get('/api/orders' + q);
    const statusCount = {};
    orders.forEach((o) => (statusCount[o.status] = (statusCount[o.status] || 0) + 1));

    root.innerHTML = `
      <div class="card">
        <div class="card-head">
          <h3>订货单列表</h3>
          <div class="toolbar">
            <select id="order-filter">
              <option value="">全部状态（${orders.length}）</option>
              ${Object.keys(STATUS_LABEL)
                .map((k) => `<option value="${k}">${STATUS_LABEL[k][0]}（${statusCount[k] || 0}）</option>`)
                .join('')}
            </select>
            <button class="btn btn-sm" id="order-refresh">刷新</button>
          </div>
        </div>
        <div class="card-body" style="padding:0">
          <table>
            <thead>
              <tr>
                <th>单号</th><th>门店</th><th>品类</th><th class="num">金额</th>
                <th>状态</th><th>创建时间</th><th style="width:120px">操作</th>
              </tr>
            </thead>
            <tbody id="order-body"></tbody>
          </table>
        </div>
      </div>`;

    function draw(filter) {
      const rows = filter ? orders.filter((o) => o.status === filter) : orders;
      const body = $('#order-body');
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="7"><div class="empty"><strong>暂无订货单</strong>可在「智能补货」中生成第一张订货单</div></td></tr>';
        return;
      }
      body.innerHTML = rows
        .map(
          (o) => `<tr>
            <td><a href="#" data-order="${o.id}" style="color:var(--primary);text-decoration:none;font-weight:500">${o.orderNo}</a></td>
            <td>${escapeHtml(o.storeName)}</td>
            <td>${o.items.length} 项</td>
            <td class="num">${fmtMoney(o.totalCents)}</td>
            <td><span class="tag tag-${STATUS_LABEL[o.status][1]}">${STATUS_LABEL[o.status][0]}</span></td>
            <td class="nowrap" style="color:var(--text-2)">${fmtDateTime(o.createdAt)}</td>
            <td><button class="btn btn-sm" data-order="${o.id}">详情</button></td>
          </tr>`
        )
        .join('');
    }

    draw('');
    $('#order-filter').onchange = (e) => draw(e.target.value);
    $('#order-refresh').onclick = () => render();
    $('#order-body').addEventListener('click', (e) => {
      const link = e.target.closest('[data-order]');
      if (link) {
        e.preventDefault();
        showOrderDetail(Number(link.dataset.order));
      }
    });
  };

  async function showOrderDetail(orderId) {
    const o = await API.get('/api/orders/' + orderId);
    const canApprove = ['REGION_MANAGER', 'HQ_PLANNER', 'ADMIN'].includes(S.user.role);
    const canShip = ['WAREHOUSE', 'ADMIN'].includes(S.user.role);
    const canReceive = ['STORE_MANAGER', 'STORE_CLERK', 'ADMIN'].includes(S.user.role);

    const actions = [];
    if (o.status === 'DRAFT') actions.push(`<button class="btn btn-primary" data-act="submit">提交审批</button>`);
    if (o.status === 'SUBMITTED' && canApprove) {
      actions.push(`<button class="btn btn-danger" data-act="reject">驳回</button>`);
      actions.push(`<button class="btn btn-primary" data-act="approve">审批通过</button>`);
    }
    if (o.status === 'APPROVED' && canShip) actions.push(`<button class="btn btn-primary" data-act="confirm">确认发货</button>`);
    if (o.status === 'CONFIRMED' && canReceive) actions.push(`<button class="btn btn-primary" data-act="receive">确认收货</button>`);
    if (['DRAFT', 'SUBMITTED', 'REJECTED'].includes(o.status)) actions.push(`<button class="btn btn-danger" data-act="cancel">取消</button>`);

    const modal = openModal({
      title: '订货单 ' + o.orderNo,
      wide: true,
      body: `
        <div class="grid grid-4" style="margin-bottom:16px">
          <div class="explain-cell"><span>门店</span><strong style="font-size:13px">${escapeHtml(o.storeName)}</strong></div>
          <div class="explain-cell"><span>状态</span><strong style="font-size:13px">${STATUS_LABEL[o.status][0]}</strong></div>
          <div class="explain-cell"><span>金额</span><strong style="font-size:15px">${fmtMoney(o.totalCents)}</strong></div>
          <div class="explain-cell"><span>预计到货</span><strong style="font-size:13px">${fmtDate(o.expectedDeliveryDate)}</strong></div>
        </div>
        <table style="margin-bottom:16px">
          <thead><tr><th>商品</th><th class="num">建议</th><th class="num">订货</th><th class="num">实收</th><th class="num">金额</th><th>调整说明</th></tr></thead>
          <tbody>
            ${o.items
              .map(
                (i) => `<tr>
                  <td>${escapeHtml(i.productName)}</td>
                  <td class="num">${i.suggestQty}</td>
                  <td class="num"><strong>${i.orderQty}</strong> ${i.orderUnit}</td>
                  <td class="num">${o.status === 'RECEIVED' || o.status === 'CLOSED' ? i.receivedQty : '—'}</td>
                  <td class="num">${fmtMoney(i.amountCents)}</td>
                  <td style="color:var(--muted);font-size:12px">${escapeHtml(i.adjustReason || '—')}</td>
                </tr>`
              )
              .join('')}
          </tbody>
        </table>
        <h4 style="font-size:13px;margin-bottom:8px">流转记录</h4>
        <div class="stack-alerts">
          ${o.approvals
            .map(
              (a) => `<div class="alert-line">
                <span class="dot grey"></span>
                <span class="msg"><strong style="color:var(--text)">${ACTION_LABEL[a.action] || a.action}</strong> · ${escapeHtml(a.opinion || '')}</span>
                <span style="color:var(--muted);font-size:11.5px">${fmtDateTime(a.createdAt)}</span>
              </div>`
            )
            .join('')}
        </div>`,
      footer: `<button class="btn" data-close>关闭</button>${actions.join('')}`,
    });

    modal.el.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-act]');
      if (!btn) return;
      const act = btn.dataset.act;
      btn.disabled = true;
      try {
        if (act === 'submit') {
          const res = await API.post(`/api/orders/${orderId}/submit`, {});
          toast(res.autoApproved ? '已自动通过审批' : '已提交，等待审批', 'success');
        } else if (act === 'approve' || act === 'reject' || act === 'confirm' || act === 'cancel') {
          await API.post(`/api/orders/${orderId}/${act}`, { opinion: '' });
          toast('操作成功', 'success');
        } else if (act === 'receive') {
          await receiveFlow(o);
        }
        modal.close();
        render();
      } catch (err) {
        toast(err.message, 'error');
        btn.disabled = false;
      }
    });
  }

  function receiveFlow(order) {
    return new Promise((resolve, reject) => {
      const modal = openModal({
        title: '收货确认 · ' + order.orderNo,
        wide: true,
        body: `
          <p style="color:var(--text-2);font-size:12.5px;margin-bottom:12px">
            默认按订货量整单收货。若实收与订货不符，请修改实收数量，系统将按实收入库并记录到货差异。
          </p>
          <table>
            <thead><tr><th>商品</th><th class="num">订货量</th><th class="num">实收数量</th></tr></thead>
            <tbody>
              ${order.items
                .map(
                  (i) => `<tr>
                    <td>${escapeHtml(i.productName)}</td>
                    <td class="num">${i.orderQty} ${i.orderUnit}</td>
                    <td class="num"><input type="number" min="0" data-recv="${i.productId}" value="${i.orderQty}"
                      style="width:80px;height:28px;text-align:center;border:1px solid var(--border-strong);border-radius:6px" /></td>
                  </tr>`
                )
                .join('')}
            </tbody>
          </table>`,
        footer: `<button class="btn" data-close>取消</button><button class="btn btn-primary" data-confirm>确认收货</button>`,
      });
      modal.el.addEventListener('click', async (e) => {
        if (!e.target.closest('[data-confirm]')) return;
        const items = $$('[data-recv]', modal.el).map((el) => ({
          product_id: Number(el.dataset.recv),
          received_qty: Number(el.value || 0),
        }));
        try {
          const res = await API.post(`/api/orders/${order.id}/receive`, { items, opinion: '门店收货' });
          modal.close();
          if (res.discrepancies.length) {
            toast(`收货完成，${res.discrepancies.length} 项存在到货差异`, 'error');
          } else {
            toast('收货完成，库存已更新', 'success');
          }
          resolve(res);
        } catch (err) {
          toast(err.message, 'error');
          reject(err);
        }
      });
    });
  }

  // ------------------------------------------------------------------ 视图：库存
  VIEWS.inventory = async function (root) {
    const storeId = S.storeId || (S.stores[0] || {}).id;
    const [stock, batches, movements] = await Promise.all([
      API.get('/api/inventory/stock?store_id=' + storeId),
      API.get('/api/inventory/batches?store_id=' + storeId),
      API.get('/api/inventory/movements?store_id=' + storeId + '&limit=60'),
    ]);
    const lowCount = stock.filter((s) => s.availableBase <= 0).length;
    const expiring = batches.filter((b) => b.remainDays <= 3);

    root.innerHTML = `
      <div class="grid grid-4" style="margin-bottom:14px">
        <div class="card metric"><div class="metric-label">在库 SKU</div><div class="metric-value">${stock.length}</div><div class="metric-foot">覆盖 ${stock.filter((s) => s.qtyBase > 0).length} 个有库存商品</div></div>
        <div class="card metric ${lowCount ? 'bad' : 'good'}"><div class="metric-label">断货 SKU</div><div class="metric-value">${lowCount}</div><div class="metric-foot">可用库存为 0，需立即补货</div></div>
        <div class="card metric ${expiring.length ? 'warn' : 'good'}"><div class="metric-label">临期批次</div><div class="metric-value">${expiring.length}</div><div class="metric-foot">3 天内到期</div></div>
        <div class="card metric"><div class="metric-label">库存总值</div><div class="metric-value" style="font-size:21px">${fmtMoneyShort(stock.reduce((s, i) => s + i.valueCents, 0))}</div><div class="metric-foot">按订货单位单价估算</div></div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="toolbar">
            <button class="btn btn-sm active" data-tab="stock">库存</button>
            <button class="btn btn-sm" data-tab="batch">批次效期</button>
            <button class="btn btn-sm" data-tab="move">库存流水</button>
          </div>
          <div class="toolbar">
            <button class="btn btn-sm" data-op="receive">收货入库</button>
            <button class="btn btn-sm" data-op="outbound">领用出库</button>
            <button class="btn btn-sm" data-op="loss">报损</button>
            <button class="btn btn-sm" data-op="stocktake">盘点</button>
          </div>
        </div>
        <div class="card-body" style="padding:0" id="inv-panel"></div>
      </div>`;

    function renderStock() {
      $('#inv-panel').innerHTML = `
        <table>
          <thead><tr><th>商品</th><th>分类</th><th class="num">现存</th><th class="num">可用</th><th class="num">库存值</th><th>存储</th><th>更新时间</th></tr></thead>
          <tbody>
            ${stock
              .map(
                (s) => `<tr>
                  <td><div style="font-weight:500">${escapeHtml(s.productName)}</div><div style="color:var(--muted);font-size:11px">${s.sku}</div></td>
                  <td><span class="tag tag-grey">${escapeHtml(s.categoryName)}</span></td>
                  <td class="num">${escapeHtml(s.qtyText)}</td>
                  <td class="num">${s.availableBase <= 0 ? '<span class="tag tag-red">0</span>' : escapeHtml(s.availableText)}</td>
                  <td class="num">${fmtMoney(s.valueCents)}</td>
                  <td style="color:var(--text-2)">${escapeHtml(s.storageType)}</td>
                  <td class="nowrap" style="color:var(--muted);font-size:12px">${fmtDateTime(s.updatedAt)}</td>
                </tr>`
              )
              .join('')}
          </tbody>
        </table>`;
    }

    function renderBatch() {
      $('#inv-panel').innerHTML = `
        <table>
          <thead><tr><th>批次号</th><th>商品</th><th class="num">数量</th><th>生产日期</th><th>到期日</th><th class="num">剩余天数</th><th>状态</th></tr></thead>
          <tbody>
            ${batches
              .map(
                (b) => `<tr>
                  <td style="font-family:ui-monospace,monospace;font-size:12px">${escapeHtml(b.batchNo)}</td>
                  <td>${escapeHtml(b.productName)}</td>
                  <td class="num">${escapeHtml(b.qtyText)}</td>
                  <td style="color:var(--text-2)">${fmtDate(b.productionDate)}</td>
                  <td style="color:var(--text-2)">${fmtDate(b.expiryDate)}</td>
                  <td class="num">${b.remainDays}</td>
                  <td>${
                    b.expired
                      ? '<span class="tag tag-red">已过期</span>'
                      : b.remainDays <= 3
                      ? '<span class="tag tag-amber">临期</span>'
                      : '<span class="tag tag-green">正常</span>'
                  }</td>
                </tr>`
              )
              .join('') || '<tr><td colspan="7"><div class="empty">暂无批次</div></td></tr>'}
          </tbody>
        </table>`;
    }

    function renderMove() {
      $('#inv-panel').innerHTML = `
        <table>
          <thead><tr><th>时间</th><th>商品</th><th>类型</th><th class="num">数量</th><th>单据</th><th>说明</th></tr></thead>
          <tbody>
            ${movements
              .map((m) => {
                const meta = MOVEMENT_LABEL[m.type] || [m.type, 'grey'];
                return `<tr>
                  <td class="nowrap" style="color:var(--muted);font-size:12px">${fmtDateTime(m.createdAt)}</td>
                  <td>${escapeHtml(m.productName)}</td>
                  <td><span class="tag tag-${meta[1]}">${meta[0]}</span></td>
                  <td class="num" style="color:${m.direction === 'IN' ? 'var(--primary)' : 'var(--danger)'}">
                    ${m.direction === 'IN' ? '+' : '−'}${escapeHtml(m.qtyText)}
                  </td>
                  <td style="font-size:12px;color:var(--text-2)">${escapeHtml(m.refNo || '—')}</td>
                  <td style="color:var(--muted);font-size:12px">${escapeHtml(m.note || '')}</td>
                </tr>`;
              })
              .join('') || '<tr><td colspan="6"><div class="empty">暂无流水</div></td></tr>'}
          </tbody>
        </table>`;
    }

    const renderers = { stock: renderStock, batch: renderBatch, move: renderMove };
    renderStock();

    root.onclick = async (e) => {
      const tab = e.target.closest('[data-tab]');
      if (tab) {
        $$('[data-tab]', root).forEach((b) => b.classList.remove('active'));
        tab.classList.add('active');
        renderers[tab.dataset.tab]();
        return;
      }
      const op = e.target.closest('[data-op]');
      if (!op) return;
      if (op.dataset.op === 'stocktake') return stocktakeFlow(storeId);
      openStockOp(op.dataset.op, storeId);
    };
  };

  function productOptions(products, selected) {
    return products
      .map((p) => `<option value="${p.id}" ${selected === p.id ? 'selected' : ''}>${escapeHtml(p.name)}（${p.orderUnit}=${p.basePerOrderUnit}${p.baseUnit}）</option>`)
      .join('');
  }

  async function openStockOp(type, storeId) {
    const products = await API.get('/api/master/products');
    const config = {
      receive: { title: '收货入库', qtyLabel: '入库数量', hint: '入库将按商品保质期自动生成批次与到期日' },
      outbound: { title: '领用出库', qtyLabel: '出库数量', hint: '出库按 FEFO（先到期先出）自动扣减批次' },
      loss: { title: '报损登记', qtyLabel: '报损数量', hint: '报损计入损耗率，请如实选择原因' },
    }[type];

    const rowHtml = (i) => `<tr>
        <td><select data-p="${i}" style="width:100%;height:32px;border:1px solid var(--border-strong);border-radius:6px">${productOptions(
          products
        )}</select></td>
        <td class="num"><input type="number" min="1" data-q="${i}" value="1" style="width:78px;height:32px;text-align:center;border:1px solid var(--border-strong);border-radius:6px" /></td>
      </tr>`;
    const rowsHtml = (n) => Array.from({ length: n }, (_, i) => rowHtml(i)).join('');
    // 报损通常只损一个单品，初始只给一行；入库/出库/调拨常一次处理多个商品，保留三行
    const initialRows = type === 'loss' ? 1 : 3;

    const modal = openModal({
      title: config.title,
      wide: true,
      body: `
        <p style="color:var(--text-2);font-size:12.5px;margin-bottom:12px">${config.hint}</p>
        <table>
          <thead><tr><th style="width:70%">商品</th><th class="num">${config.qtyLabel}（按订货单位）</th></tr></thead>
          <tbody id="op-rows">${rowsHtml(initialRows)}</tbody>
        </table>
        ${type === 'loss'
          ? `<div class="form-row" style="margin-top:14px"><label>报损原因</label>
              <select id="op-reason">${Object.entries(REASON_LABEL)
                .map(([k, v]) => `<option value="${k}">${v}</option>`)
                .join('')}</select></div>`
          : ''}
        <div class="form-row" style="margin-top:4px"><label>备注</label><input id="op-note" placeholder="选填" /></div>`,
      footer: `<button class="btn" data-close>取消</button><button class="btn" data-add>+ 增加一行</button><button class="btn btn-primary" data-submit>确认${config.title}</button>`,
    });

    let rowCount = initialRows;
    modal.el.addEventListener('click', async (e) => {
      if (e.target.closest('[data-add]')) {
        $('#op-rows', modal.el).insertAdjacentHTML('beforeend', rowHtml(rowCount));
        rowCount += 1;
        return;
      }
      if (!e.target.closest('[data-submit]')) return;
      const items = $$('#op-rows tr', modal.el)
        .map((tr) => {
          const select = $('select', tr);
          const input = $('input', tr);
          return { productId: Number(select.value), qty: Number(input.value || 0) };
        })
        .filter((x) => x.qty > 0);

      if (!items.length) return toast('请至少填写一行数量', 'error');

      const payloadItems = items.map((i) => ({ product_id: i.productId, qty: i.qty, unit: null }));
      // 数量按订货单位换算
      for (const item of payloadItems) {
        const p = products.find((x) => x.id === item.product_id);
        item.unit = p ? p.orderUnit : null;
      }
      const note = $('#op-note', modal.el) ? $('#op-note', modal.el).value : '';
      try {
        if (type === 'receive') {
          await API.post('/api/inventory/receive', { store_id: storeId, items: payloadItems, ref_no: '手工入库' });
        } else if (type === 'outbound') {
          await API.post('/api/inventory/outbound', { store_id: storeId, items: payloadItems, ref_type: 'OUT', note });
        } else {
          const reason = $('#op-reason', modal.el).value;
          await API.post('/api/inventory/loss', { store_id: storeId, items: payloadItems, reason_code: reason, note });
        }
        toast(config.title + '成功', 'success');
        modal.close();
        render();
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

  async function stocktakeFlow(storeId) {
    const draft = await API.post('/api/inventory/stocktake?store_id=' + storeId, {});
    const modal = openModal({
      title: '库存盘点',
      wide: true,
      body: `
        <p style="color:var(--text-2);font-size:12.5px;margin-bottom:12px">
          填写实际盘点数量（按订货单位，可用小数表示零头）。留空或与原值相同的行不会产生调整。
        </p>
        <table>
          <thead><tr><th>商品</th><th class="num">账面</th><th class="num">实盘</th></tr></thead>
          <tbody>
            ${draft.items
              .map(
                (i) => `<tr>
                  <td>${escapeHtml(i.productName)}</td>
                  <td class="num" style="color:var(--text-2)">${escapeHtml(i.bookQtyText)}</td>
                  <td class="num"><input type="number" min="0" step="0.001" data-st="${i.productId}" placeholder="按最小单位"
                    style="width:110px;height:30px;text-align:center;border:1px solid var(--border-strong);border-radius:6px" /></td>
                </tr>`
              )
              .join('')}
          </tbody>
        </table>`,
      footer: `<button class="btn" data-close>取消</button><button class="btn btn-primary" data-submit>提交盘点</button>`,
    });

    modal.el.addEventListener('click', async (e) => {
      if (!e.target.closest('[data-submit]')) return;
      const items = $$('[data-st]', modal.el)
        .filter((el) => el.value !== '')
        .map((el) => ({ product_id: Number(el.dataset.st), actual_qty: Number(el.value), unit: null }));
      if (!items.length) return toast('未填写任何实盘数量', 'error');
      try {
        await API.post(`/api/inventory/stocktake/${draft.id}/confirm`, { store_id: storeId, items });
        toast('盘点完成，差异已调整', 'success');
        modal.close();
        render();
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

  // ------------------------------------------------------------------ 视图：预警
  VIEWS.alerts = async function (root) {
    const q = S.storeId ? '?store_id=' + S.storeId : '';
    const [list, summary] = await Promise.all([
      API.get('/api/alerts?status=OPEN' + (S.storeId ? '&store_id=' + S.storeId : '')),
      API.get('/api/alerts/summary' + q),
    ]);

    root.innerHTML = `
      <div class="grid grid-4" style="margin-bottom:14px">
        <div class="card metric ${summary.total ? 'bad' : 'good'}">
          <div class="metric-label">待处理预警</div>
          <div class="metric-value">${summary.total}</div>
          <div class="metric-foot">含全部类型</div>
        </div>
        ${['STOCKOUT_RISK', 'LOW_STOCK', 'NEAR_EXPIRY']
          .map(
            (key) => `<div class="card metric ${summary.byType[key] ? 'warn' : ''}">
              <div class="metric-label">${ALERT_LABEL[key]}</div>
              <div class="metric-value">${summary.byType[key] || 0}</div>
              <div class="metric-foot">${key === 'STOCKOUT_RISK' ? '预计 3 天内断货' : key === 'LOW_STOCK' ? '低于补货点' : '临近保质期'}</div>
            </div>`
          )
          .join('')}
      </div>
      <div class="card">
        <div class="card-head">
          <h3>预警列表</h3>
          <div class="toolbar">
            <select id="alert-type">
              <option value="">全部类型</option>
              ${Object.entries(ALERT_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}
            </select>
            <button class="btn btn-sm btn-primary" id="scan-btn">立即扫描</button>
          </div>
        </div>
        <div class="card-body" style="padding:0">
          <table>
            <thead><tr><th>级别</th><th>类型</th><th>门店</th><th>商品</th><th>说明</th><th>时间</th><th style="width:130px">操作</th></tr></thead>
            <tbody id="alert-body"></tbody>
          </table>
        </div>
      </div>`;

    function draw(filter) {
      const rows = filter ? list.filter((a) => a.type === filter) : list;
      const body = $('#alert-body');
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="7"><div class="empty"><strong>暂无预警</strong>系统运行正常，或已全部处理完毕</div></td></tr>';
        return;
      }
      body.innerHTML = rows
        .map(
          (a) => `<tr>
            <td><span class="tag tag-${a.level === 'CRITICAL' ? 'red' : a.level === 'WARN' ? 'amber' : 'grey'}">${
            a.level === 'CRITICAL' ? '紧急' : a.level === 'WARN' ? '警告' : '提示'
          }</span></td>
            <td>${ALERT_LABEL[a.type] || a.type}</td>
            <td style="color:var(--text-2)">${escapeHtml(a.storeName)}</td>
            <td>${escapeHtml(a.productName)}</td>
            <td style="color:var(--text-2)">${escapeHtml(a.message)}</td>
            <td class="nowrap" style="color:var(--muted);font-size:12px">${fmtDateTime(a.createdAt)}</td>
            <td>
              <button class="btn btn-sm" data-h="${a.id}">处理</button>
              <button class="btn btn-sm" data-i="${a.id}">忽略</button>
            </td>
          </tr>`
        )
        .join('');
    }

    draw('');
    $('#alert-type').onchange = (e) => draw(e.target.value);
    $('#scan-btn').onclick = async () => {
      try {
        const res = await API.post('/api/alerts/scan' + q, {});
        toast('扫描完成：新增低库存 ' + res.LOW_STOCK + '、断货风险 ' + res.STOCKOUT_RISK + '、临期 ' + res.NEAR_EXPIRY, 'success');
        render();
      } catch (err) {
        toast(err.message, 'error');
      }
    };
    $('#alert-body').addEventListener('click', async (e) => {
      const handleBtn = e.target.closest('[data-h]');
      const ignoreBtn = e.target.closest('[data-i]');
      if (!handleBtn && !ignoreBtn) return;
      const id = handleBtn ? handleBtn.dataset.h : ignoreBtn.dataset.i;
      const action = handleBtn ? 'HANDLE' : 'IGNORE';
      try {
        await API.post(`/api/alerts/${id}/handle`, { action, note: '' });
        toast('已处理', 'success');
        render();
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  };

  // ------------------------------------------------------------------ 视图：基础数据
  VIEWS.master = async function (root) {
    const [products, categories, policies] = await Promise.all([
      API.get('/api/master/products'),
      API.get('/api/master/categories'),
      API.get('/api/master/policies?store_id=' + (S.storeId || (S.stores[0] || {}).id)),
    ]);
    const policyMap = {};
    policies.forEach((p) => (policyMap[p.productId] = p));

    // 人员管理：仅管理员 / 总部计划员可见（离职操作仅管理员可执行）
    const canManage = S.user.role === 'ADMIN' || S.user.role === 'HQ_PLANNER';
    let users = [];
    if (canManage) {
      users = await API.get('/api/master/users');
    }
    const usersCard = canManage
      ? `
      <div class="card">
        <div class="card-head">
          <h3>人员管理</h3>
          <div class="toolbar">
            <input type="text" id="um-search" placeholder="搜索账号 / 姓名" style="width:160px" />
            <span class="hint">在职 ${users.filter((u) => u.isActive).length} / 共 ${users.length} 人</span>
          </div>
        </div>
        <div class="card-body" style="padding:0">
          <table>
            <thead><tr><th>账号</th><th>姓名</th><th>角色</th><th>门店 / 区域</th><th>状态</th><th style="width:110px">操作</th></tr></thead>
            <tbody id="um-body"></tbody>
          </table>
        </div>
      </div>`
      : '';

    root.innerHTML = `
      ${usersCard}
      <div class="card">
        <div class="card-head">
          <h3>商品主数据</h3>
          <div class="toolbar">
            <input type="text" id="md-search" placeholder="搜索商品 / SKU" style="width:180px" />
            <span class="hint">共 ${products.length} 个 SKU · ${categories.length} 个分类</span>
          </div>
        </div>
        <div class="card-body" style="padding:0">
          <table>
            <thead>
              <tr>
                <th>SKU</th><th>商品</th><th>分类</th><th class="num">订货单位</th>
                <th>存储</th><th class="num">保质期</th><th class="num">单价</th>
                <th class="num">提前期</th><th class="num">订货周期</th><th class="num">最大库存</th>
              </tr>
            </thead>
            <tbody id="md-body"></tbody>
          </table>
        </div>
      </div>
      <p style="margin:12px 2px;color:var(--muted);font-size:12px">
        补货策略按「门店 + 商品」维度配置；表中展示当前门店（${escapeHtml((S.stores.find((s) => s.id === (S.storeId || (S.stores[0] || {}).id)) || {}).name || '')}）的参数。
      </p>`;

    function draw(keyword) {
      const kw = (keyword || '').trim().toLowerCase();
      const rows = products.filter((p) => !kw || p.name.toLowerCase().includes(kw) || p.sku.toLowerCase().includes(kw));
      $('#md-body').innerHTML =
        rows
          .map((p) => {
            const pol = policyMap[p.id];
            return `<tr>
              <td style="font-family:ui-monospace,monospace;font-size:12px;color:var(--text-2)">${p.sku}</td>
              <td style="font-weight:500">${escapeHtml(p.name)}</td>
              <td><span class="tag tag-grey">${escapeHtml(p.categoryName)}</span></td>
              <td class="num">${p.orderUnit} = ${p.basePerOrderUnit}${p.baseUnit}</td>
              <td style="color:var(--text-2)">${escapeHtml(p.storageType)}</td>
              <td class="num">${p.shelfLifeDays} 天</td>
              <td class="num">${fmtMoney(p.unitPriceCents)}</td>
              <td class="num">${pol ? pol.leadTimeDays + ' 天' : '—'}</td>
              <td class="num">${pol ? pol.orderCycleDays + ' 天' : '—'}</td>
              <td class="num">${pol && pol.maxStockBase ? (pol.maxStockBase / p.basePerOrderUnit) + ' ' + p.orderUnit : '不限'}</td>
            </tr>`;
          })
          .join('') || '<tr><td colspan="10"><div class="empty">没有匹配的商品</div></td></tr>';
    }

    draw('');
    $('#md-search').oninput = (e) => draw(e.target.value);

    // 人员管理表格与上岗/离职操作
    if (canManage) {
      const ROLE_TXT = ROLE;
      function drawUsers(kw) {
        const k = (kw || '').trim().toLowerCase();
        const rows = users.filter((u) => !k || u.username.toLowerCase().includes(k) || (u.fullName || '').toLowerCase().includes(k));
        $('#um-body').innerHTML =
          rows
            .map(
              (u) => `<tr>
              <td style="font-family:ui-monospace,monospace;font-size:12px;color:var(--text-2)">${escapeHtml(u.username)}</td>
              <td style="font-weight:500">${escapeHtml(u.fullName || u.username)}</td>
              <td><span class="tag tag-grey">${ROLE_TXT[u.role] || u.role}</span></td>
              <td style="color:var(--text-2)">${escapeHtml(u.storeName || u.regionName || '—')}</td>
              <td><span class="tag ${u.isActive ? 'tag-green' : 'tag-red'}">${u.isActive ? '在职' : '离职'}</span></td>
              <td>${
                u.isActive
                  ? u.id === S.user.id
                    ? '<span class="hint">当前账号</span>'
                    : `<button class="btn btn-sm" data-off="${u.id}" data-name="${escapeHtml(u.fullName || u.username)}">离职</button>`
                  : `<button class="btn btn-sm btn-primary" data-on="${u.id}">上岗</button>`
              }</td>
            </tr>`
            )
            .join('') || '<tr><td colspan="6"><div class="empty">没有匹配的账号</div></td></tr>';
      }
      drawUsers('');
      $('#um-search').oninput = (e) => drawUsers(e.target.value);
      $('#um-body').addEventListener('click', async (e) => {
        const off = e.target.closest('[data-off]');
        const on = e.target.closest('[data-on]');
        if (!off && !on) return;
        const id = off ? off.dataset.off : on.dataset.on;
        const active = !!on;
        if (off && !window.confirm(`确认给「${off.dataset.name}」办理离职？离职后该账号将无法登录，且释放其角色注册名额。`)) return;
        try {
          const res = await API.put('/api/master/users/' + id + '/status', { is_active: active });
          toast(res.message || '操作成功', 'success');
          render();
        } catch (err) {
          toast(err.message, 'error');
        }
      });
    }
  };

  // ------------------------------------------------------------------ 事件绑定
  document.addEventListener('DOMContentLoaded', function () {
    // 登录表单
    $('#login-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = $('#login-username').value.trim();
      const password = $('#login-password').value;
      $('#login-error').textContent = '';
      try {
        await doLogin(username, password);
      } catch (err) {
        $('#login-error').textContent = err.message;
      }
    });

    // 登录 / 注册页签切换
    $$('.auth-tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        $$('.auth-tab').forEach((t) => t.classList.toggle('active', t === tab));
        $('#login-form').classList.toggle('hidden', tab.dataset.tab !== 'login');
        $('#register-form').classList.toggle('hidden', tab.dataset.tab !== 'register');
        $('#login-error').textContent = '';
        $('#register-error').textContent = '';
        if (tab.dataset.tab === 'register') initRegisterForm().catch(() => {});
      });
    });

    // 注册表单：角色联动归属选择
    $('#reg-role').addEventListener('change', syncRegisterRows);
    $('#register-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const errEl = $('#register-error');
      errEl.textContent = '';
      const role = $('#reg-role').value;
      const payload = {
        username: $('#reg-username').value.trim(),
        password: $('#reg-password').value,
        full_name: $('#reg-fullname').value.trim(),
        role,
      };
      if (role === 'STORE_MANAGER' || role === 'STORE_CLERK') payload.store_id = Number($('#reg-store').value);
      if (role === 'REGION_MANAGER') payload.region_id = Number($('#reg-region').value);
      try {
        await doRegister(payload);
        toast('注册成功，欢迎加入');
      } catch (err) {
        errEl.textContent = err.message;
      }
    });

    // 演示账号快捷填充
    $$('.chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const [u, p] = chip.dataset.account.split('|');
        $('#login-username').value = u;
        $('#login-password').value = p;
        $('#login-form').dispatchEvent(new Event('submit'));
      });
    });

    // 导航
    $$('.nav-item').forEach((item) => {
      item.addEventListener('click', () => navigate(item.dataset.view));
    });

    window.addEventListener('hashchange', () => {
      const v = location.hash.replace('#', '');
      if (v && VIEWS[v] && v !== S.view) navigate(v, true);
    });

    $('#logout-btn').addEventListener('click', () => logout(false));
    $('#refresh-btn').addEventListener('click', () => render());

    // 窗口尺寸变化重绘图表
    let resizeTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (S.view === 'dashboard') render();
      }, 260);
    });

    // 自动登录
    initRegisterForm().catch(() => {});
    if (S.token) {
      bootApp().catch((err) => {
        console.error('启动失败', err);
        logout(true);
      });
    }
  });
})();
