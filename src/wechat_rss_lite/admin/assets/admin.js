    // Tab Navigation
    function switchTab(tabId) {
      document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
      document.querySelectorAll('.page-section').forEach(el => el.classList.remove('active'));
      document.getElementById('tab-' + tabId).classList.add('active');
      document.getElementById('sec-' + tabId).classList.add('active');
      if (tabId === 'reader') loadDownloadedArticles();
    }

    // Toast Notification System
    function showToast(message, isError = false) {
      const container = document.getElementById('toast-container');
      const toast = document.createElement('div');
      toast.className = 'toast' + (isError ? ' error' : '');
      toast.textContent = message;
      container.appendChild(toast);
      
      setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
      }, 3000);
    }

    // App State & API
    let loginSession = "";
    let loginConfirmUrl = "";
    let loginCompleting = false;
    let subscribedIds = new Set();
    let categoriesCache = [];
    let subscriptionsCache = [];
    let downloadedArticles = [];
    let currentReaderArticleUrl = "";
    let rssBuilderMode = "subscriptions";
    let selectedRssSubscriptions = new Set();
    let selectedRssCategories = new Set();
    const recommendedRateLimit = { per_minute: 6, min_interval_seconds: 10 };
    let adminToken = localStorage.getItem("wechat-rss-lite-admin-token") || "";
    const ADMIN_TOKEN_ERROR = "管理令牌只能包含英文字母、数字和常见符号。请从项目根目录 .env 复制 ADMIN_API_TOKEN，不要输入中文或说明文字。";

    function assertByteStringHeaderValue(name, value) {
      for (const ch of value) {
        if (ch.charCodeAt(0) > 255) {
          throw new Error(`${name} ${ADMIN_TOKEN_ERROR}`);
        }
      }
    }

    function authHeaders(extra = {}) {
      const headers = { ...extra };
      if (!adminToken) {
        return headers;
      }
      const token = adminToken.trim();
      assertByteStringHeaderValue("Authorization", `Bearer ${token}`);
      headers.Authorization = `Bearer ${token}`;
      return headers;
    }

    function saveAdminToken() {
      const nextToken = document.getElementById("adminToken").value.trim();
      if (nextToken) {
        try {
          assertByteStringHeaderValue("Authorization", `Bearer ${nextToken}`);
        } catch (err) {
          showToast(err.message, true);
          return;
        }
        adminToken = nextToken;
        localStorage.setItem("wechat-rss-lite-admin-token", adminToken);
        showToast("管理令牌已保存");
      } else {
        adminToken = "";
        localStorage.removeItem("wechat-rss-lite-admin-token");
        showToast("管理令牌已清除");
      }
    }

    async function requestJson(path, options) {
      try {
        const res = await fetch(path, { ...options, headers: authHeaders({ "content-type": "application/json", ...(options && options.headers ? options.headers : {}) }) });
        const text = await res.text();
        let data = null;
        try { data = JSON.parse(text); } catch {}
        if (!res.ok) throw new Error(data?.detail || data?.message || res.statusText || '请求失败');
        return { ok: true, data, text };
      } catch (err) {
        showToast(err.message, true);
        return { ok: false, data: null, text: err.message };
      }
    }

    async function requestForm(path, formData) {
      try {
        const res = await fetch(path, { method: "POST", headers: authHeaders(), body: formData });
        const text = await res.text();
        let data = null;
        try { data = JSON.parse(text); } catch {}
        if (!res.ok) throw new Error(data?.detail || res.statusText);
        return { ok: true, data, text };
      } catch (err) {
        showToast(err.message, true);
        return { ok: false, data: null, text: err.message };
      }
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[ch]));
    }

    function formatDate(value) {
      if (!value) return '';
      try { return new Date(value).toLocaleString(); } catch { return value; }
    }

    document.addEventListener("DOMContentLoaded", () => {
      if (adminToken) {
        try {
          assertByteStringHeaderValue("Authorization", `Bearer ${adminToken.trim()}`);
        } catch {
          adminToken = "";
          localStorage.removeItem("wechat-rss-lite-admin-token");
          showToast(ADMIN_TOKEN_ERROR, true);
        }
      }
      document.getElementById("adminToken").value = adminToken;
    });

    // Status & Health
    async function loadStatus() {
      const health = await requestJson("/health");
      if (health.ok) {
        document.getElementById("statusRaw").textContent = JSON.stringify(health.data, null, 2);
        renderStatus(health.data);
        renderRateLimit(health.data?.rate_limit);
      }
      await loadCategories();
      await loadSubscriptions();
      await loadBlacklist();
      await loadVerifications();
    }

    function renderStatus(data) {
      const credential = data?.credential;
      if (!credential || !credential.configured) {
        setStatus("warn", "未登录微信", credential?.stored ? "检测到演示/手工凭证，但微信凭证不可用。" : "未检测到微信登录凭证。");
        return;
      }
      if (credential.expired) {
        setStatus("error", "登录已过期", `账号 ${credential.account_name || "默认"} 凭证过期，请重新扫码。`);
        return;
      }
      const expiry = credential.expires_at ? `有效期至 ${new Date(credential.expires_at).toLocaleString()}` : "";
      setStatus("ok", "已登录", `账号 ${credential.account_name || "默认"} 正常在线。${expiry}`);
    }

    function setStatus(kind, title, detail) {
      const card = document.getElementById("statusCard");
      card.className = `status-card ${kind}`;
      document.getElementById("statusTitle").textContent = title;
      document.getElementById("statusDetails").textContent = detail;
    }

    // Login
    async function createLogin() {
      document.getElementById('loginDialog').showModal();
      document.getElementById('qrBox').innerHTML = '<span style="color:var(--text-muted)">正在创建登录会话...</span>';
      document.getElementById('loginHint').textContent = '';
      document.getElementById('loginConfirmUrl').style.display = 'none';
      document.getElementById('openConfirmButton').style.display = 'none';
      loginConfirmUrl = "";
      
      const res = await requestJson("/login/sessions", { method: "POST", body: "{}" });
      if (res.ok && res.data) {
        loginSession = res.data.id || "";
        renderLoginDialog(res.data);
      } else {
        document.getElementById('qrBox').textContent = "创建失败";
      }
    }

    function renderLoginDialog(session) {
      const qrBox = document.getElementById('qrBox');
      loginConfirmUrl = session.confirm_url || "";
      renderConfirmUrlHint(loginConfirmUrl);
      if (session.qrcode_url) {
        qrBox.innerHTML = `<img src="${session.qrcode_url}" alt="QR">`;
        document.getElementById('loginHint').textContent = session.message || "请使用微信扫描二维码。";
      } else {
        qrBox.innerHTML = '<span style="color:var(--text-muted)">未返回二维码</span>';
        document.getElementById('loginHint').textContent = session.message || "请检查提供器配置。";
      }
    }

    function renderConfirmUrlHint(url) {
      const urlNode = document.getElementById('loginConfirmUrl');
      const openButton = document.getElementById('openConfirmButton');
      if (!url) {
        urlNode.style.display = 'none';
        openButton.style.display = 'none';
        return;
      }
      const host = (() => {
        try { return new URL(url).hostname; } catch { return ""; }
      })();
      const localHost = ["127.0.0.1", "localhost", "::1"].includes(host);
      urlNode.textContent = localHost
        ? `当前二维码地址仅本机可打开：${url}`
        : url;
      urlNode.style.display = 'block';
      openButton.style.display = 'inline-flex';
    }

    function openConfirmPage() {
      if (!loginConfirmUrl) return;
      window.open(loginConfirmUrl, "_blank", "noopener,noreferrer");
    }

    async function refreshLoginSession() {
      if (!loginSession) return;
      document.getElementById('loginHint').textContent = "正在刷新二维码状态...";
      const res = await requestJson(`/login/sessions/${loginSession}`);
      if (res.ok && res.data) renderLoginDialog(res.data);
      else document.getElementById('loginHint').textContent = res.text || "刷新二维码状态失败。";
    }

    async function completeLogin() {
      if (loginCompleting) return;
      if (!loginSession) {
        document.getElementById('loginHint').textContent = "请先创建登录二维码。";
        return;
      }
      loginCompleting = true;
      const button = document.getElementById('completeLoginButton');
      const previousText = button.textContent;
      button.disabled = true;
      button.textContent = "正在确认...";
      document.getElementById('loginHint').textContent = "正在确认手机扫码状态，请稍候...";
      const res = await requestJson(`/login/sessions/${loginSession || "manual"}/complete`, { method: "POST", body: "{}" });
      if (res.ok) {
        document.getElementById('loginHint').textContent = "登录成功，正在刷新状态。";
        showToast("登录成功！");
        closeLoginDialog();
        loadStatus();
      } else {
        const status = await requestJson(`/login/sessions/${loginSession}`);
        if (status.ok && status.data) {
          renderLoginDialog(status.data);
          const state = status.data.status || "";
          const messageByState = {
            pending: "还没有检测到手机端扫码确认，请在微信里确认登录后再点击。",
            scanned: "已检测到扫码，请先在手机端确认登录，再点击完成。",
            expired: "登录二维码已过期，请关闭弹窗后重新扫码。",
            failed: "登录会话不可用，请关闭弹窗后重新扫码。",
            confirmed: "手机端已确认，请再次点击完成登录保存凭证。",
          };
          document.getElementById('loginHint').textContent = messageByState[state] || res.text || "登录尚未确认。";
        } else {
          document.getElementById('loginHint').textContent = res.text || "登录完成失败，请刷新二维码状态后重试。";
        }
      }
      button.disabled = false;
      button.textContent = previousText;
      loginCompleting = false;
    }

    function closeLoginDialog() {
      document.getElementById('loginDialog').close();
    }

    async function clearCredential() {
      if (!confirm('确定要清除当前的微信登录状态吗？')) return;
      const res = await requestJson("/credentials/default", { method: "DELETE" });
      if (res.ok) {
        showToast("登录状态已清除");
        loadStatus();
      }
    }

    async function validateCredential() {
      setStatus("warn", "正在验证", "请求微信验证凭证有效性...");
      const res = await requestJson("/credentials/default/validate", { method: "POST", body: "{}" });
      if (res.ok && res.data?.valid) {
        showToast("验证通过");
        loadStatus();
      } else {
        setStatus("error", "验证失败", res.data?.reason || res.text);
      }
    }

    // Rate Limit & Stats
    async function loadStats() {
      const res = await requestJson("/stats");
      if (res.ok) {
        document.getElementById("statsRaw").textContent = JSON.stringify(res.data, null, 2);
        renderRateLimit(res.data?.rate_limit);
        showToast("统计数据已刷新");
      }
    }

    async function saveRateLimit() {
      const payload = {
        per_minute: Number(document.getElementById('ratePerMinute').value || recommendedRateLimit.per_minute),
        min_interval_seconds: Number(document.getElementById('rateInterval').value || recommendedRateLimit.min_interval_seconds)
      };
      const res = await requestJson("/rate-limit", { method: "PUT", body: JSON.stringify(payload) });
      if (res.ok) {
        showToast("限频配置已保存");
        renderRateLimit(res.data);
      }
    }

    function applyRecommendedRateLimit() {
      document.getElementById('ratePerMinute').value = recommendedRateLimit.per_minute;
      document.getElementById('rateInterval').value = recommendedRateLimit.min_interval_seconds;
      saveRateLimit();
    }

    function renderRateLimit(config) {
      if (!config) return;
      document.getElementById('ratePerMinute').value = config.per_minute;
      document.getElementById('rateInterval').value = config.min_interval_seconds;
      const el = document.getElementById('rateLimitSummary');
      el.className = "status-card ok";
      el.innerHTML = `
        <div class="status-line"><span class="status-dot"></span><span>限流保护运行中</span></div>
        <div class="status-details">
          当前窗口请求：${config.requests_in_current_window} / ${config.per_minute} (剩余 ${config.remaining_in_current_window})<br>
          最小间隔 ${config.min_interval_seconds}s。累计拦截等待 ${config.total_waits} 次，总计 ${config.total_wait_seconds}s。
        </div>
      `;
    }

    // Search Accounts
    async function searchAccounts() {
      const q = document.getElementById('query').value;
      const resultsDiv = document.getElementById('accountResults');
      if (!q) {
        showToast("请输入搜索词", true);
        return;
      }
      resultsDiv.innerHTML = '<div class="empty-state">正在搜索中...</div>';
      const res = await requestJson(`/accounts/search?query=${encodeURIComponent(q)}`);
      
      if (res.ok) {
        const items = Array.isArray(res.data) ? res.data : [];
        if (!items.length) {
          resultsDiv.innerHTML = '<div class="empty-state">未找到相关公众号，可能是限流或关键字不对。</div>';
          return;
        }
        resultsDiv.innerHTML = '';
        items.forEach(item => {
          const isSub = subscribedIds.has(item.id);
          const div = document.createElement('div');
          div.className = 'item-card';
          div.style.flexDirection = 'row';
          div.style.alignItems = 'center';
          div.style.justifyContent = 'space-between';
          div.innerHTML = `
            <div class="result-body">
              <div class="avatar"><img src="${item.avatar_url||''}" onerror="this.style.display='none'"></div>
              <div class="item-info">
                <div class="item-title">${item.name || item.title || item.id}</div>
                <div class="item-meta">${item.id}</div>
              </div>
            </div>
            <button ${isSub ? 'disabled class="secondary"' : ''}>${isSub ? '已订阅' : '订阅'}</button>
          `;
          if (!isSub) {
            div.querySelector('button').onclick = () => subscribeAccount(item, div.querySelector('button'));
          }
          resultsDiv.appendChild(div);
        });
      }
    }

    async function subscribeAccount(item, btn) {
      btn.textContent = "添加中...";
      btn.disabled = true;
      const sub = {
        id: item.id,
        title: item.name || item.title || item.id,
        account_id: item.id,
        source_url: item.source_url || "",
        avatar_url: item.avatar_url || "",
        description: item.description || "",
        category_id: categoriesCache[0]?.id || null
      };
      const res = await requestJson("/subscriptions", { method: "POST", body: JSON.stringify(sub) });
      if (res.ok) {
        showToast("订阅成功！");
        btn.textContent = "已订阅";
        btn.className = "secondary";
        subscribedIds.add(item.id);
        loadSubscriptions();
      } else {
        btn.textContent = "订阅";
        btn.disabled = false;
      }
    }

    async function subscribe() {
      const id = document.getElementById('sid').value;
      if (!id) return showToast("请输入公众号 ID", true);
      const res = await requestJson("/subscriptions", { 
        method: "POST", 
        body: JSON.stringify({ id, title: document.getElementById('title').value || id, account_id: id }) 
      });
      if (res.ok) {
        showToast("手动添加订阅成功");
        document.getElementById('sid').value = '';
        document.getElementById('title').value = '';
        loadSubscriptions();
      }
    }

    // Subscriptions
    async function loadSubscriptions() {
      const res = await requestJson("/subscriptions");
      if (res.ok) {
        const items = Array.isArray(res.data) ? res.data : [];
        subscriptionsCache = items;
        subscribedIds = new Set(items.map(i => i.id));
        renderReaderSubscriptionOptions(items);
        renderSubscriptions(items);
        renderRssBuilder();
      }
    }

    function renderSubscriptions(items) {
      const list = document.getElementById('subscriptionList');
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">暂无订阅，请在上方搜索并添加。</div>';
        return;
      }
      items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'item-card';
        const feedUrl = item.feed_url || `/feeds/${item.id}.rss`;
        div.innerHTML = `
          <div class="item-top">
            <div class="result-body">
              <div class="avatar"><img src="${item.avatar_url||''}" onerror="this.style.display='none'"></div>
              <div class="item-info">
                <div class="item-title">${item.title || item.id}</div>
                <div class="item-meta">ID: ${item.account_id || item.id}</div>
              </div>
            </div>
            <button class="switch-btn ${item.enabled ? 'on' : ''}"></button>
          </div>
          <select class="category-select" style="margin: 8px 0; padding: 6px; font-size: 13px;"></select>
          <div class="row" style="gap: 8px; margin-top: auto;">
            <button class="icon-button secondary" title="复制 RSS" data-action="copy-feed"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button>
            <button class="icon-button secondary" title="轮询更新" onclick="pollSubscription('${item.id}')"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg></button>
            <button class="icon-button secondary" title="重新拉取文章" onclick="refreshSubscriptionArticles('${item.id}', this)"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M3 21v-5h5"></path><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path></svg></button>
            <button class="icon-button secondary" title="查看本地文章" onclick="openReaderForSubscription('${item.id}')"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"></path><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"></path></svg></button>
            <button class="icon-button danger" style="margin-left: auto;" title="取消订阅" onclick="deleteSubscription('${item.id}')"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg></button>
          </div>
        `;
        div.querySelector('[data-action="copy-feed"]').onclick = () => copyText(feedUrl);
        // Setup switch
        div.querySelector('.switch-btn').onclick = async function() {
          const isEn = this.classList.contains('on');
          const res = await requestJson(`/subscriptions/${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ enabled: !isEn }) });
          if (res.ok) {
            this.classList.toggle('on');
            showToast(`已${!isEn ? '启用' : '暂停'}订阅`);
          }
        };
        // Setup categories
        const sel = div.querySelector('select');
        sel.innerHTML = '<option value="">未分类</option>';
        categoriesCache.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c.id; opt.textContent = c.name;
          if (item.category_id === c.id) opt.selected = true;
          sel.appendChild(opt);
        });
        sel.onchange = async () => {
          await requestJson(`/subscriptions/${encodeURIComponent(item.id)}`, { method: "PATCH", body: JSON.stringify({ category_id: sel.value ? Number(sel.value) : null }) });
          showToast("分类已更新");
        };
        list.appendChild(div);
      });
    }

    async function pollAll() {
      showToast("开始后台轮询全部...");
      await requestJson("/poll", { method: "POST", body: "{}" });
      showToast("轮询请求已发送");
      loadSubscriptions();
    }

    async function pollSubscription(id) {
      showToast("正在轮询更新...");
      const res = await requestJson(`/subscriptions/${encodeURIComponent(id)}/poll`, { method: "POST", body: "{}" });
      if (res.ok) showToast("轮询完成");
    }

    async function refreshAllDownloadedArticles(button) {
      if (!confirm("确定要重新拉取所有已下载文章吗？这会覆盖本地已保存正文。")) return;
      await runRefreshRequest("/articles/refresh", button, "全部文章重新拉取完成");
    }

    async function refreshSubscriptionArticles(id, button) {
      if (!confirm("确定要重新拉取这个公众号已下载的文章吗？")) return;
      await runRefreshRequest(`/subscriptions/${encodeURIComponent(id)}/articles/refresh`, button, "公众号文章重新拉取完成");
    }

    async function runRefreshRequest(path, button, successPrefix) {
      const originalText = button ? button.textContent : "";
      if (button) {
        button.disabled = true;
        if (originalText.trim()) button.textContent = "拉取中...";
      }
      showToast("正在重新拉取文章...");
      const res = await requestJson(path, { method: "POST", body: "{}" });
      if (button) {
        button.disabled = false;
        if (originalText.trim()) button.textContent = originalText;
      }
      if (!res.ok) return;
      const refreshed = res.data?.refreshed ?? 0;
      const failed = res.data?.failed ?? 0;
      const batchLimit = res.data?.batch_limit;
      const firstError = res.data?.errors?.[0]?.error;
      const detail = failed && firstError ? `，原因：${firstError}` : "";
      const limitHint = batchLimit && refreshed >= batchLimit ? `（本批上限 ${batchLimit} 篇，可再次执行）` : "";
      showToast(`${successPrefix}: 成功 ${refreshed} 篇，失败 ${failed} 篇${detail}${limitHint}`, failed > 0);
      if (document.getElementById('sec-reader').classList.contains('active')) {
        loadDownloadedArticles();
      }
    }

    async function deleteSubscription(id) {
      if (!confirm("确定要删除这个订阅吗？")) return;
      const res = await requestJson(`/subscriptions/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (res.ok) {
        showToast("已删除订阅");
        loadSubscriptions();
      }
    }

    function copyAllFeed() {
      copyText(`${location.origin}/feeds/all.rss`);
    }

    function exportSubscriptions(format) {
      const normalized = format === "csv" ? "csv" : "opml";
      const link = document.createElement("a");
      link.href = `/subscriptions/export?format=${normalized}`;
      link.download = `wechat_rss_subscriptions.${normalized}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast(`正在导出 ${normalized.toUpperCase()} 文件`);
    }

    async function copyText(txt) {
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(txt);
        } else {
          fallbackCopyText(txt);
        }
      } catch {
        fallbackCopyText(txt);
      }
      showToast("链接已复制到剪贴板");
    }

    function fallbackCopyText(txt) {
      const input = document.createElement("textarea");
      input.value = txt;
      input.setAttribute("readonly", "");
      input.style.position = "fixed";
      input.style.left = "-9999px";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    }

    // RSS Builder
    function currentRssSelection() {
      return rssBuilderMode === "categories" ? selectedRssCategories : selectedRssSubscriptions;
    }

    function setRssBuilderMode(mode) {
      rssBuilderMode = mode === "categories" ? "categories" : "subscriptions";
      document.getElementById("rssModeSubscriptions").classList.toggle("active", rssBuilderMode === "subscriptions");
      document.getElementById("rssModeCategories").classList.toggle("active", rssBuilderMode === "categories");
      renderRssBuilder();
    }

    function rssItemUrl(item) {
      if (rssBuilderMode === "categories") return `${location.origin}/feeds/categories/${encodeURIComponent(item.id)}.rss`;
      return `${location.origin}/feeds/${encodeURIComponent(item.id)}.rss`;
    }

    function rssItemSearchText(item) {
      if (rssBuilderMode === "categories") {
        return [item.name, item.description, item.id].filter(Boolean).join(" ").toLowerCase();
      }
      return [item.title, item.id, item.account_id, item.description].filter(Boolean).join(" ").toLowerCase();
    }

    function filteredRssItems() {
      const q = (document.getElementById("rssSearch")?.value || "").trim().toLowerCase();
      const items = rssBuilderMode === "categories" ? categoriesCache : subscriptionsCache;
      if (!q) return items;
      return items.filter(item => rssItemSearchText(item).includes(q));
    }

    function renderRssBuilder() {
      const list = document.getElementById("rssBuilderList");
      if (!list) return;
      const modeLabel = rssBuilderMode === "categories" ? "分类" : "公众号";
      const items = filteredRssItems();
      const selected = currentRssSelection();
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = `<div class="empty-state">没有匹配的${modeLabel}。</div>`;
        updateGeneratedRssLinks();
        return;
      }
      items.forEach(item => {
        const id = String(item.id);
        const title = rssBuilderMode === "categories" ? item.name : (item.title || item.id);
        const meta = rssBuilderMode === "categories"
          ? `${item.subscription_count || 0} 个订阅`
          : `ID: ${item.account_id || item.id}`;
        const row = document.createElement("label");
        row.className = "rss-select-row";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = selected.has(id);
        checkbox.onchange = () => {
          if (checkbox.checked) selected.add(id);
          else selected.delete(id);
          updateGeneratedRssLinks();
        };
        const info = document.createElement("div");
        info.className = "item-info";
        info.innerHTML = `
          <div class="item-title">${escapeHtml(title)}</div>
          <div class="item-meta">${escapeHtml(meta)}</div>
          ${item.description ? `<div class="item-desc">${escapeHtml(item.description)}</div>` : ""}
        `;
        const pill = document.createElement("span");
        pill.className = "pill";
        pill.textContent = rssBuilderMode === "categories" ? "分类 RSS" : "公众号 RSS";
        row.appendChild(checkbox);
        row.appendChild(info);
        row.appendChild(pill);
        list.appendChild(row);
      });
      updateGeneratedRssLinks();
    }

    function selectedRssItems() {
      const selected = currentRssSelection();
      const items = rssBuilderMode === "categories" ? categoriesCache : subscriptionsCache;
      return items.filter(item => selected.has(String(item.id)));
    }

    function updateGeneratedRssLinks() {
      const output = document.getElementById("generatedRssLinks");
      const summary = document.getElementById("rssSelectionSummary");
      if (!output || !summary) return;
      const selected = selectedRssItems();
      output.value = selected.map(item => {
        const title = rssBuilderMode === "categories" ? item.name : (item.title || item.id);
        return `${title}\\n${rssItemUrl(item)}`;
      }).join("\\n\\n");
      const modeLabel = rssBuilderMode === "categories" ? "分类" : "公众号";
      summary.textContent = `已选择 ${selected.length} 个${modeLabel}，当前筛选结果 ${filteredRssItems().length} 项。`;
    }

    function selectVisibleRssItems() {
      const selected = currentRssSelection();
      filteredRssItems().forEach(item => selected.add(String(item.id)));
      renderRssBuilder();
    }

    function invertVisibleRssItems() {
      const selected = currentRssSelection();
      filteredRssItems().forEach(item => {
        const id = String(item.id);
        if (selected.has(id)) selected.delete(id);
        else selected.add(id);
      });
      renderRssBuilder();
    }

    function clearRssSelection() {
      currentRssSelection().clear();
      renderRssBuilder();
    }

    function copyGeneratedRssLinks() {
      const value = document.getElementById("generatedRssLinks").value.trim();
      if (!value) return showToast("请先选择要生成的 RSS 链接", true);
      copyText(value);
    }

    // Downloaded Article Reader
    function renderReaderSubscriptionOptions(items) {
      const select = document.getElementById('readerSubscription');
      if (!select) return;
      const current = select.value;
      select.innerHTML = '<option value="">全部订阅</option>';
      items.forEach(item => {
        const option = document.createElement('option');
        option.value = item.id;
        option.textContent = item.title || item.id;
        select.appendChild(option);
      });
      select.value = [...select.options].some(option => option.value === current) ? current : "";
    }

    function openReaderForSubscription(id) {
      document.getElementById('readerSubscription').value = id;
      switchTab('reader');
    }

    async function loadDownloadedArticles() {
      const list = document.getElementById('downloadedArticleList');
      if (!list) return;
      const subscriptionId = document.getElementById('readerSubscription').value;
      const source = document.getElementById('readerSource').value;
      const limit = Math.min(500, Math.max(1, Number(document.getElementById('readerLimit').value || 100)));
      const params = new URLSearchParams({ limit: String(limit), status: "fetched" });
      if (subscriptionId) params.set("subscription_id", subscriptionId);
      if (source) params.set("source", source);
      list.innerHTML = '<div class="empty-state">正在加载已下载文章...</div>';
      const res = await requestJson(`/articles?${params.toString()}`);
      if (!res.ok) return;
      downloadedArticles = Array.isArray(res.data) ? res.data : [];
      renderDownloadedArticleList(downloadedArticles);
      if (downloadedArticles.length) {
        openDownloadedArticle(downloadedArticles[0].url);
      } else {
        clearReader("没有找到已下载文章。可以先轮询订阅或下载历史文章。");
      }
    }

    function renderDownloadedArticleList(items) {
      const list = document.getElementById('downloadedArticleList');
      list.innerHTML = '';
      if (!items.length) {
        list.innerHTML = '<div class="empty-state">暂无已下载文章。</div>';
        return;
      }
      items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'reader-list-item';
        div.dataset.url = item.url;
        div.innerHTML = `
          <div class="reader-title">${escapeHtml(item.title || item.url)}</div>
          <div class="item-meta">${escapeHtml(item.account_name || item.author || '未知来源')} · ${escapeHtml(formatDate(item.published_at) || item.source || '')}</div>
          ${item.summary ? `<div class="item-desc">${escapeHtml(item.summary)}</div>` : ''}
        `;
        div.onclick = () => openDownloadedArticle(item.url);
        list.appendChild(div);
      });
    }

    async function openDownloadedArticle(url) {
      document.querySelectorAll('.reader-list-item').forEach(el => {
        el.classList.toggle('active', el.dataset.url === url);
      });
      currentReaderArticleUrl = url;
      const res = await requestJson(`/articles/read?url=${encodeURIComponent(url)}`);
      if (!res.ok || !res.data) return;
      renderArticleReader(res.data);
    }

    function clearReader(message) {
      currentReaderArticleUrl = "";
      const frame = document.getElementById('articleReaderFrame');
      frame.removeAttribute('src');
      frame.removeAttribute('srcdoc');
      frame.style.display = 'none';
      document.getElementById('readerArticleActions').style.display = 'none';
      const placeholder = document.getElementById('readerPlaceholder');
      placeholder.style.display = 'grid';
      placeholder.textContent = message;
    }

    function readerHtmlUrl(articleUrl) {
      const params = new URLSearchParams({ url: articleUrl });
      const token = adminToken.trim();
      if (token) params.set("token", token);
      return `/articles/read/html?${params.toString()}`;
    }

    function renderArticleReader(article) {
      const frame = document.getElementById('articleReaderFrame');
      const placeholder = document.getElementById('readerPlaceholder');
      const actions = document.getElementById('readerArticleActions');
      if (!article?.url) return;
      frame.removeAttribute('srcdoc');
      frame.src = readerHtmlUrl(article.url);
      placeholder.style.display = 'none';
      actions.style.display = 'flex';
      frame.style.display = 'block';
    }

    async function refreshCurrentReaderArticle(button) {
      if (!currentReaderArticleUrl) return showToast("请先选择一篇文章", true);
      await refreshSingleArticle(currentReaderArticleUrl, button, true);
    }

    async function refreshSingleArticle(url, button, reopen) {
      const originalText = button ? button.textContent : "";
      if (button) {
        button.disabled = true;
        if (originalText.trim()) button.textContent = "拉取中...";
      }
      showToast("正在重新拉取这篇文章...");
      const res = await requestJson(`/articles/refresh?url=${encodeURIComponent(url)}`, { method: "POST", body: "{}" });
      if (button) {
        button.disabled = false;
        if (originalText.trim()) button.textContent = originalText;
      }
      if (!res.ok) return;
      const failed = res.data?.failed ?? 0;
      const firstError = res.data?.errors?.[0]?.error;
      showToast(
        failed ? (firstError ? `重新拉取失败：${firstError}` : "重新拉取失败") : "文章已重新拉取",
        failed > 0
      );
      if (!failed && reopen) {
        await openDownloadedArticle(url);
      }
    }

    // Local Articles
    async function loadLocalArticles(id, title) {
      const card = document.getElementById('localArticlesCard');
      const list = document.getElementById('articleList');
      document.getElementById('localArticlesTitle').textContent = `本地文章: ${title || id}`;
      card.style.display = 'block';
      list.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">加载中...</div>';
      
      const res = await requestJson(`/subscriptions/${encodeURIComponent(id)}/articles?limit=50`);
      if (res.ok) {
        const items = Array.isArray(res.data) ? res.data : [];
        if (!items.length) {
          list.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">暂无本地缓存文章，可能是还没有抓取到。</div>';
          return;
        }
        list.innerHTML = '';
        items.forEach(item => {
          const div = document.createElement('div');
          div.className = 'item-card';
          div.innerHTML = `
            <div class="item-title"><a href="${item.url}" target="_blank" style="color:inherit;text-decoration:none;">${item.title || item.url}</a></div>
            <div class="item-meta">${item.published_at || ''} · ${item.content_type || 'article'}</div>
            <div class="row" style="gap: 8px;">
              <button class="secondary" onclick="refreshSingleArticle('${item.url}', this, false)">重新拉取</button>
              <button onclick="openDownloadedArticle('${item.url}'); switchTab('reader')">阅读</button>
            </div>
          `;
          list.appendChild(div);
        });
      }
      // scroll to it
      card.scrollIntoView({ behavior: 'smooth' });
    }

    function closeLocalArticles() {
      document.getElementById('localArticlesCard').style.display = 'none';
    }

    // Categories
    async function loadCategories() {
      const res = await requestJson("/categories");
      if (res.ok) {
        categoriesCache = Array.isArray(res.data) ? res.data : [];
        renderCategories(categoriesCache);
        renderRssBuilder();
      }
    }

    async function createCategory() {
      const name = document.getElementById('categoryName').value;
      if (!name) return showToast("分类名称不能为空", true);
      const res = await requestJson("/categories", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: document.getElementById('categoryDescription').value,
          color: document.getElementById('categoryColor').value || "blue"
        })
      });
      if (res.ok) {
        showToast("分类创建成功");
        document.getElementById('categoryName').value = '';
        document.getElementById('categoryDescription').value = '';
        loadCategories();
      }
    }

    function renderCategories(items) {
      const list = document.getElementById('categoryList');
      list.innerHTML = "";
      if (!items.length) {
        list.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">暂无分类。</div>';
        return;
      }
      items.forEach(item => {
        const div = document.createElement('div');
        div.className = 'item-card';
        div.innerHTML = `
          <div class="item-top">
            <div class="item-info">
              <div class="item-title">${item.name}</div>
              <div class="item-meta">${item.description || "无描述"}</div>
            </div>
            <span class="pill">${item.subscription_count || 0} 订阅</span>
          </div>
          <div class="row" style="margin-top: auto; padding-top: 12px; gap: 8px;">
            <button class="secondary" style="flex:1; font-size: 13px; padding: 6px;" onclick="copyText('${location.origin}/feeds/categories/${item.id}.rss')">复制 RSS</button>
            <button class="danger" style="flex:1; font-size: 13px; padding: 6px;" onclick="deleteCategory(${item.id})">删除</button>
          </div>
        `;
        list.appendChild(div);
      });
    }

    async function deleteCategory(id) {
      if (!confirm("确定要删除此分类吗？")) return;
      const res = await requestJson(`/categories/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (res.ok) {
        showToast("分类已删除");
        loadCategories();
        loadSubscriptions();
      }
    }

    // Import
    async function importSubscriptions() {
      const txt = document.getElementById('bulkText').value;
      const file = document.getElementById('bulkFile').files[0];
      if (!txt && !file) return showToast("请粘贴文本或选择文件", true);
      
      const form = new FormData();
      form.append("text", txt || "");
      if (file) form.append("file", file);
      
      const pre = document.getElementById('importResult');
      pre.style.display = 'block';
      pre.textContent = "导入中...";
      
      const res = await requestForm("/subscriptions/import", form);
      if (res.ok) {
        showToast("导入完成");
        pre.textContent = JSON.stringify(res.data, null, 2);
        loadSubscriptions();
      } else {
        pre.textContent = "导入失败: " + res.text;
      }
    }

    // Blacklist
    async function loadBlacklist() {
      const res = await requestJson("/blacklist");
      if (res.ok) {
        const items = Array.isArray(res.data) ? res.data : [];
        const list = document.getElementById('blacklistList');
        list.innerHTML = "";
        if (!items.length) {
          list.innerHTML = '<div class="empty-state" style="grid-column: 1/-1;">黑名单为空。</div>';
          return;
        }
        items.forEach(item => {
          const div = document.createElement('div');
          div.className = 'item-card';
          div.innerHTML = `
            <div class="item-top">
              <div class="item-info">
                <div class="item-title">${item.account_id}</div>
                <div class="item-meta">原因：${item.reason || '-'}</div>
              </div>
            </div>
            <button class="secondary" style="margin-top:auto;" onclick="removeBlacklist('${item.account_id}')">移出黑名单</button>
          `;
          list.appendChild(div);
        });
      }
    }

    async function addBlacklist() {
      const id = document.getElementById('blacklistId').value;
      if (!id) return showToast("请输入公众号 ID", true);
      const res = await requestJson("/blacklist", {
        method: "POST",
        body: JSON.stringify({ account_id: id, reason: document.getElementById('blacklistReason').value })
      });
      if (res.ok) {
        showToast("已加入黑名单");
        document.getElementById('blacklistId').value = '';
        document.getElementById('blacklistReason').value = '';
        loadBlacklist();
      }
    }

    async function removeBlacklist(id) {
      const res = await requestJson(`/blacklist/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (res.ok) {
        showToast("已移出黑名单");
        loadBlacklist();
      }
    }

    // Verifications
    async function loadVerifications() {
      const el = document.getElementById('verificationsCard');
      if (!el) return;
      const res = await requestJson("/verifications?status=pending");
      if (res.ok && Array.isArray(res.data) && res.data.length > 0) {
        el.style.display = 'block';
        const list = document.getElementById('verificationList');
        list.innerHTML = '';
        res.data.forEach(item => {
          const div = document.createElement('div');
          div.className = 'item-card';
          div.style.background = '#FFFBEB';
          div.innerHTML = `
            <div class="item-top">
              <div class="item-info">
                <div class="item-title" style="color: #B45309;">⚠️ ${item.message || item.kind + ' 验证'}</div>
                <div class="item-meta">目标: ${item.target || item.id}</div>
              </div>
            </div>
            <div class="row" style="margin-top:12px;">
              ${item.verify_url ? `<button onclick="window.open('${item.verify_url}', '_blank')">打开验证页面</button>` : ''}
              <button class="secondary" onclick="resolveVerification('${item.id}')">标记为已处理</button>
            </div>
          `;
          list.appendChild(div);
        });
        document.getElementById('verifications').textContent = JSON.stringify(res.data, null, 2);
      } else {
        el.style.display = 'none';
      }
    }

    async function resolveVerification(id) {
      await requestJson(`/verifications/${encodeURIComponent(id)}/resolve`, { method: "POST", body: "{}" });
      showToast("已标记处理");
      loadVerifications();
    }

    // Init
    loadStatus();
