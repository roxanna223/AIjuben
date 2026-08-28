/* 「歧路」前端逻辑（零依赖原生JS） */
"use strict";

const $ = (id) => document.getElementById(id);
let SID = localStorage.getItem("qilu_sid") || null;
let busy = false;
let enteringStory = false;   // 进入故事过渡防抖:同一时间只允许一次开局/恢复请求

/* ---------- 人物头像配置 ----------
   每个角色的人物图片放在 server/static/avatars/ 目录下，在此按角色ID登记。
   当前为程序手绘的扁平风SVG占位头像（零生成成本）；
   后续换成AI生成的人物图时，只需把对应路径改掉（支持 png/jpg/webp/svg）。
   未登记的角色会自动显示"首字彩色占位头像"。 */
const AVATAR_IMAGES = {
  pc: "/avatars/pc.svg",       // 你（主角，双剧本共用）
  lin: "/avatars/lin.svg",     // 林sir《午夜列车》
  aunt: "/avatars/aunt.svg",   // 葛姨《午夜列车》
  boy: "/avatars/boy.svg",     // 小满《午夜列车》
  zhou: "/avatars/zhou.svg",   // 老周《规则楼》
  he: "/avatars/he.svg",       // 阿禾《规则楼》
};

let CHARS = {};   // 当前剧本的人物表 { id: {name, role} }，由服务端下发

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
  if (view.characters) CHARS = view.characters;
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

/* ---------- 人物对话渲染（文字游戏式气泡） ---------- */

function speakerName(speaker) {
  if (speaker === "narrator") return "旁白";
  const ch = CHARS[speaker];
  return (ch && ch.name) || speaker;
}

/* 确定性哈希：同一角色始终同色（头像占位/名字着色），后续替换为人物图片后仍可保留名字色 */
function speakerHue(id) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360;
  return h;
}

function buildLineEl(speaker, text) {
  const isPc = speaker === "pc";
  const isNarr = speaker === "narrator";
  const msg = document.createElement("div");
  msg.className = "msg msg-line" + (isPc ? " msg-pc" : "") + (isNarr ? " msg-narr" : "");
  msg.dataset.speaker = speaker;

  if (isNarr) {
    const b = document.createElement("div");
    b.className = "narr-text";
    b.textContent = text;
    msg.appendChild(b);
    return msg;
  }

  // 头像槽：有登记图片时渲染 <img>，否则显示首字彩色占位（后续可直接换图）
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  const imgUrl = AVATAR_IMAGES[speaker];
  if (imgUrl) {
    const img = document.createElement("img");
    img.className = "avatar-photo";
    img.src = imgUrl;
    img.alt = speakerName(speaker);
    img.loading = "lazy";
    avatar.appendChild(img);
  } else {
    const fb = document.createElement("span");
    fb.className = "avatar-fallback";
    fb.textContent = (speakerName(speaker) || "?").charAt(0);
    fb.style.background = "hsl(" + speakerHue(speaker) + ", 38%, 26%)";
    fb.style.borderColor = "hsl(" + speakerHue(speaker) + ", 45%, 55%)";
    avatar.appendChild(fb);
  }

  const body = document.createElement("div");
  body.className = "line-body";
  const name = document.createElement("div");
  name.className = "line-name";
  name.textContent = speakerName(speaker);
  if (!isPc) name.style.color = "hsl(" + speakerHue(speaker) + ", 42%, 72%)";
  const bubble = document.createElement("div");
  bubble.className = "line-bubble";
  bubble.textContent = text;
  body.appendChild(name);
  body.appendChild(bubble);

  msg.appendChild(avatar);
  msg.appendChild(body);
  return msg;
}

/* 打字目标：NPC/主角行是气泡，旁白行是居中文本 */
function textTarget(el) {
  return el.querySelector(".line-bubble") || el.querySelector(".narr-text");
}

async function addLine(speaker, text, instant) {
  const el = buildLineEl(speaker, instant ? text : "");
  $("chat").appendChild(el);
  if (instant) {
    scrollBottom();
    return;
  }
  // 打字机效果
  const target = textTarget(el);
  target.classList.add("cursor");
  for (let i = 0; i < text.length; i += 2) {
    target.textContent = text.slice(0, i + 2);
    scrollBottom();
    await sleep(12);
  }
  target.classList.remove("cursor");
}

async function addDialogue(lines, instant) {
  for (const ln of (lines || [])) {
    await addLine(ln.speaker, ln.text, instant);
  }
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
  renderDialogueThenChoices(view.scene);
}

function renderDialogueThenChoices(scene) {
  const choices = $("choices");
  choices.innerHTML = "";
  addDialogue(scene.dialogue, false).then(() => renderChoiceButtons(scene.choices));
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
  const box = beginStream();
  try {
    const view = await streamTurn(SID, { choice_index: index }, box);
    afterTurn(view, box);
  } catch (e) {
    addSystem("（生成失败: " + e.message + "）");
    setBusy(false);
  }
}

async function freeAct() {
  const text = $("free-input").value.trim();
  if (!text || busy) return;
  setBusy(true);
  $("free-input").value = "";
  addChoice(text);
  const box = beginStream();
  try {
    const view = await streamTurn(SID, { free_text: text }, box);
    afterTurn(view, box);
  } catch (e) {
    addSystem("（生成失败: " + e.message + "）");
    setBusy(false);
  }
}

