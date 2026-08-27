/* 「歧路」前端逻辑（零依赖原生JS） */
"use strict";

const $ = (id) => document.getElementById(id);
let SID = localStorage.getItem("qilu_sid") || null;
let busy = false;

/* ---------- 基础请求 ---------- */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || ("HTTP " + res.status));
  }
  return res.json();
}

/* ---------- 渲染 ---------- */
function renderState(view) {
  $("chapter-chip").textContent = "第" + view.chapter + "章";
  if (view.story) $("story-title").innerHTML =
    "《" + view.story.title + "》<span id=\"chapter-chip\" class=\"chip\">第" + view.chapter + "章</span>";
  renderBars("stats", view.stats, view.stat_defs || {});
  renderBars("tendencies", view.tendencies, view.stat_defs || {});
  renderBeatPath(view.beat_path);
  renderFacts(view.facts);
}

const TEND_LABELS = {
  caution: "谨慎", empathy: "共情", order: "守序", curiosity: "好奇", trust: "信任",
};

function renderBars(elId, data, defs) {
  const el = $(elId);
  el.innerHTML = "";
  for (const [k, v] of Object.entries(data)) {
    const d = defs[k] || {};
    const label = d.label || TEND_LABELS[k] || k;
    const lo = (d.min !== undefined) ? d.min : (k in TEND_LABELS ? -1 : 0);
    const hi = (d.max !== undefined) ? d.max : (k in TEND_LABELS ? 1 : 100);
    const isTend = hi === 1 && lo === -1;
    const pct = hi === lo ? 100 : ((v - lo) / (hi - lo)) * 100;
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML =
      '<div class="bar-label"><span>' + label + "</span><span>" +
      (isTend ? (v >= 0 ? "+" : "") + v.toFixed(2) : Math.round(v)) +
      '</span></div><div class="bar-track"><div class="bar-fill ' +
      (isTend ? "tend-fill" : "") + '" style="width:' + pct + '%"></div></div>';
    el.appendChild(row);
  }
}

function renderBeatPath(path) {
  const el = $("beat-path");
  el.innerHTML = path.length
    ? path.map((b) => '<span class="beat-dot">' + b + "</span>").join("")
    : '<span class="muted">开局后显示</span>';
}

function renderFacts(facts) {
  const el = $("facts");
  el.innerHTML = facts.length
    ? facts.map((f) => '<div class="fact-item">· ' + f + "</div>").join("")
    : '<span class="muted">暂无</span>';
}

function addSystem(text) {
  const div = document.createElement("div");
  div.className = "msg-sys";
  div.textContent = text;
  $("chat").appendChild(div);
  scrollBottom();
}

async function addNarrative(text, instant) {
  const msg = document.createElement("div");
  msg.className = "msg";
  const bubble = document.createElement("div");
  bubble.className = "msg-narr";
  if (!instant) bubble.classList.add("cursor");
  msg.appendChild(bubble);
  $("chat").appendChild(msg);
  if (instant) {
    bubble.textContent = text;
    scrollBottom();
    return;
  }
  // 打字机效果
  for (let i = 0; i < text.length; i += 2) {
    bubble.textContent = text.slice(0, i + 2);
    scrollBottom();
    await sleep(12);
  }
  bubble.classList.remove("cursor");
}

