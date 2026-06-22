/* Admin dashboard — job ops, analytics, user mgmt, cost watch.
 * Clerk-gated (server enforces require_admin); this UI just renders /admin/*.
 * Reuses clerk-auth.js for the bearer token. No chart lib — CSS bars. */
(function () {
  const el = document.getElementById("app");

  async function api(path) {
    const token = window.__authToken ? await window.__authToken() : null;
    const headers = {};
    if (token) headers["Authorization"] = "Bearer " + token;
    const res = await fetch(path, { headers });
    if (res.status === 401) throw new Error("unauthenticated");
    if (res.status === 403) throw new Error("forbidden");
    if (!res.ok) throw new Error(res.status + " " + res.statusText);
    return res.json();
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  const short = (id) => esc(String(id).slice(0, 8));

  function costCards(cost, analytics) {
    const used = cost.minutes_used, budget = cost.minute_budget;
    const pct = budget ? Math.min(100, Math.round((used / budget) * 100)) : 0;
    const near = pct >= 80;
    return `
      <div class="cards">
        <div class="card"><div class="n ${near ? "warn" : ""}">${used}/${budget}</div>
          <div class="l">runner-min this month${near ? " ⚠" : ""}</div>
          <div class="bar"><i style="width:${pct}%"></i></div></div>
        <div class="card"><div class="n">${cost.active_jobs}/${cost.global_concurrency_cap}</div>
          <div class="l">active jobs</div></div>
        <div class="card"><div class="n">${analytics.total}</div>
          <div class="l">total jobs</div></div>
        <div class="card"><div class="n">${analytics.by_status.done || 0}</div>
          <div class="l">completed</div></div>
        <div class="card"><div class="n">${analytics.by_status.failed || 0}</div>
          <div class="l">failed</div></div>
      </div>`;
  }

  function statusBreakdown(by) {
    const total = Object.values(by).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(by).map(([s, n]) =>
      `<div class="l">${esc(s)} — ${n}</div>
       <div class="bar"><i style="width:${Math.round((n / total) * 100)}%"></i></div>`).join("");
  }

  function jobsTable(jobs) {
    const rows = jobs.map((j) => `
      <tr><td>${short(j.id)}</td>
          <td><span class="pill ${esc(j.status)}">${esc(j.status)}</span></td>
          <td>${esc(j.owner_user_id)}</td>
          <td>${esc((j.topic || "").slice(0, 60))}</td>
          <td class="muted">${esc(j.created_at)}</td></tr>`).join("");
    return `<h2>Jobs</h2><div class="wrap"><table>
      <tr><th>id</th><th>status</th><th>owner</th><th>topic</th><th>created</th></tr>
      ${rows || '<tr><td colspan="5" class="muted">none</td></tr>'}</table></div>`;
  }

  function usersTable(users) {
    const rows = users.map((u) => `
      <tr><td>${esc(u.clerk_id)}</td><td>${esc(u.email)}</td>
          <td><span class="pill">${esc(u.role)}</span></td>
          <td>${u.job_count}</td><td>${u.month_minutes}</td>
          <td>${u.banned ? "yes" : ""}</td></tr>`).join("");
    return `<h2>Users</h2><div class="wrap"><table>
      <tr><th>clerk id</th><th>email</th><th>role</th><th>jobs</th><th>min/mo</th><th>banned</th></tr>
      ${rows || '<tr><td colspan="6" class="muted">none</td></tr>'}</table></div>`;
  }

  async function render() {
    let cost, analytics, users, jobs;
    try {
      [cost, analytics, users, jobs] = await Promise.all([
        api("/admin/cost"), api("/admin/analytics"), api("/admin/users"), api("/admin/jobs"),
      ]);
    } catch (e) {
      el.innerHTML = e.message === "forbidden"
        ? "<h1>Not authorized</h1><p class='muted'>Admin access required.</p>"
        : "<h1>Sign-in required</h1><p class='muted'>Authenticate to view the admin console.</p>";
      return;
    }
    el.innerHTML =
      `<h1>Admin console</h1><p class="muted">month ${esc(cost.month)} · refreshes every 10s</p>` +
      costCards(cost, analytics) +
      `<h2>Status breakdown</h2>${statusBreakdown(analytics.by_status)}` +
      jobsTable(jobs) + usersTable(users);
  }

  (async () => {
    await (window.__authReady || Promise.resolve());
    render();
    setInterval(render, 10000);
  })();
})();