/* ---------- 流式渲染 ---------- */
function beginStream() {
  const root = document.createElement("div");
  root.className = "stream-root";
  $("chat").appendChild(root);
  scrollBottom();
  return { root: root, rows: [] };   // rows: 已流式渲染的对话行
}

function streamLine(box, speaker, text) {
  box.root.appendChild(buildLineEl(speaker, text));
  box.rows.push({ speaker: speaker, text: text });
  scrollBottom();
}

function linesMatch(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].speaker !== b[i].speaker || a[i].text !== b[i].text) return false;
  }
  return true;
}

async function streamTurn(sid, body, box) {
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
    return await res.json();          // 兼容非流式：afterTurn 会整体渲染最终对话
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
      if (evt.type === "line") {
        streamLine(box, evt.speaker, evt.text);
      } else if (evt.type === "done") {
        view = evt.view;
      } else if (evt.type === "error") {
        throw new Error(evt.detail || "生成错误");
      }
    }
  }
  if (!view) throw new Error("流式响应异常终止");
  return view;
}

function afterTurn(view, box) {
  renderState(view);
  if (view.finished) {
    showEnding();
    return;
  }
  // 流式行与最终对话一致则保留；不一致（重写/降级）则整体重绘，保证所见即最终剧本
  if (box && !linesMatch(box.rows, view.scene.dialogue)) {
    box.root.innerHTML = "";
    box.rows = [];
    for (const ln of (view.scene.dialogue || [])) {
      box.root.appendChild(buildLineEl(ln.speaker, ln.text));
    }
    scrollBottom();
  }
  renderChoiceButtons(view.scene.choices);  // 正文已流式渲染，这里只出选项
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
      card.querySelector("button").onclick = () => startNew(s.id, s.title);
      box.appendChild(card);
    }
    // 有存档时在顶部显示"继续上次的故事"卡片(不自动进入,选故事页始终优先展示)
    if (SID) {
      try {
        const v = await api("/api/sessions/" + SID);
        const card = document.createElement("div");
        card.className = "story-card resume-card";
        card.innerHTML =
          '<div class="story-card-head"><span class="story-card-title">↻ 继续上次的故事</span>' +
          '<span class="story-card-meta">第' + v.chapter + "章 · 第" + v.turn + "回合</span></div>" +
          '<div class="story-card-desc">《' + (v.story && v.story.title) + "》" +
          (v.finished ? " · 已通关,可查看结局" : " · 从上次的位置继续") + "</div>" +
          '<div class="story-card-foot"><button class="btn primary story-card-btn">继续</button></div>';
        card.querySelector("button").onclick = () => resumeStory();
        box.insertBefore(card, box.firstChild);
      } catch (e) { /* 存档失效则忽略,只展示剧本列表 */ }
    }
  } catch (e) {
    $("story-cards").innerHTML = '<p class="muted">剧本加载失败: ' + e.message + "</p>";
  }
}

async function startNew(storyId, title) {
  if (enteringStory) return;          // 双保险:防连点触发多次开局
  enteringStory = true;
  // 立即切到"加载中"过渡页:选择按钮随页面隐藏,用户无法再点
  $("start").classList.add("hidden");
  $("loading").classList.remove("hidden");
  $("loading-title").textContent = "正在进入《" + (title || storyId) + "》";
  try {
    const view = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ story_id: storyId }),
    });
    SID = view.sid;
    localStorage.setItem("qilu_sid", SID);
    $("loading").classList.add("hidden");
    $("ending").classList.add("hidden");
    $("chat").innerHTML = "";
    addSystem("你走进了这个故事");
    renderScene(view);
    enteringStory = false;
  } catch (e) {
    enteringStory = false;
    $("loading").classList.add("hidden");
    $("start").classList.remove("hidden");
    alert("开局失败: " + e.message + "\n已返回首页,可重新进入。");
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
  if (!SID) return false;
  try {
    const view = await api("/api/sessions/" + SID);
    $("start").classList.add("hidden");
    $("chat").innerHTML = "";
    if (view.finished) {
      renderState(view);
      showEnding();
      return true;
    }
    addSystem("已为你恢复存档");
    // 回放历史时间线（对话行即时渲染，不逐字打字；当前场景的行跳过，交给下方实时渲染）
    const hist = view.history || [];
    for (let i = 0; i < hist.length; i++) {
      const h = hist[i];
      if (h.is_current) break;   // 到达当前场景首行：其后由实时渲染负责
      if (h.kind === "line") {
        addLine(h.speaker, h.text, true);
      } else {
        addChoice(h.text);
      }
    }
    renderState(view);
    renderDialogueThenChoices(view.scene);
    return true;
  } catch (e) {
    return false;  // 存档失效:留在选故事页
  }
}

/* 从选故事页"继续"卡片进入:同样走加载页过渡,防连点 */
async function resumeStory() {
  if (enteringStory) return;
  enteringStory = true;
  $("start").classList.add("hidden");
  $("loading").classList.remove("hidden");
  $("loading-title").textContent = "正在恢复你的故事";
  const ok = await resume();
  $("loading").classList.add("hidden");
  enteringStory = false;
  if (!ok) $("start").classList.remove("hidden");
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
/* 注意:不再自动 resume()——打开网站始终先展示选故事页,
   有存档时由"继续上次的故事"卡片显式进入(同样走加载页)。 */
