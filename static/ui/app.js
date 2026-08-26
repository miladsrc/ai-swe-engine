/* SASE Governance Dashboard — client layer over the governance engine.
   Backend is the source of truth; the UI owns no state or rights.
   Human actions go ONLY through the gated endpoints (Bearer authoritative).
   X-Acting-As is NEVER sent by this UI. */
"use strict";

const API = location.origin;
const TOKEN_KEY = "sase_token";
const POLL_MS = 15000;

let ME = null;          // {username, actor_id}
let pollTimer = null;

// ------------------------------------------------------------- api helper
async function api(method, path, body) {
  const headers = {"Content-Type": "application/json"};
  const t = sessionStorage.getItem(TOKEN_KEY);
  if (t) headers["Authorization"] = "Bearer " + t;
  const r = await fetch(API + path, {
    method, headers, body: body ? JSON.stringify(body) : undefined});
  if (r.status === 401 && path !== "/auth/login") { logout(); throw new Error("401"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((data.detail || ("HTTP " + r.status)));
  return data;
}

function esc(s) { return String(s ?? "").replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function fmt(ts) { return ts ? new Date(ts).toLocaleString() : "—"; }
function badge(status) {
  const map = {running:"b-running", completed:"b-ok", passed:"b-ok", approved:"b-ok",
    failed:"b-failed", rejected:"b-failed", blocked:"b-warn", pending:"b-pending",
    needs_revision:"b-warn", ready_for_human_review:"b-awaiting",
    open:"b-awaiting", blocking:"b-awaiting"};
  return `<span class="badge ${map[status] || "b-info"}">${esc(status || "?")}</span>`;
}
function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg; el.classList.remove("hidden");
  setTimeout(() => el.classList.remove("show"), 10);
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.add("hidden"), 3500);
}

// ------------------------------------------------------------------- auth
async function login(e) {
  e.preventDefault();
  const err = document.getElementById("login-error");
  const btn = e.target.querySelector("button[type=submit]");
  err.classList.add("hidden");
  btn.disabled = true; btn.textContent = "Signing in…";   // loading state
  try {
    const r = await fetch(API + "/auth/login", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({username: document.getElementById("login-user").value.trim(),
                            password: document.getElementById("login-pass").value})});
    if (!r.ok) throw new Error((await r.json()).detail || "Login failed");
    sessionStorage.setItem(TOKEN_KEY, (await r.json()).token);
    if (location.pathname.endsWith("/ui/login")) {
      location.replace("/ui/dashboard");                   // entry-point flow
      return;
    }
    await enterApp();
  } catch (ex) { err.textContent = ex.message; err.classList.remove("hidden"); }
  finally { btn.disabled = false; btn.textContent = "Sign in"; }
}

function logout() {
  sessionStorage.removeItem(TOKEN_KEY); ME = null;
  clearInterval(pollTimer);
  location.replace("/ui/login");                           // back to login page
}

function showLogin() {
  document.getElementById("app-view").classList.add("hidden");
  document.getElementById("login-view").classList.remove("hidden");
}

async function enterApp() {
  ME = await api("GET", "/auth/me");
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("app-view").classList.remove("hidden");
  const role = (ME.actor_id || "").split(":")[0] || "human";
  document.getElementById("whoami").innerHTML =
    `${esc(ME.username)}<small>role: ${esc(role)} · ${esc(ME.actor_id)}</small>`;
  buildNav();
  route();
  clearInterval(pollTimer);
  pollTimer = setInterval(() => { if (["dashboard","approvals"].includes(currentView)) route(); }, POLL_MS);
}

// ---------------------------------------------------------------- routing
const NAV = [["dashboard","Dashboard"],["approvals","Pending Approvals"],
  ["runs","Agent Runs"],["projects","Projects"],["evidence","Evidence"],
  ["audit","Audit Logs"],["console","Agent Console"],["validation","SoD Validation"],
  ["settings","Settings"]];