function addChoice(text) {
  const msg = document.createElement("div");
  msg.className = "msg msg-choice";
  msg.textContent = "» " + text;
  $("chat").appendChild(msg);
  scrollBottom();
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function scrollBottom() { $("chat").scrollTop = $("chat").scrollHeight; }

/* ---------- 交互 ---------- */
function setBusy(b) {
  busy = b;
  $("thinking").classList.toggle("hidden", !b);
  $("choices").querySelectorAll("button").forEach((x) => (x.disabled = b));
  $("btn-send").disabled = b;
  $("free-input").disabled = b;
}

function renderScene(view) {
  if (!view.scene) return;
  renderState(view);
  renderNarrativeThenChoices(view.scene);
}

function renderNarrativeThenChoices(scene) {
  const choices = $("choices");
  choices.innerHTML = "";
  addNarrative(scene.narrative).then(() => renderChoiceButtons(scene.choices));
}

function renderChoiceButtons(choices) {
  const box = $("choices");
  box.innerHTML = "";
  for (let i = 0; i < choices.length; i++) {
    const ch = choices[i];
    const btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = (i + 1) + ". " + ch.text;
    btn.onclick = () => choose(i + 1, ch.text);
    box.appendChild(btn);
  }
  setBusy(false);
}

async function choose(index, text) {
  if (busy) return;
  setBusy(true);
  addChoice(text);
  const bubble = beginStream();
  try {
    const view = await streamTurn(SID, { choice_index: index }, bubble);
    afterTurn(view);
  } catch (e) {
    finalizeStream(bubble, "（生成失败: " + e.message + "）");
    setBusy(false);
  }
}

async function freeAct() {
  const text = $("free-input").value.trim();
  if (!text || busy) return;
  setBusy(true);
  $("free-input").value = "";
  addChoice(text);
  const bubble = beginStream();
  try {
    const view = await streamTurn(SID, { free_text: text }, bubble);
    afterTurn(view);
  } catch (e) {
    finalizeStream(bubble, "（生成失败: " + e.message + "）");
    setBusy(false);
  }
}

/* ---------- 流式渲染 ---------- */
function beginStream() {
  const msg = document.createElement("div");
  msg.className = "msg";
  const bubble = document.createElement("div");
  bubble.className = "msg-narr cursor";
  bubble.textContent = "";
  msg.appendChild(bubble);
  $("chat").appendChild(msg);
  scrollBottom();
  return bubble;
}

function appendDelta(bubble, text) {
  bubble.textContent += text;
  scrollBottom();
}

function finalizeStream(bubble, text) {
  bubble.textContent = text;
  bubble.classList.remove("cursor");
  scrollBottom();
}

async function streamTurn(sid, body, bubble) {
  const res = await fetch("/api/sessions/" + sid + "/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || ("HTTP " + res.status));
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.indexOf("application/json") >= 0) {
    const view = await res.json();          // 兼容非流式
    if (view.scene) finalizeStream(bubble, view.scene.narrative);
    return view;
  }
  // NDJSON 流
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let view = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      let evt;
      try { evt = JSON.parse(line); } catch (e) { continue; }
      if (evt.type === "delta") {
        appendDelta(bubble, evt.text);
      } else if (evt.type === "done") {
        view = evt.view;
        if (view.scene) finalizeStream(bubble, view.scene.narrative);
      } else if (evt.type === "error") {
        throw new Error(evt.detail || "生成错误");
      }
    }
  }
  if (!view) throw new Error("流式响应异常终止");
  return view;
}

function afterTurn(view) {
  if (view.finished) {
    renderState(view);
    showEnding();
  } else {
    renderState(view);
    renderChoiceButtons(view.scene.choices);  // 正文已流式渲染，这里只出选项
  }
}

/* ---------- 结局 ---------- */
async function showEnding() {
  setBusy(false);
  const recap = await api("/api/sessions/" + SID + "/recap").catch(() => null);
  if (recap && recap.ending) {
    $("ending-name").textContent = "「" + recap.ending.name + "」";
    $("ending-type").textContent = "结局 · " + (recap.ending.type || "");
    const el = $("ending-recap");
    const labels = {
      caution: "谨慎", empathy: "共情", order: "守序", curiosity: "好奇", trust: "信任",
    };
    const tend = Object.entries(recap.tendencies)
      .map(([k, v]) => (labels[k] || k) + " " + (v >= 0 ? "+" : "") + v.toFixed(2))
      .join(" · ");
    const choices = recap.choices
      .map((c) => '<div class="choice-line">» ' + escapeHtml(c.choice || "") + "</div>").join("");
    el.innerHTML =
      "<h4>你的专属路线图</h4>" + buildRouteGraph(recap) +
      "<h4>你的倾向画像</h4><div>" + tend + "</div>" +
      "<h4>你的每一次选择</h4>" + (choices || "无") +
      "<h4>数据足迹</h4><div>确认事实 " + recap.facts.length + " 项 · 事件账本 " +
      recap.event_count + " 条 · 生成降级 " + recap.fallback_flags.length + " 次</div>";
  }
  $("ending").classList.remove("hidden");
}

