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
    input { padding: 10px 12px; border: 1px solid #c9c9c1; border-radius: 6px; font: inherit; }
    button { padding: 9px 12px; border: 1px solid #1f2933; border-radius: 6px; background: #1f2933; color: white; cursor: pointer; }
    button.secondary { background: white; color: #1f2933; }
    pre { overflow: auto; background: #f2f2ed; padding: 12px; border-radius: 6px; min-height: 48px; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; }
  </style>
</head>
<body>
  <header><h1>wechat-rss-lite</h1></header>
  <main>
    <section>
      <h2>状态</h2>
      <button onclick="loadStatus()">刷新</button>
      <pre id="status"></pre>
    </section>
    <section>
      <h2>扫码登录</h2>
      <div class="row">
        <button onclick="createLogin()">创建会话</button>
        <button class="secondary" onclick="completeLogin()">完成登录</button>
      </div>
      <pre id="login"></pre>
    </section>
    <section>
      <h2>公众号搜索</h2>
      <label>关键词 <input id="query" placeholder="公众号名称"></label>
      <button onclick="searchAccounts()">搜索</button>
      <pre id="accounts"></pre>
    </section>
    <section>
      <h2>订阅</h2>
      <label>订阅 ID <input id="sid" placeholder="account-id"></label>
      <label>标题 <input id="title" placeholder="公众号名称"></label>
      <button onclick="subscribe()">添加订阅</button>
      <button class="secondary" onclick="pollAll()">轮询全部</button>
      <pre id="subs"></pre>
    </section>
  </main>
  <script>
    let loginSession = "";
    async function api(path, options) {
      const res = await fetch(path, { headers: { "content-type": "application/json" }, ...options });
      const text = await res.text();
      try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
    }
    async function loadStatus() { status.textContent = await api("/health"); subs.textContent = await api("/subscriptions"); }
    async function createLogin() {
      const value = await api("/login/sessions", { method: "POST", body: "{}" });
      login.textContent = value;
      try { loginSession = JSON.parse(value).id || ""; } catch {}
    }
    async function completeLogin() {
      login.textContent = await api(`/login/sessions/${loginSession || "manual"}/complete`, { method: "POST", body: "{}" });
    }
    async function searchAccounts() { accounts.textContent = await api(`/accounts/search?query=${encodeURIComponent(query.value)}`); }
    async function subscribe() {
      subs.textContent = await api("/subscriptions", { method: "POST", body: JSON.stringify({ id: sid.value, title: title.value, account_id: sid.value }) });
    }
    async function pollAll() { subs.textContent = await api("/poll", { method: "POST", body: "{}" }); }
    loadStatus();
  </script>
</body>
</html>
"""