let currentView = "";

function buildNav() {
  document.getElementById("nav").innerHTML = NAV.map(([id, label]) =>
    `<a class="nav-item" data-v="${id}" onclick="go('${id}')">${label}</a>`).join("");
}
function go(v) { location.hash = "#/" + v; }
window.addEventListener("hashchange", route);

async function route() {
  if (!ME) return;
  const view = (location.hash.replace(/^#\//, "") || "dashboard").split("/")[0];
  currentView = view;
  document.querySelectorAll(".nav-item").forEach(a =>
    a.classList.toggle("active", a.dataset.v === view));
  const el = document.getElementById("view");
  try {
    if (view === "dashboard") await viewDashboard(el);
    else if (view === "approvals") await viewApprovals(el);
    else if (view === "runs") await viewRuns(el);
    else if (view === "projects") await viewProjects(el);
    else if (view === "evidence") await viewEvidence(el);
    else if (view === "audit") await viewAudit(el);
    else if (view === "console") await viewConsole(el);
    else if (view === "validation") await viewValidation(el);
    else if (view === "settings") viewSettings(el);
    else viewDashboard(el);
  } catch (ex) { el.innerHTML = `<div class="card"><h3>Error</h3><p>${esc(ex.message)}</p></div>`; }
}

// --------------------------------------------------------------- views
async function viewDashboard(el) {
  const o = await api("GET", "/dashboard/overview");
  const audit = await api("GET", "/dashboard/audit?limit=8");
  const p = o.pending, r = o.agent_runs;
  el.innerHTML = `
    <h1 class="page">Welcome, <span class="gold">${esc(ME.username)}</span></h1>
    <p class="sub">Acting identity for every approval: <b>${esc(ME.actor_id)}</b></p>
    <div class="grid c3">
      <div class="stat"><div class="n gold">${p.mrps_awaiting_human}</div><div class="l">MRP approvals</div></div>
      <div class="stat"><div class="n gold">${p.open_crps}</div><div class="l">Open CRPs</div></div>
      <div class="stat"><div class="n gold">${p.unvalidated_specs}</div><div class="l">Spec validations</div></div>
      <div class="stat"><div class="n">${r.running}</div><div class="l">Runs active</div></div>
      <div class="stat"><div class="n" style="color:var(--ok)">${r.completed}</div><div class="l">Completed</div></div>
      <div class="stat"><div class="n" style="color:var(--danger)">${r.failed}</div><div class="l">Failed</div></div>
    </div>
    <div class="section-title">Recent activity</div>
    <table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Artifact</th><th>Result</th></tr></thead>
    <tbody>${audit.map(a => `<tr><td>${fmt(a.timestamp)}</td><td class="mono">${esc(a.actor_id)}</td>
      <td>${esc(a.action)}</td><td class="mono">${esc(a.artifact_id || "")}</td>
      <td>${esc(a.result || a.human_decision || "")}</td></tr>`).join("")}</tbody></table>`;
}

async function viewApprovals(el) {
  const d = await api("GET", "/dashboard/approvals");
  const rows = [
    ...d.spec_validations.map(s => ({...s, title: "Validate spec", badge: "pending"})),
    ...d.crps.map(c => ({...c, title: c.title, badge: c.severity})),
    ...d.mrps.map(m => ({...m, title: m.change_summary || m.id, badge: "awaiting"})),
  ];
  el.innerHTML = `
    <h1 class="page">Approval Center</h1>
    <p class="sub">Decisions are recorded under your account (${esc(ME.actor_id)}) — permanently.</p>
    <table><thead><tr><th>Type</th><th>ID</th><th>Title</th><th>Status</th><th>Since</th><th></th></tr></thead>
    <tbody>${rows.map(x => `<tr>
      <td>${x.kind.replace("_", " ")}</td><td class="mono">${esc(x.id)}</td>
      <td>${esc(String(x.title).slice(0, 70))}</td><td>${badge(x.status || x.badge)}</td>
      <td>${fmt(x.created_at)}</td>
      <td><button class="btn btn-primary btn-sm" onclick="openDecision('${x.kind}','${esc(x.id)}')">Review</button></td>
    </tr>`).join("") || "<tr><td colspan=6>Nothing waiting. 🎉</td></tr>"}</tbody></table>`;
}

window.openDecision = async function(kind, id) {
  let detail = "";
  if (kind === "SPEC_VALIDATION") {
    const s = await api("GET", "/specs/" + id);
    detail = `<div class="card"><h3>What is happening?</h3>
      <p>The Specification Agent produced spec <b class="mono">${esc(id)}</b>. Per §3.5 no code may be
      generated until a human validates this spec. After validation, coder agents may implement it.</p>
      <div class="kv" style="margin-top:12px">
        <div class="k">Project</div><div class="mono">${esc(s.project_id)}</div>
        <div class="k">Format</div><div>${esc(s.format)}</div>
        <div class="k">Body</div><pre class="mono">${esc((s.body_ref || "").slice(0, 2000))}</pre></div></div>`;
    detail += decisionBox(kind, id, "/specs/" + id + "/validate", "{}");
  } else if (kind === "CRP") {
    const c = await api("GET", "/crps/" + id);
    detail = `<div class="card"><h3>What is happening?</h3>
      <p>A Change Request was raised by agent run <b class="mono">${esc(c.agent_run_id || "?")}</b>.
      Approval is needed because its severity (<b>${esc(c.severity)}</b>) blocks merge until resolved
      by a human VCR decision (§3.6.3).</p>
      <div class="kv" style="margin-top:12px">
        <div class="k">Blocking issue</div><div>${esc(c.blocking_issue_title)}
        <br><small>${esc(c.blocking_issue_body)}</small></div>
        <div class="k">Required decision</div><div>${esc(c.required_decision)}</div>
        <div class="k">Required role</div><div>${esc(c.required_role)}</div>
        <div class="k">Status</div><div>${badge(c.status)}</div></div></div>`;
    detail += decisionBox(kind, id, "/vcrs", JSON.stringify({
      related_artifact_type: "CRP", related_artifact_id: id,
      decision_status: "approved_with_changes", rationale: "<fill in>"}));
  } else if (kind === "MRP") {
    const m = await api("GET", "/mrps/" + id);
    let chain = null;
    try { chain = await api("GET", "/traceability/chain/" + id); } catch {}
    detail = `<div class="card"><h3>Merge request</h3>
      <p>Coder agent run <b class="mono">${esc(m.created_by_agent_run || "?")}</b> asks to merge
      branch <b class="mono">${esc(m.branch_name)}</b>.</p>
      <div class="grid c2" style="margin-top:12px">
        <div class="kv">
          <div class="k">Tests</div><div>${badge(m.unit_tests_status)}</div>
          <div class="k">Security scan</div><div>${badge(m.security_scan_status)}</div>
          <div class="k">Lint</div><div>${badge(m.lint_status)}</div>
          <div class="k">Blueprint</div><div class="mono">${esc(m.blueprint_id)} ${esc(m.blueprint_version || "")}</div>
          <div class="k">Specs</div><div class="mono">${esc((m.spec_ids || []).join(", "))}</div>
        </div>
        <div class="kv">
          <div class="k">Summary</div><div>${esc(m.change_summary || "")}</div>
          <div class="k">Affected modules</div><div class="mono">${esc((m.affected_modules || []).join(", "))}</div>
          <div class="k">Traceable</div><div>${chain ? (chain.fully_traceable ? "✅ yes" : "⚠️ partial") : "?"}</div>
        </div></div></div>`;
    detail += decisionBox(kind, id, `/mrps/${id}/human-decision`, JSON.stringify({decision: "approved"}));
  }
  document.getElementById("view").innerHTML =
    `<a href="#/approvals">← Back to approvals</a><div class="section-title">${kind}: <span class="mono">${esc(id)}</span></div>` + detail;
};

function decisionBox(kind, id, endpoint, bodyTemplate) {
  return `<div class="card dark">
    <h3 style="color:#fff;border-color:var(--gold)">Decision</h3>
    <div class="confirm-box" id="confirm-${kind}">
      You are approving this action as: <b>${esc(ME.actor_id)}</b><br>
      This decision will be <b>permanently recorded</b>.
    </div>
    <textarea id="note-${kind}" placeholder="Rationale (recorded)" style="width:100%;min-height:60px;
      border-radius:8px;border:1px solid var(--black-700);padding:8px"></textarea>
    <div style="margin-top:12px;display:flex;gap:10px">
      <button class="btn btn-approve" onclick="decide('${kind}','${endpoint}','${esc(id)}',true)">Approve</button>
      <button class="btn btn-reject" onclick="decide('${kind}','${endpoint}','${esc(id)}',false)">Reject</button>
    </div></div>`;
}

window.decide = async function(kind, endpoint, id, approve) {
  const note = (document.getElementById(`note-${kind}`)?.value || "").trim();
  let body = {};
  try { body = JSON.parse(endpoint.includes("vcrs") ? "{}" : "{}"); } catch {}
  if (kind === "SPEC_VALIDATION") body = {};
  else if (kind === "MRP") {
    if (!approve && !note) return toast("Rejection requires a rationale.");
    body = {decision: approve ? "approved" : "rejected", rationale: note};
  } else if (kind === "CRP") {
    if (!note) return toast("A VCR requires a rationale.");
    body = {related_artifact_type: "CRP", related_artifact_id: id,
            decision_status: approve ? "approved_with_changes" : "rejected",
            rationale: note};
  }
  try {
    await api("POST", endpoint, body);
    toast(`${approve ? "Approved" : "Rejected"} as ${ME.actor_id} — recorded.`);
    go("approvals");
  } catch (ex) { toast("Backend gate refused: " + ex.message); }
};

async function viewRuns(el, statusFilter) {
  const runs = await api("GET", "/dashboard/agent-runs" +
    (statusFilter ? `?status=${statusFilter}` : ""));
  el.innerHTML = `
    <h1 class="page">Agent Runs</h1>
    <p class="sub">Every generation is traceable to a run (§3.7.8).</p>
    <div class="filters">
      <select onchange="viewRuns(document.getElementById('view'), this.value)">
        ${["", "running", "completed", "failed", "blocked"].map(s =>
          `<option value="${s}" ${s === statusFilter ? "selected" : ""}>${s || "all statuses"}</option>`).join("")}
      </select></div>
    <table><thead><tr><th>Run</th><th>Project</th><th>Role</th><th>Status</th><th>Model</th><th>Started</th><th>MRP</th></tr></thead>
    <tbody>${runs.map(r => `<tr class="clickable" onclick="location.hash='#/evidence';setTimeout(()=>window.loadRun&&window.loadRun('${r.id}'),50)">
      <td class="mono">${esc(r.id)}</td><td>${esc(r.project_id)}</td><td>${esc(r.agent_role)}</td>
      <td>${badge(r.status)}</td><td class="mono">${esc(r.model_name)}</td>
      <td>${fmt(r.started_at)}</td><td class="mono">${esc(r.mrp_id || "—")}</td></tr>`).join("")}</tbody></table>`;
}

async function viewEvidence(el) {
  el.innerHTML = `
    <h1 class="page">Evidence & Traceability</h1>
    <p class="sub">Answer “why did this change happen?” from the immutable chain.</p>
    <div class="filters"><input id="ev-mrp" placeholder="MRP id, e.g. MRP-PR-78001" size="24">
    <button class="btn btn-primary" onclick="loadChain()">Load chain</button></div>
    <div id="chain-out"><i>Load an MRP chain to inspect Requirement → Spec → AgentRun → MRP → CRP → VCR → Merge.</i></div>`;
}
window.loadChain = async function() {
  const id = document.getElementById("ev-mrp").value.trim();
  if (!id) return;
  const c = await api("GET", "/traceability/chain/" + id);
  const step = (label, obj, ts) => obj ?
    `<div class="chain-step"><span class="chain-arrow">▼</span><b>${label}</b>
     <span class="mono">${esc(obj.id || "")}</span><span class="badge b-ok">${ts ? fmt(ts) : ""}</span></div>` :
    `<div class="chain-step"><span class="chain-arrow">▼</span><b>${label}</b><span class="badge b-danger">missing</span></div>`;
  document.getElementById("chain-out").innerHTML = `
    <div class="card"><h3>Full traceable chain ${c.fully_traceable ? "✅" : "(incomplete)"}</h3>
      ${step("PRD", c.prd, c.prd?.created_at)}
      ${(c.specs || []).map(s => step("SPEC", s)).join("")}
      ${step("AGENT RUN", c.agent_run, c.agent_run?.started_at)}
      ${step("MRP", c.mrp, c.mrp?.created_at)}
      ${(c.crps || []).map(x => step("CRP", x)).join("")}
      ${(c.vcrs || []).map(x => step("VCR", x, x.decided_at)).join("")}
    </div>
    <div class="card"><h3>Evidence export for this run</h3>
      <button class="btn btn-primary btn-sm" onclick="loadRunExport('${esc(c.agent_run?.id || "")}')">Fetch /evidence/run</button>
      <pre id="run-export" class="mono" style="margin-top:10px;white-space:pre-wrap"></pre></div>`;
};
window.loadRunExport = async function(runId) {
  if (!runId) return toast("This MRP has no agent run linked.");
  const e = await api("GET", "/evidence/run/" + runId);
  document.getElementById("run-export").textContent = JSON.stringify(e, null, 2);
};

async function viewAudit(el, params) {
  const q = params || "";
  const rows = await api("GET", "/dashboard/audit?" + q);
  el.innerHTML = `
    <h1 class="page">Audit Logs</h1>
    <p class="sub">Append-only record — who did what, when, under which identity.</p>
    <div class="filters">
      <input id="f-action" placeholder="action (e.g. mrp_human_decision)" size="26">
      <input id="f-actor" placeholder="actor contains…" size="18">
      <input id="f-artifact" placeholder="artifact id contains…" size="18">
      <button class="btn btn-primary btn-sm" onclick="filterAudit()">Filter</button></div>
    <table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Artifact</th><th>Result</th><th></th></tr></thead>
    <tbody>${rows.map(a => `<tr>
      <td>${fmt(a.timestamp)}</td><td class="mono">${esc(a.actor_id)}</td><td>${esc(a.action)}</td>
      <td class="mono">${esc(a.artifact_type || "")}:${esc(a.artifact_id || "")}</td>
      <td>${esc(a.result || a.human_decision || "")}</td>
      <td><button class="btn btn-ghost btn-sm" onclick='alert(${JSON.stringify(JSON.stringify(a.context || {}))})'>context</button></td>
    </tr>`).join("")}</tbody></table>`;
}
function filterAudit() {
  const p = new URLSearchParams();
  ["f-action:action", "f-actor:actor_id", "f-artifact:artifact_id"].forEach(pair => {
    const [elId, key] = pair.split(":");
    const v = document.getElementById(elId).value.trim();
    if (v) p.set(key, v);
  });
  viewAudit(document.getElementById("view"), p.toString());
}

async function viewProjects(el) {
  // Projects list via per-known-project summary is not available (no generic
  // project list w/ details beyond GET /projects); use blueprints-free list.
  const listResp = await api("GET", "/projects");
  const projects = Array.isArray(listResp) ? listResp : (listResp.items || []);
  el.innerHTML = `
    <h1 class="page">Projects</h1>
    <p class="sub">Complete state of every governed project.</p>
    <table><thead><tr><th>Project</th><th>Name</th><th>Stack</th><th></th></tr></thead>
    <tbody>${projects.map(p => `<tr><td class="mono">${esc(p.id)}</td><td>${esc(p.name)}</td>
      <td>${esc(p.stack)}</td>
      <td><button class="btn btn-primary btn-sm" onclick="openProject('${esc(p.id)}')">Open</button></td></tr>`).join("")}
    </tbody></table>`;
}
window.openProject = async function(pid) {
  const s = await api("GET", `/dashboard/projects/${pid}/summary`);
  document.getElementById("view").innerHTML = `
    <a href="#/projects">← All projects</a>
    <h1 class="page">${esc(s.project.name)} <small class="mono">(${esc(s.project.id)}, ${esc(s.project.stack)})</small></h1>
    <div class="section-title">Specs</div>
    <table><tbody>${s.specs.map(x => `<tr><td class="mono">${esc(x.id)}</td>
      <td>${x.human_validated ? badge("passed") : badge("pending")} ${x.human_validated ? "validated" : "awaiting human validation"}</td>
      <td>${fmt(x.created_at)}</td></tr>`).join("")}</tbody></table>
    <div class="section-title">Agent Runs</div>
    <table><tbody>${s.runs.map(r => `<tr><td class="mono">${esc(r.id)}</td><td>${badge(r.status)}</td>
      <td>${esc(r.agent_role)}</td><td>${fmt(r.started_at)}</td></tr>`).join("")}</tbody></table>
    <div class="section-title">MRPs</div>
    <table><tbody>${s.mrps.map(m => `<tr><td class="mono">${esc(m.id)}</td><td>${badge(m.status)}</td>
      <td>${fmt(m.created_at)}</td></tr>`).join("")}</tbody></table>`;
};

async function viewConsole(el) {
  const instructions = (await api("GET", "/dashboard/audit?action=agent_instruction&limit=25")).reverse();
  const runs = await api("GET", "/dashboard/agent-runs?limit=10");
  el.innerHTML = `
    <h1 class="page">Agent Console</h1>
    <p class="sub">Issue governed instructions (recorded to the audit trail) and follow live run activity.
       Pipeline execution remains CLI-driven: <span class="mono">python -m agents.orchestrator --online …</span></p>
    <div class="grid c2">
      <div>
        <div class="chat-log" id="chatlog">
          ${instructions.map(i => `<div class="msg system mono">${fmt(i.timestamp)}</div>
            <div class="msg human">${esc(i.context?.instruction || "")}<br>
            <small class="mono">${esc(i.actor_id)}</small></div>`).join("") ||
            '<div class="msg system">No instructions yet.</div>'}
        </div>
        <div style="display:flex;gap:8px;margin-top:10px">
          <input id="chat-input" style="flex:1;padding:9px;border-radius:8px;border:1px solid #CBD5E1"
                 placeholder="e.g. Implement authentication improvements on todo-springboot…">
          <button class="btn btn-primary" onclick="sendInstruction()">Send</button></div>
      </div>
      <div class="card dark"><h3 style="color:#fff">Live agent activity</h3>
        ${runs.map(r => `<div style="padding:6px 0;border-bottom:1px solid var(--black-700)">
          <span class="mono">${esc(r.id)}</span> ${badge(r.status)}<br>
          <small style="color:var(--slate-400)">${esc(r.agent_role)} · ${esc(r.task_type)} · ${fmt(r.started_at)}</small>
        </div>`).join("")}</div></div>`;
}
window.sendInstruction = async function() {
  const inp = document.getElementById("chat-input");
  const text = inp.value.trim();
  if (!text) return;
  try { await api("POST", "/dashboard/console/instructions", {instruction: text});
    inp.value = ""; toast("Instruction recorded to audit trail."); viewConsole(document.getElementById("view"));
  } catch (ex) { toast(ex.message); }
};

// --------------------------------------------------- SoD validation demo ----
const DEMO_PROJECTS = ["demo-task-manager", "sod-map-demo"];

async function viewValidation(el, project) {
  project = project || DEMO_PROJECTS[0];
  const [summary, runs, evAudit] = await Promise.all([
    api("GET", `/dashboard/projects/${project}/summary`),
    api("GET", `/dashboard/agent-runs?project_id=${project}&limit=5`),
    api("GET", "/dashboard/audit?action=update_mrp_evidence&limit=10"),
  ]);

  el.innerHTML = `
    <h1 class="page">SoD Validation — <span class="mono">${esc(project)}</span></h1>
    <p class="sub">Proposal-only coder → orchestrator verification → human gates.</p>
    <div class="filters"><select onchange="viewValidation(document.getElementById('view'), this.value)">
      ${DEMO_PROJECTS.map(p => `<option value="${p}" ${p === project ? "selected" : ""}>${p}</option>`).join("")}
    </select></div>`;

  for (const run of runs) {
    el.insertAdjacentHTML("beforeend",
      await renderSodTimeline(project, summary, run, runs, evAudit));
  }
  if (!runs.length) {
    el.insertAdjacentHTML("beforeend", "<div class='card'>No agent runs yet.</div>");
  }

  el.insertAdjacentHTML("beforeend", `
    <div class="card"><h3>Audit events</h3>
      <table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Artifact</th></tr></thead><tbody>
      ${(await auditRowsFor(project)).join("")}</tbody></table></div>`);
}

async function renderSodTimeline(project, summary, run, runs, evAudit) {
  const mrpId = run.mrp_id;
  const mrp = summary.mrps.find(m => m.id === mrpId);
  const ev = mrpId ? evAudit.find(a => a.artifact_id === mrpId
    && a.context?.execution_context?.tree_hash) : null;
  const ec = ev?.context?.execution_context || {};
  let decision = null;
  if (mrpId) {
    const dec = await api("GET",
      `/dashboard/audit?action=mrp_human_decision&artifact_id=${mrpId}&limit=1`);
    decision = dec[0] || null;
  }
  const spec = summary.specs[0] || null;

  const stage = (label, state, detail) => `
    <div class="chain-step"><span class="chain-arrow">▼</span>
      <b style="min-width:150px">${label}</b> ${state}
      <span style="color:var(--slate-600);font-size:12px">${detail}</span></div>`;

  return `
    <div class="card"><h3>${esc(run.id)} <small style="color:var(--slate-600)">(${esc(run.task_type)})</small></h3>
      <div class="grid c3">
        <div class="stat"><div class="l">Human authority</div><b class="gold">${esc(ME.actor_id)}</b></div>
        <div class="stat"><div class="l">Agent identity</div><b>${esc(run.agent_role)}</b>
          <small class="mono" style="display:block;color:var(--slate-600)">${esc(run.model_name)}</small></div>
        <div class="stat"><div class="l">Verifier identity</div><b>${esc(ec.runner || "?")}</b>
          <small style="display:block;color:var(--slate-600)">provenance: ${esc(ec.provenance || "?")}</small></div>
      </div>
      ${stage("Requirement", badge("completed"), `${esc(summary.project.name)} — by ${ME.actor_id}`)}
      ${stage("Spec drafted + validated", spec ? badge(spec.human_validated ? "completed" : "pending") : badge("pending"),
        spec ? `${esc(spec.id)} · GATE 1 by ${esc(spec.human_validated_by || ME.actor_id)}` : "—")}
      ${stage("Coder PROPOSAL ONLY", badge("completed"),
        `<span class="mono">${esc(run.id)}</span> · ${(run.generated_files || []).length} files committed · verified nothing itself`)}
      ${stage("Orchestrator verification", ec.tree_hash ? badge(testsState(ec)) : badge("pending"),
        ec.tree_hash ? `tests ${ec.unit_tests_status || "?"} · scan ${ev.context.security_scan_status || "?"} · lint ${ev.context.lint_status || "?"} · tree <span class="mono">${esc(String(ec.tree_hash).slice(0,12))}…</span>` : "awaiting evidence")}
      ${stage("Evidence recorded", ev ? badge("ok") : badge("pending"),
        ev ? `by <span class="mono">${esc(ev.actor_id)}</span> at ${fmt(ev.timestamp)} (runner=${esc(ec.runner || "?")})` : "—")}
      ${stage("MRP", mrpId ? badge(mrp?.status || "draft") :
          badge("pending"), mrpId ? `<a href="#/evidence" onclick="document.getElementById('ev-mrp').value='${esc(mrpId)}'">${esc(mrpId)}</a>` : "—")}
      ${stage("Merge decision (human)", decision ? badge(decision.human_decision || "approved") : badge("awaiting"),
        decision ? `${esc(decision.actor_id)} at ${fmt(decision.timestamp)}` :
          (mrpId ? `waiting for you → Approval Center (${esc(mrpId)})` : "—"))}
    </div>`;
}

function testsState(ec) { return (ec.unit_tests_status === "passed") ? "passed" : "failed"; }

async function auditRowsFor(project) {
  const rows = await api("GET", "/dashboard/audit?limit=40");
  return rows.filter(a =>
    (a.artifact_id || "").includes("DTM") ||
    ["start_agent_run","update_mrp_evidence","mrp_human_decision","create_mrp"].includes(a.action)
  ).slice(0, 12).map(a => `<tr>
    <td>${fmt(a.timestamp)}</td><td class="mono">${esc(a.actor_id)}</td>
    <td>${esc(a.action)}</td><td class="mono">${esc(a.artifact_id || "")}</td></tr>`);
}

function viewSettings(el) {
  el.innerHTML = `
    <h1 class="page">Settings</h1>
    <p class="sub">Session and identity.</p>
    <div class="card"><h3>Your session</h3><div class="kv">
      <div class="k">Username</div><div>${esc(ME.username)}</div>
      <div class="k">Actor id used for approvals</div><div class="gold"><b>${esc(ME.actor_id)}</b></div>
      <div class="k">Token</div><div class="mono">${esc((sessionStorage.getItem(TOKEN_KEY) || "").slice(0, 12))}…</div>
      <div class="k">Auth mode</div><div>Bearer token (authoritative) — X-Acting-As never sent by this UI</div>
    </div></div>
    <div class="card"><h3>About</h3><p>SASE Governance Dashboard — a read-mostly client over
    the ai-swe-engine. The backend remains the source of truth; all decisions pass the same
    gated endpoints as before.</p></div>`;
}

// ------------------------------------------------------------------ boot
(async function boot() {
  document.getElementById("login-form").addEventListener("submit", login);
  document.getElementById("logout").addEventListener("click", logout);

  const onLoginPage = location.pathname.endsWith("/ui/login");
  const onDash = location.pathname.endsWith("/ui/dashboard");
  const hasToken = !!sessionStorage.getItem(TOKEN_KEY);

  // Unauthenticated anywhere -> login page (the UI entry point).
  if (!hasToken && !onLoginPage) { location.replace("/ui/login"); return; }
  // Already authenticated but sitting on /ui/login -> straight to dashboard.
  if (hasToken && onLoginPage) { location.replace("/ui/dashboard"); return; }

  if (onLoginPage) { showLogin(); return; }   // FIX: login view ships hidden;
                                              // it was never unhidden without a token.
  try { await enterApp(); }
  catch { logout(); }                         // invalid/expired token -> login page
})();