function truncate(s, n) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function endingColor(ending) {
  const map = { good: "#d4a24e", bad: "#b0554a", secret: "#a58fd4", neutral: "#8494a5", open: "#55606e" };
  return map[(ending && ending.type) || "open"] || "#55606e";
}

/* ---------- 专属路线图（SVG节点图） ---------- */
function buildRouteGraph(recap) {
  const route = recap.route || [];
  if (!route.length) return '<p class="muted">无路线数据</p>';
  const N = route.length;
  const step = 150, x0 = 70, y = 76, W = x0 + (N - 1) * step + 190;
  const s = [];
  s.push('<svg viewBox="0 0 ' + W + ' 240" xmlns="http://www.w3.org/2000/svg" class="route-svg">');
  s.push('<line x1="' + (x0 - 18) + '" y1="' + y + '" x2="' + (x0 + (N - 1) * step + 64) +
         '" y2="' + y + '" stroke="#2a3441" stroke-width="3"/>');
  const doneTurns = [];
  for (let i = 0; i < N; i++) {
    const b = route[i], x = x0 + i * step;
    const done = b.status === "done";
    const skipped = b.status === "skipped";
    const fill = done ? "#d4a24e" : "none";
    const stroke = skipped ? "#4a5568" : (done ? "#d4a24e" : "#2a3441");
    const op = done ? 1 : 0.45;
    if (b.kind === "optional") {
      s.push('<polygon points="' + x + ',' + (y - 14) + ' ' + (x + 14) + ',' + y + ' ' +
             x + ',' + (y + 14) + ' ' + (x - 14) + ',' + y + '" fill="' + fill +
             '" stroke="' + stroke + '" stroke-width="2" opacity="' + op + '"/>');
    } else {
      s.push('<circle cx="' + x + '" cy="' + y + '" r="' + (done ? 15 : 12) +
             '" fill="' + fill + '" stroke="' + stroke + '" stroke-width="2" opacity="' + op + '"' +
             (b.kind === "conditional" ? ' stroke-dasharray="4 2"' : "") + "/>");
    }
    if (skipped) {
      s.push('<text x="' + x + '" y="' + (y + 4) + '" text-anchor="middle" fill="#8494a5" font-size="11">✕</text>');
    } else if (done && b.turn != null) {
      s.push('<text x="' + x + '" y="' + (y + 4) + '" text-anchor="middle" fill="#101418" font-size="10" font-weight="700">' + b.turn + "</text>");
    }
    s.push('<text x="' + x + '" y="' + (y - 28) + '" text-anchor="middle" fill="' +
           (done ? "#d8dee6" : "#55606e") + '" font-size="12" font-weight="600">' + b.beat_id + "</text>");
    const sub = b.skip_reason ? ("跳过·" + b.skip_reason) : truncate(b.must_happen || "", 12);
    s.push('<text x="' + x + '" y="' + (y + 36) + '" text-anchor="middle" fill="' +
           (done ? "#8494a5" : "#3d4754") + '" font-size="10">' + escapeHtml(sub) + "</text>");
    if (done) doneTurns.push({ x: x, turn: b.turn || 0 });
  }
  // 相邻完成节拍之间的选项标签
  const choices = recap.choices || [];
  for (let i = 1; i < doneTurns.length; i++) {
    const prev = doneTurns[i - 1], cur = doneTurns[i];
    const ch = choices.find((c) => c.turn > prev.turn && c.turn <= cur.turn);
    if (ch && ch.choice) {
      const mx = (prev.x + cur.x) / 2;
      s.push('<text x="' + mx + '" y="' + (y - 46) + '" text-anchor="middle" fill="#8fa8c0" font-size="10">» ' +
             escapeHtml(truncate(ch.choice, 14)) + "</text>");
    }
  }
  // 结局节点
  const endX = x0 + (N - 1) * step + 76;
  const ec = endingColor(recap.ending);
  s.push('<polygon points="' + endX + ',' + (y - 16) + ' ' + (endX + 16) + ',' + y + ' ' +
         endX + ',' + (y + 16) + ' ' + (endX - 16) + ',' + y + '" fill="' + ec + '" stroke="#101418" stroke-width="2"/>');
  s.push('<text x="' + endX + '" y="' + (y - 26) + '" text-anchor="middle" fill="' + ec +
         '" font-size="13" font-weight="700">' + escapeHtml((recap.ending && recap.ending.name) || "?") + "</text>");
  s.push('<text x="' + endX + '" y="' + (y + 34) + '" text-anchor="middle" fill="#8494a5" font-size="10">结局</text>');
  s.push("</svg>");
  const legend =
    '<div class="route-legend">' +
    '<span><i class="lg lg-fixed"></i>fixed 必走</span>' +
    '<span><i class="lg lg-cond"></i>conditional 条件触发</span>' +
    '<span><i class="lg lg-opt"></i>optional 倾向解锁</span>' +
    '<span><i class="lg lg-skip"></i>跳过/未达</span>' +
    "</div>";
  return '<div class="route-wrap">' + s.join("") + legend + "</div>";
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- 剧本选择 / 开局 / 续玩 / 换剧本 ---------- */
async function loadStories() {
  try {
    const stories = await api("/api/stories");
    const box = $("story-cards");
    box.innerHTML = "";
    for (const s of stories) {
      const card = document.createElement("div");
      card.className = "story-card";
      const genre = (s.genre || []).map((g) => '<span class="genre-chip">' + g + "</span>").join("");
      card.innerHTML =
        '<div class="story-card-head"><span class="story-card-title">《' + s.title + "》</span>" +
        '<span class="story-card-meta">' + (s.endings || 0) + "种结局 · 约" + (s.chapters || "?") + "章</span></div>" +
        '<div class="story-card-desc">' + s.desc + "</div>" +
        '<div class="story-card-foot">' + genre +
        '<button class="btn primary story-card-btn">开始</button></div>';
      card.querySelector("button").onclick = () => startNew(s.id);
      box.appendChild(card);
    }
  } catch (e) {
    $("story-cards").innerHTML = '<p class="muted">剧本加载失败: ' + e.message + "</p>";
  }
}

async function startNew(storyId) {
  setBusy(true);
  try {
    const view = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ story_id: storyId }),
    });
    SID = view.sid;
    localStorage.setItem("qilu_sid", SID);
    $("start").classList.add("hidden");
    $("ending").classList.add("hidden");
    $("chat").innerHTML = "";
    addSystem("你走进了这个故事");
    renderScene(view);
  } catch (e) {
    alert("开局失败: " + e.message);
    setBusy(false);
  }
}

