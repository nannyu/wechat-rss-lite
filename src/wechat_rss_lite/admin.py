from __future__ import annotations


ADMIN_HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>wechat-rss-lite</title>
  <style>
    :root { color-scheme: light; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f7f7f4; color: #222; }
    header { background: #1f2933; color: white; padding: 18px 24px; }
    main { max-width: 1080px; margin: 0 auto; padding: 24px; display: grid; gap: 18px; }
    section { background: white; border: 1px solid #deded8; border-radius: 8px; padding: 18px; }
    h1 { margin: 0; font-size: 22px; }
    h2 { margin: 0 0 12px; font-size: 16px; }
    label { display: grid; gap: 6px; margin: 10px 0; font-size: 13px; color: #4b5563; }
    input, textarea, select { padding: 10px 12px; border: 1px solid #c9c9c1; border-radius: 6px; font: inherit; }
    textarea { min-height: 96px; resize: vertical; }
    button { padding: 9px 12px; border: 1px solid #1f2933; border-radius: 6px; background: #1f2933; color: white; cursor: pointer; }
    button.secondary { background: white; color: #1f2933; }
    button:disabled { cursor: not-allowed; opacity: .62; }
    pre { overflow: auto; background: #f2f2ed; padding: 12px; border-radius: 6px; min-height: 48px; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; }
    .status-card { margin-top: 14px; border: 1px solid #deded8; border-radius: 8px; padding: 14px; background: #fbfbf8; display: grid; gap: 6px; }
    .status-line { display: flex; align-items: center; gap: 8px; font-weight: 700; }
    .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #9ca3af; }
    .status-card.ok .status-dot { background: #16a34a; }
    .status-card.warn .status-dot { background: #d97706; }
    .status-card.error .status-dot { background: #dc2626; }
    .status-details { font-size: 13px; color: #6b7280; }
    .raw-details { margin-top: 10px; }
    .raw-details summary { cursor: pointer; color: #4b5563; font-size: 13px; }
    .result-list { margin-top: 14px; display: grid; gap: 10px; }
    .result-item { border: 1px solid #deded8; border-radius: 8px; padding: 12px; display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: center; background: #fbfbf8; }
    .result-body { display: grid; grid-template-columns: 48px 1fr; gap: 12px; align-items: center; min-width: 0; }
    .result-avatar { width: 48px; height: 48px; border-radius: 8px; object-fit: cover; background: #e5e7eb; color: #4b5563; display: grid; place-items: center; font-weight: 700; overflow: hidden; }
    .result-avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .result-info { min-width: 0; }
    .result-title { font-weight: 700; }
    .result-meta { margin-top: 4px; color: #6b7280; font-size: 13px; }
    .result-desc { margin-top: 6px; color: #4b5563; font-size: 13px; line-height: 1.5; overflow-wrap: anywhere; }
    .empty-state { margin-top: 14px; color: #6b7280; background: #f2f2ed; border-radius: 6px; padding: 12px; }
    .stack { display: grid; gap: 10px; margin-top: 14px; }
    .item-card { border: 1px solid #deded8; border-radius: 8px; padding: 12px; background: #fbfbf8; display: grid; gap: 10px; }
    .item-top { display: flex; justify-content: space-between; gap: 12px; align-items: start; flex-wrap: wrap; }
    .item-title { font-weight: 700; }
    .item-url { word-break: break-all; color: #4b5563; font-size: 13px; }
    .pill { display: inline-flex; border: 1px solid #deded8; border-radius: 999px; padding: 2px 8px; font-size: 12px; color: #4b5563; background: white; }
    .switch-button { border-radius: 999px; padding: 5px 10px; min-width: 72px; font-size: 12px; }
    .switch-button.off { background: white; color: #4b5563; border-color: #c9c9c1; }
    dialog { border: 0; border-radius: 8px; padding: 0; width: min(420px, calc(100vw - 32px)); box-shadow: 0 24px 80px rgba(15, 23, 42, .28); }
    dialog::backdrop { background: rgba(15, 23, 42, .45); }
    .modal { padding: 22px; display: grid; gap: 16px; }
    .modal-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
    .modal-head h2 { margin: 0; }
    .icon-button { width: 34px; height: 34px; padding: 0; border-radius: 50%; font-size: 18px; line-height: 1; }
    .qr-box { min-height: 248px; border: 1px solid #deded8; border-radius: 8px; background: #fbfbf8; display: grid; place-items: center; text-align: center; padding: 18px; color: #4b5563; }
    .qr-box img { width: 220px; height: 220px; object-fit: contain; }
    .muted { color: #6b7280; font-size: 13px; line-height: 1.6; margin: 0; }
  </style>
</head>
<body>
  <header><h1>wechat-rss-lite</h1></header>
  <main>
    <section>
      <h2>状态</h2>
      <div class="row">
        <button onclick="loadStatus()">刷新</button>
        <button onclick="createLogin()">扫码登录</button>
        <button class="secondary" onclick="validateCredential()">验证登录</button>
        <button class="secondary" onclick="clearCredential()">清除登录状态</button>
      </div>
      <div id="statusCard" class="status-card warn">
        <div class="status-line"><span class="status-dot"></span><span id="statusTitle">未登录</span></div>
        <div id="statusDetails" class="status-details">还没有保存登录凭证。请创建扫码登录会话。</div>
      </div>
      <details class="raw-details">
        <summary>查看原始状态</summary>
        <pre id="statusRaw"></pre>
      </details>
    </section>
    <section>
      <h2>健康检查与限频</h2>
      <div class="row">
        <button onclick="loadStats()">刷新统计</button>
        <button class="secondary" onclick="applyRecommendedRateLimit()">应用推荐值</button>
      </div>
      <p class="muted">推荐值：每分钟最多 6 次，单次间隔 10 秒。用于降低连续访问带来的验证风险；如遇验证，应暂停该公众号轮询并人工处理。</p>
      <label>每分钟请求上限 <input id="ratePerMinute" type="number" min="1" step="1" placeholder="6"></label>
      <label>最小请求间隔（秒） <input id="rateInterval" type="number" min="0" step="0.1" placeholder="10.0"></label>
      <button onclick="saveRateLimit()">保存限频配置</button>
      <div id="rateLimitSummary" class="status-card">
        <div class="status-line"><span class="status-dot"></span><span>等待统计数据</span></div>
        <div class="status-details">用于控制请求节奏和观察等待情况。</div>
      </div>
      <pre id="statsRaw"></pre>
    </section>
    <dialog id="loginDialog">
      <div class="modal">
        <div class="modal-head">
          <h2>扫码登录</h2>
          <button class="icon-button secondary" onclick="closeLoginDialog()" aria-label="关闭">×</button>
        </div>
        <div id="qrBox" class="qr-box">正在创建登录会话...</div>
        <p id="loginHint" class="muted"></p>
        <details class="raw-details">
          <summary>查看登录会话</summary>
          <pre id="login"></pre>
        </details>
        <div class="row">
          <button onclick="refreshLoginSession()">刷新状态</button>
          <button class="secondary" onclick="completeLogin()">完成登录</button>
        </div>
      </div>
    </dialog>
    <section>
      <h2>公众号搜索</h2>
      <label>关键词 <input id="query" placeholder="公众号名称"></label>
      <button onclick="searchAccounts()">搜索</button>
      <div id="accountResults" class="result-list"></div>
      <details class="raw-details">
        <summary>查看原始搜索结果</summary>
        <pre id="accounts"></pre>
      </details>
    </section>
    <section>
      <h2>批量导入</h2>
      <label>粘贴列表 <textarea id="bulkText" placeholder="支持逗号、空格、换行分隔，例如：公众号A, 公众号B&#10;公众号C"></textarea></label>
      <label>上传文件 <input id="bulkFile" type="file" accept=".txt,.csv,.xlsx"></label>
      <button onclick="importSubscriptions()">导入订阅</button>
      <pre id="importResult"></pre>
    </section>
    <section>
      <h2>黑名单管理</h2>
      <label>公众号 ID <input id="blacklistId" placeholder="高频触发验证码的 account-id"></label>
      <label>原因 <input id="blacklistReason" placeholder="例如：高频触发验证码"></label>
      <button onclick="addBlacklist()">加入黑名单</button>
      <div id="blacklistList" class="stack"></div>
      <pre id="blacklistRaw"></pre>
    </section>
    <section>
      <h2>RSS 与分类</h2>
      <div class="row">
        <button onclick="copyText(`${location.origin}/feeds/all.rss`)">复制聚合 RSS</button>
        <button class="secondary" onclick="location.href='/subscriptions/export?format=opml'">导出 OPML</button>
        <button class="secondary" onclick="location.href='/subscriptions/export?format=csv'">导出 CSV</button>
      </div>
      <label>分类名称 <input id="categoryName" placeholder="例如：科技"></label>
      <label>分类描述 <input id="categoryDescription" placeholder="可选"></label>
      <label>颜色 <input id="categoryColor" placeholder="blue"></label>
      <button onclick="createCategory()">创建分类</button>
      <div id="categoryList" class="stack"></div>
      <pre id="categoryRaw"></pre>
    </section>
    <section>
      <h2>订阅</h2>
      <label>订阅 ID <input id="sid" placeholder="account-id"></label>
      <label>标题 <input id="title" placeholder="公众号名称"></label>
      <div class="row">
        <label>历史页数 <input id="historyPages" type="number" min="1" max="50" step="1" value="5"></label>
        <label>每页数量 <input id="historyPageSize" type="number" min="1" max="100" step="1" value="20"></label>
        <label>历史关键词 <input id="historyKeyword" placeholder="可选"></label>
      </div>
      <div class="row">
        <button onclick="subscribe()">添加订阅</button>
        <button class="secondary" onclick="pollAll()">轮询全部</button>
      </div>
      <div id="subscriptionList" class="stack"></div>
      <div id="articleList" class="stack"></div>
      <pre id="subs"></pre>
      <pre id="articles"></pre>
    </section>
  </main>
  <script>
    let loginSession = "";
    let subscribedIds = new Set();
    let categoriesCache = [];
    const recommendedRateLimit = { per_minute: 6, min_interval_seconds: 10 };
    async function requestJson(path, options) {
      const res = await fetch(path, { headers: { "content-type": "application/json" }, ...options });
      const text = await res.text();
      try { return { ok: res.ok, data: JSON.parse(text), text }; } catch { return { ok: res.ok, data: null, text }; }
    }
    async function requestForm(path, formData) {
      const res = await fetch(path, { method: "POST", body: formData });
      const text = await res.text();
      try { return { ok: res.ok, data: JSON.parse(text), text }; } catch { return { ok: res.ok, data: null, text }; }
    }
    async function api(path, options) {
      const result = await requestJson(path, options);
      return result.data ? JSON.stringify(result.data, null, 2) : result.text;
    }
    async function loadStatus() {
      const health = await requestJson("/health");
      document.getElementById("statusRaw").textContent = health.data ? JSON.stringify(health.data, null, 2) : health.text;
      renderStatus(health.data);
      renderRateLimit(health.data && health.data.rate_limit);
      await loadCategories();
      await loadSubscriptions();
      await loadBlacklist();
    }
    async function createLogin() {
      loginDialog.showModal();
      qrBox.textContent = "正在创建登录会话...";
      loginHint.textContent = "";
      const result = await requestJson("/login/sessions", { method: "POST", body: "{}" });
      login.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      if (result.data) {
        loginSession = result.data.id || "";
        renderLoginDialog(result.data);
      } else {
        renderLoginError(result.text || "创建登录会话失败");
      }
    }
    async function refreshLoginSession() {
      if (!loginSession) return;
      const result = await requestJson(`/login/sessions/${loginSession}`);
      login.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      if (result.data) renderLoginDialog(result.data);
    }
    async function completeLogin() {
      const result = await requestJson(`/login/sessions/${loginSession || "manual"}/complete`, { method: "POST", body: "{}" });
      login.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      loginHint.textContent = result.ok ? "登录凭证已保存。" : "登录完成失败。";
    }
    function renderLoginDialog(session) {
      if (session.qrcode_url) {
        qrBox.innerHTML = `<img src="${escapeAttr(session.qrcode_url)}" alt="登录二维码">`;
        loginHint.textContent = session.message || "请使用微信扫描公众平台登录二维码。";
      } else {
        qrBox.innerHTML = "<div>当前未返回微信登录二维码</div>";
        loginHint.textContent = session.message || "真实登录二维码应由微信公众平台 scanloginqrcode?action=getqrcode 返回；请检查 LOGIN_PROVIDER 配置。";
      }
    }
    function renderLoginError(message) {
      qrBox.textContent = message;
      loginHint.textContent = "请检查服务端登录提供器配置。";
    }
    function closeLoginDialog() { loginDialog.close(); }
    function renderStatus(data) {
      const credential = data && data.credential;
      if (!credential || !credential.configured) {
        const detail = credential && credential.stored
          ? `检测到 ${credential.account_name || "本地"} 演示/手工凭证，但还没有可用的微信登录凭证。请使用真实 LoginProvider 扫码登录，或清除当前登录状态。`
          : "还没有保存微信登录凭证。请创建扫码登录会话。";
        setStatus("warn", "未登录微信", detail);
        return;
      }
      if (credential.expired) {
        setStatus("error", "登录已过期", `账号 ${credential.account_name || "默认账号"} 的凭证已过期，请重新扫码。`);
        return;
      }
      const expiry = credential.expires_at ? `，有效期至 ${formatTime(credential.expires_at)}` : "";
      setStatus("ok", "已登录", `账号 ${credential.account_name || "默认账号"} 已可用${expiry}。`);
    }
    function setStatus(kind, title, detail) {
      statusCard.className = `status-card ${kind}`;
      statusTitle.textContent = title;
      statusDetails.textContent = detail;
    }
    async function clearCredential() {
      const result = await requestJson("/credentials/default", { method: "DELETE" });
      document.getElementById("statusRaw").textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      await loadStatus();
    }
    async function validateCredential() {
      setStatus("warn", "正在验证登录", "正在请求微信公众平台确认当前 token/cookie 是否仍然有效。");
      const result = await requestJson("/credentials/default/validate", { method: "POST", body: "{}" });
      document.getElementById("statusRaw").textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      if (result.data && result.data.valid) {
        setStatus("ok", "登录有效", `微信侧验证通过：${result.data.account_name || result.data.username || "当前账号"}。`);
        await loadStatus();
      } else {
        setStatus("error", "登录无效", result.data ? `微信侧验证失败：${result.data.reason || "unknown"}` : result.text);
      }
    }
    async function loadStats() {
      const result = await requestJson("/stats");
      statsRaw.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      renderRateLimit(result.data && result.data.rate_limit);
    }
    async function saveRateLimit() {
      const payload = {
        per_minute: Number(ratePerMinute.value || recommendedRateLimit.per_minute),
        min_interval_seconds: Number(rateInterval.value || recommendedRateLimit.min_interval_seconds)
      };
      const result = await requestJson("/rate-limit", { method: "PUT", body: JSON.stringify(payload) });
      statsRaw.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      renderRateLimit(result.data);
    }
    async function applyRecommendedRateLimit() {
      ratePerMinute.value = recommendedRateLimit.per_minute;
      rateInterval.value = recommendedRateLimit.min_interval_seconds;
      await saveRateLimit();
    }
    function renderRateLimit(config) {
      if (!config) return;
      ratePerMinute.value = config.per_minute;
      rateInterval.value = config.min_interval_seconds;
      rateLimitSummary.className = "status-card ok";
      rateLimitSummary.innerHTML = `
        <div class="status-line"><span class="status-dot"></span><span>限频已启用</span></div>
        <div class="status-details">当前窗口 ${config.requests_in_current_window}/${config.per_minute}，剩余 ${config.remaining_in_current_window}；最小间隔 ${config.min_interval_seconds} 秒；累计等待 ${config.total_waits} 次，共 ${config.total_wait_seconds} 秒。</div>
      `;
    }
    function formatTime(value) {
      try { return new Date(value).toLocaleString(); } catch { return value; }
    }
    function escapeAttr(value) {
      return String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;").replaceAll("<", "&lt;");
    }
    async function searchAccounts() {
      accountResults.innerHTML = '<div class="empty-state">正在搜索...</div>';
      const result = await requestJson(`/accounts/search?query=${encodeURIComponent(query.value)}`);
      accounts.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      renderAccountResults(Array.isArray(result.data) ? result.data : []);
    }
    function renderAccountResults(items) {
      accountResults.innerHTML = "";
      if (!items.length) {
        accountResults.innerHTML = '<div class="empty-state">没有搜索结果。接入 AccountProvider 后，这里会显示可订阅的公众号。</div>';
        return;
      }
      for (const item of items) {
        const node = document.createElement("div");
        node.className = "result-item";
        const body = document.createElement("div");
        body.className = "result-body";
        const avatar = document.createElement("div");
        avatar.className = "result-avatar";
        renderAvatar(avatar, item.avatar_url, item.name || item.title || item.id);
        const info = document.createElement("div");
        info.className = "result-info";
        const title = document.createElement("div");
        title.className = "result-title";
        title.textContent = item.name || item.title || item.id;
        const meta = document.createElement("div");
        meta.className = "result-meta";
        meta.textContent = [item.id, item.alias].filter(Boolean).join(" · ");
        info.append(title, meta);
        if (item.description) {
          const desc = document.createElement("div");
          desc.className = "result-desc";
          desc.textContent = item.description;
          info.append(desc);
        }
        body.append(avatar, info);
        const button = document.createElement("button");
        markSubscribeButton(button, subscribedIds.has(item.id));
        button.onclick = () => subscribeAccount(item, button);
        node.append(body, button);
        accountResults.append(node);
      }
    }
    function markSubscribeButton(button, subscribed) {
      button.textContent = subscribed ? "订阅成功" : "加入订阅";
      button.disabled = subscribed;
      button.className = subscribed ? "secondary" : "";
    }
    async function subscribeAccount(item, button) {
      markSubscribeButton(button, true);
      const subscription = {
        id: item.id,
        title: item.name || item.title || item.id,
        account_id: item.id,
        source_url: item.source_url || "",
        avatar_url: item.avatar_url || "",
        description: item.description || "",
        category_id: defaultCategoryId()
      };
      const result = await requestJson("/subscriptions", { method: "POST", body: JSON.stringify(subscription) });
      accounts.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      if (!result.ok) {
        markSubscribeButton(button, subscribedIds.has(item.id));
        return;
      }
      subscribedIds.add(item.id);
      await loadSubscriptions();
    }
    async function subscribe() {
      await requestJson("/subscriptions", { method: "POST", body: JSON.stringify({ id: sid.value, title: title.value, account_id: sid.value, category_id: defaultCategoryId() }) });
      await loadSubscriptions();
    }
    async function importSubscriptions() {
      const form = new FormData();
      form.append("text", bulkText.value || "");
      if (bulkFile.files[0]) form.append("file", bulkFile.files[0]);
      importResult.textContent = "正在导入...";
      const result = await requestForm("/subscriptions/import", form);
      importResult.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      await loadSubscriptions();
    }
    async function pollAll() {
      subs.textContent = await api("/poll", { method: "POST", body: "{}" });
      await loadSubscriptions();
    }
    async function loadSubscriptions() {
      const result = await requestJson("/subscriptions");
      subs.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      const items = Array.isArray(result.data) ? result.data : [];
      subscribedIds = new Set(items.map(item => item.id));
      renderSubscriptions(items);
    }
    function renderSubscriptions(items) {
      subscriptionList.innerHTML = "";
      if (!items.length) {
        subscriptionList.innerHTML = '<div class="empty-state">暂无订阅。可以从搜索结果加入，或手动/批量导入。</div>';
        return;
      }
      for (const item of items) {
        const node = document.createElement("div");
        node.className = "item-card";
        node.innerHTML = `
          <div class="item-top">
            <div class="result-body">
              <div class="result-avatar"></div>
              <div class="result-info">
                <div class="item-title"></div>
                <div class="result-meta"></div>
                <div class="result-desc"></div>
              </div>
            </div>
            <button class="switch-button" type="button"></button>
          </div>
          <div class="item-url"></div>
          <div class="item-url history-url"></div>
          <label>分类 <select class="category-select"></select></label>
          <div class="row"></div>
        `;
        renderAvatar(node.querySelector(".result-avatar"), item.avatar_url, item.title || item.id);
        node.querySelector(".item-title").textContent = item.title || item.id;
        node.querySelector(".result-meta").textContent = item.account_id || item.id;
        const description = node.querySelector(".result-desc");
        description.textContent = item.description || "";
        description.hidden = !item.description;
        renderSubscriptionSwitch(node.querySelector(".switch-button"), item);
        node.querySelector(".item-url").textContent = item.feed_url || `/feeds/${item.id}.rss`;
        node.querySelector(".history-url").textContent = item.history_feed_url || `/feeds/${item.id}/history.rss`;
        renderCategorySelect(node.querySelector(".category-select"), item);
        const actions = node.querySelector(".row");
        actions.append(
          actionButton("复制 RSS", () => copyText(item.feed_url || `/feeds/${item.id}.rss`)),
          actionButton("复制历史 RSS", () => copyText(item.history_feed_url || `/feeds/${item.id}/history.rss`), "secondary"),
          actionButton("轮询", () => pollSubscription(item.id)),
          actionButton("获取历史", () => fetchHistory(item.id)),
          actionButton("本地文章", () => loadLocalArticles(item.id), "secondary"),
          actionButton("加入黑名单", () => blacklistSubscription(item), "secondary"),
          actionButton("删除", () => deleteSubscription(item.id), "secondary"),
        );
        subscriptionList.append(node);
      }
    }
    function renderAvatar(container, url, label) {
      container.textContent = "";
      if (!url) {
        container.textContent = (label || "?").slice(0, 1);
        return;
      }
      const image = document.createElement("img");
      image.src = url;
      image.alt = `${label || "公众号"} 头像`;
      image.loading = "lazy";
      image.onerror = () => {
        container.textContent = (label || "?").slice(0, 1);
      };
      container.append(image);
    }
    function renderSubscriptionSwitch(button, item) {
      button.textContent = item.enabled ? "启用" : "关闭";
      button.className = `switch-button${item.enabled ? "" : " off"}`;
      button.setAttribute("aria-pressed", item.enabled ? "true" : "false");
      button.onclick = () => toggleSubscription(item, button);
    }
    function actionButton(label, handler, className = "") {
      const button = document.createElement("button");
      button.textContent = label;
      if (className) button.className = className;
      button.onclick = handler;
      return button;
    }
    async function copyText(value) {
      await navigator.clipboard.writeText(value);
      subs.textContent = `已复制 RSS 地址：${value}`;
    }
    async function pollSubscription(id) {
      subs.textContent = await api(`/subscriptions/${encodeURIComponent(id)}/poll`, { method: "POST", body: "{}" });
    }
    async function toggleSubscription(item, button) {
      const nextEnabled = !item.enabled;
      const previous = { ...item };
      item.enabled = nextEnabled;
      renderSubscriptionSwitch(button, item);
      const result = await requestJson(`/subscriptions/${encodeURIComponent(item.id)}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: nextEnabled })
      });
      subs.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      if (!result.ok) {
        item.enabled = previous.enabled;
        renderSubscriptionSwitch(button, item);
        return;
      }
      await loadSubscriptions();
    }
    function defaultCategoryId() {
      return categoriesCache[0] ? categoriesCache[0].id : null;
    }
    async function loadCategories() {
      const result = await requestJson("/categories");
      categoryRaw.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      categoriesCache = Array.isArray(result.data) ? result.data : [];
      renderCategories(categoriesCache);
    }
    async function createCategory() {
      const result = await requestJson("/categories", {
        method: "POST",
        body: JSON.stringify({
          name: categoryName.value,
          description: categoryDescription.value,
          color: categoryColor.value || "blue"
        })
      });
      categoryRaw.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      categoryName.value = "";
      categoryDescription.value = "";
      categoryColor.value = "";
      await loadCategories();
      await loadSubscriptions();
    }
    function renderCategories(items) {
      categoryList.innerHTML = "";
      if (!items.length) {
        categoryList.innerHTML = '<div class="empty-state">暂无分类。创建分类后，可给订阅分组并生成分类 RSS。</div>';
        return;
      }
      for (const item of items) {
        const node = document.createElement("div");
        node.className = "item-card";
        node.innerHTML = `<div class="item-top"><div><div class="item-title"></div><div class="result-meta"></div></div><span class="pill"></span></div><div class="item-url"></div><div class="row"></div>`;
        node.querySelector(".item-title").textContent = item.name;
        node.querySelector(".result-meta").textContent = item.description || "";
        node.querySelector(".pill").textContent = `${item.subscription_count || 0} 个订阅`;
        node.querySelector(".item-url").textContent = `${location.origin}/feeds/categories/${item.id}.rss`;
        node.querySelector(".row").append(
          actionButton("复制分类 RSS", () => copyText(`${location.origin}/feeds/categories/${item.id}.rss`)),
          actionButton("删除分类", () => deleteCategory(item.id), "secondary")
        );
        categoryList.append(node);
      }
    }
    async function deleteCategory(id) {
      await requestJson(`/categories/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadCategories();
      await loadSubscriptions();
    }
    function renderCategorySelect(select, item) {
      select.innerHTML = '<option value="">未分类</option>';
      for (const category of categoriesCache) {
        const option = document.createElement("option");
        option.value = category.id;
        option.textContent = category.name;
        option.selected = item.category_id === category.id;
        select.append(option);
      }
      select.onchange = () => setSubscriptionCategory(item.id, select.value || null);
    }
    async function setSubscriptionCategory(id, categoryId) {
      await requestJson(`/subscriptions/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify({ category_id: categoryId ? Number(categoryId) : null })
      });
      await loadCategories();
      await loadSubscriptions();
    }
    async function fetchHistory(id) {
      const params = new URLSearchParams({
        pages: historyPages.value || "5",
        page_size: historyPageSize.value || "20",
        keyword: historyKeyword.value || ""
      });
      subs.textContent = "正在获取历史文章...";
      subs.textContent = await api(`/subscriptions/${encodeURIComponent(id)}/history?${params}`, { method: "POST", body: "{}" });
      await loadLocalArticles(id);
    }
    async function loadLocalArticles(id) {
      const result = await requestJson(`/subscriptions/${encodeURIComponent(id)}/articles?limit=50`);
      articles.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      renderArticleList(Array.isArray(result.data) ? result.data : []);
    }
    function renderArticleList(items) {
      articleList.innerHTML = "";
      if (!items.length) {
        articleList.innerHTML = '<div class="empty-state">暂无本地文章。</div>';
        return;
      }
      for (const item of items) {
        const node = document.createElement("div");
        node.className = "item-card";
        node.innerHTML = `
          <div class="item-top">
            <div>
              <div class="item-title"></div>
              <div class="result-meta"></div>
            </div>
            <span class="pill"></span>
          </div>
          <div class="item-url"></div>
        `;
        node.querySelector(".item-title").textContent = item.title || item.url;
        node.querySelector(".result-meta").textContent = item.published_at || item.account_name || "";
        node.querySelector(".pill").textContent = item.content_type || "article";
        node.querySelector(".item-url").textContent = item.url;
        articleList.append(node);
      }
    }
    async function blacklistSubscription(item) {
      await requestJson("/blacklist", {
        method: "POST",
        body: JSON.stringify({ account_id: item.account_id || item.id, reason: "高频触发验证码" })
      });
      await loadBlacklist();
    }
    async function deleteSubscription(id) {
      await requestJson(`/subscriptions/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadSubscriptions();
    }
    async function loadVerifications() {
      if (!document.getElementById("verificationList") || !document.getElementById("verifications")) return;
      const result = await requestJson("/verifications?status=pending");
      verifications.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      renderVerifications(Array.isArray(result.data) ? result.data : []);
    }
    function renderVerifications(items) {
      if (!document.getElementById("verificationList")) return;
      verificationList.innerHTML = "";
      if (!items.length) {
        verificationList.innerHTML = '<div class="empty-state">暂无待处理验证。</div>';
        return;
      }
      for (const item of items) {
        const node = document.createElement("div");
        node.className = "item-card";
        const title = item.message || `${item.kind} 验证`;
        const target = item.target || item.id;
        node.innerHTML = `<div class="item-top"><div><div class="item-title"></div><div class="result-meta"></div></div><span class="pill"></span></div><div class="row"></div>`;
        node.querySelector(".item-title").textContent = title;
        node.querySelector(".result-meta").textContent = target;
        node.querySelector(".pill").textContent = item.status;
        const actions = node.querySelector(".row");
        if (item.verify_url) actions.append(actionButton("打开验证", () => window.open(item.verify_url, "_blank")));
        actions.append(actionButton("标记已处理", () => resolveVerification(item.id), "secondary"));
        verificationList.append(node);
      }
    }
    async function resolveVerification(id) {
      await requestJson(`/verifications/${encodeURIComponent(id)}/resolve`, { method: "POST", body: "{}" });
      await loadVerifications();
    }
    async function addBlacklist() {
      await requestJson("/blacklist", {
        method: "POST",
        body: JSON.stringify({ account_id: blacklistId.value, reason: blacklistReason.value })
      });
      blacklistId.value = "";
      blacklistReason.value = "";
      await loadBlacklist();
    }
    async function loadBlacklist() {
      const result = await requestJson("/blacklist");
      blacklistRaw.textContent = result.data ? JSON.stringify(result.data, null, 2) : result.text;
      renderBlacklist(Array.isArray(result.data) ? result.data : []);
    }
    function renderBlacklist(items) {
      blacklistList.innerHTML = "";
      if (!items.length) {
        blacklistList.innerHTML = '<div class="empty-state">暂无黑名单。加入后，这些公众号会跳过轮询。</div>';
        return;
      }
      for (const item of items) {
        const node = document.createElement("div");
        node.className = "item-card";
        node.innerHTML = `<div class="item-top"><div><div class="item-title"></div><div class="result-meta"></div></div><span class="pill">跳过轮询</span></div><div class="row"></div>`;
        node.querySelector(".item-title").textContent = item.account_id;
        node.querySelector(".result-meta").textContent = item.reason || "未填写原因";
        node.querySelector(".row").append(actionButton("移出黑名单", () => removeBlacklist(item.account_id), "secondary"));
        blacklistList.append(node);
      }
    }
    async function removeBlacklist(accountId) {
      await requestJson(`/blacklist/${encodeURIComponent(accountId)}`, { method: "DELETE" });
      await loadBlacklist();
    }
    loadStatus();
  </script>
</body>
</html>
"""