function backToPicker() {
  localStorage.removeItem("qilu_sid");
  SID = null;
  $("ending").classList.add("hidden");
  $("chat").innerHTML = "";
  $("start").classList.remove("hidden");
  loadStories();
}

async function resume() {
  if (!SID) return;
  try {
    const view = await api("/api/sessions/" + SID);
    $("start").classList.add("hidden");
    $("chat").innerHTML = "";
    if (view.finished) {
      renderState(view);
      showEnding();
      return;
    }
    addSystem("已为你恢复存档");
    // 回放历史时间线（正文即时渲染，不逐字打字）
    const hist = view.history || [];
    const last = hist.length - 1;
    for (let i = 0; i < hist.length; i++) {
      const h = hist[i];
      if (h.kind === "narr") {
        if (i === last) break; // 最后一场正文交给下方实时渲染，避免重复
        addNarrative(h.text, true);
      } else {
        addChoice(h.text);
      }
    }
    renderState(view);
    renderNarrativeThenChoices(view.scene);
  } catch (e) {
    /* 无存档则停留开局页 */
  }
}

$("btn-restart").onclick = backToPicker;
$("btn-new").onclick = () => {
  if (confirm("换剧本会丢弃当前进度，确定吗？")) backToPicker();
};
$("btn-send").onclick = freeAct;
$("free-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") freeAct();
});

loadStories();
resume();
