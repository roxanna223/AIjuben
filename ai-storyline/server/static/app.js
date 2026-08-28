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

/* 立即渲染一行（历史回放用，不走逐句播放器） */
function appendLineInstant(speaker, text) {
  const el = buildLineEl(speaker, text);
  $("chat").appendChild(el);
}

/* ---------- 逐句播放器（文字游戏式） ----------
   每次只显示一句话：当前句打字完成后等待推进（点击对话区或按空格）。
   自动播放模式下按文本长度放慢推进，遇到选项时暂停；玩家选完、新场景
   行流入后自动继续。 */
const Player = {
  container: null,      // 当前场景行的渲染容器
  queue: [],            // 待显示的对话行 [{speaker,text}]
  state: "idle",        // idle | typing | wait（wait=等点击/空格推进）
  cur: null,            // 当前行 {el, target, text}
  pendingChoices: null, // 场景行播完后要显示的选项
  autoplay: false,
  timer: null,
  hint: null,

  init() {
    this.mountHint();
    $("chat").addEventListener("click", () => this.advance());
    document.addEventListener("keydown", (e) => {
      if (e.code !== "Space") return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "BUTTON")) return;
      e.preventDefault();   // 空格不滚动页面
      this.advance();
    });
    this._updateHint();
  },

  mountHint() {
    if (!this.hint || !this.hint.parentNode) {
      if (this.hint) this.hint.remove();
      this.hint = document.createElement("div");
      this.hint.className = "advance-hint hidden";
      $("chat").appendChild(this.hint);
    }
    this._updateHint();
  },

  /* 开始播放一个场景（清空旧队列与定时器；交互点未到，收起输入区） */
  play(container, lines, choices) {
    this._stopTimer();
    this.mountHint();
    showFreeRow(false);
    this.container = container;
    this.queue = (lines || []).slice();
    this.pendingChoices = (choices && choices.length) ? choices : null;
    this.state = "idle";
    this.cur = null;
    this._updateHint();
    this._kick();
  },

  /* 流式到达的新行：入队，若当前空闲立即开播 */
  pushLine(speaker, text) {
    this.queue.push({ speaker: speaker, text: text });
    this._kick();
  },

  /* 流式完成：登记选项（队列播完后出选项） */
  setChoices(choices) {
    this.pendingChoices = (choices && choices.length) ? choices : null;
    this._kick();
  },

  /* 流式与最终剧本不一致时：清空容器按最终剧本重播 */
  reset(container, lines, choices) {
    container.innerHTML = "";
    this.play(container, lines, choices);
  },

  _kick() {
    if (this.state !== "idle") return;
    if (this.queue.length) {
      this._showNext();
    } else if (this.pendingChoices) {
      const ch = this.pendingChoices;
      this.pendingChoices = null;
      this._updateHint();
      renderChoiceButtons(ch);
    }
  },

  async _showNext() {
    const ln = this.queue.shift();
    const el = buildLineEl(ln.speaker, "");
    this.container.appendChild(el);
    $("chat").appendChild(this.hint);   // 提示始终保持在对话区末尾（sticky 悬浮）
    scrollBottom();
    const target = textTarget(el);
    target.classList.add("cursor");
    this.cur = { el: el, target: target, text: ln.text };
    this.state = "typing";
    await this._typewrite();
    if (!this.cur) return;              // 已被 stop()
    this._afterTyping();
  },

  _typewrite() {
    const c = this.cur;
    let typed = 0;
    return new Promise((resolve) => {
      c._resolve = resolve;
      c._iv = setInterval(() => {
        if (this.cur !== c) return;     // 已被打断
        typed += 2;
        c.target.textContent = c.text.slice(0, typed);
        scrollBottom();
        if (typed >= c.text.length) {
          clearInterval(c._iv);
          c.target.textContent = c.text;
          resolve();
        }
      }, 12);
    });
  },

  _afterTyping() {
    const c = this.cur;
    c.target.classList.remove("cursor");
    this.state = "wait";
    if (this.autoplay) this._armTimer();
    this._updateHint();
  },

  /* 自动播放：速度放慢——基础1.6s + 每字70ms，2s~5.5s 之间 */
  _armTimer() {
    this._stopTimer();
    const len = this.cur ? this.cur.text.length : 20;
    const delay = Math.min(5500, Math.max(2000, 1600 + len * 70));
    this.timer = setTimeout(() => this._next(), delay);
  },

  _stopTimer() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
  },

  /* 推进：打字中→立即补全本句；等待中→下一句 */
  advance() {
    if (this.state === "typing") {
      const c = this.cur;
      clearInterval(c._iv);
      c.target.textContent = c.text;
      c.target.classList.remove("cursor");
      if (c._resolve) { c._resolve(); c._resolve = null; }
      return;   // 补全后进入 wait，再次点击才切下一句
    }
    if (this.state === "wait") this._next();
  },

  _next() {
    this._stopTimer();
    this.cur = null;
    this.state = "idle";
    this._updateHint();
    this._kick();
  },

  setAutoplay(on) {
    this.autoplay = on;
    this._stopTimer();
    if (on && this.state === "wait") this._armTimer();
    this._updateHint();
  },

  _updateHint() {
    if (!this.hint) return;
    const active = (this.state === "wait");
    this.hint.classList.toggle("hidden", !active);
    this.hint.classList.toggle("autoplay", active && this.autoplay);
    this.hint.textContent = (active && this.autoplay)
      ? "▶▶ 自动播放中"
      : "▾ 点击或按空格继续";
    const btn = $("btn-auto");
    if (btn) {
      btn.textContent = this.autoplay ? "⏸ 自动播放" : "▶ 自动播放";
      btn.classList.toggle("active", this.autoplay);
    }
  },

  /* 结束/换剧本：停止一切 */
  stop() {
    this._stopTimer();
    if (this.cur && this.cur._iv) clearInterval(this.cur._iv);
    if (this.cur && this.cur._resolve) { this.cur._resolve(); this.cur._resolve = null; }
    this.cur = null;
    this.queue = [];
    this.pendingChoices = null;
    this.state = "idle";
    this._updateHint();
  },
};

/* 玩家动作（选择的选项/自由输入）：渲染为带头像的"你"气泡，与对话对齐 */
function appendPcAction(text, isChoice) {
  const el = buildLineEl("pc", (isChoice ? "» " : "") + text);
  $("chat").appendChild(el);
  scrollBottom();
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
function scrollBottom() { $("chat").scrollTop = $("chat").scrollHeight; }

/* ---------- 交互 ---------- */
let LAST_CHOICES = null;   // 最近一次交互点的选项（生成失败时恢复交互点用）

function setBusy(b) {
  busy = b;
  $("thinking").classList.toggle("hidden", !b);
  $("choices").querySelectorAll("button").forEach((x) => (x.disabled = b));
  $("btn-send").disabled = b;
  $("free-input").disabled = b;
  if (b) showFreeRow(false);   // 生成期间无交互点：收起输入区
}

function showFreeRow(v) {
  $("free-row").classList.toggle("hidden", !v);
}

function renderScene(view) {
  if (!view.scene) return;
  renderState(view);
  $("choices").innerHTML = "";
  Player.play($("chat"), view.scene.dialogue, view.scene.choices);
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
  LAST_CHOICES = choices;
  showFreeRow(true);   // 交互点：选项 + 自由输入同时可用
  setBusy(false);
}

async function choose(index, text) {
  if (busy) return;
  setBusy(true);
  $("choices").innerHTML = "";
  appendPcAction(text, true);   // 所选选项以"你"的气泡呈现
  const box = beginStream();
  try {
    const view = await streamTurn(SID, { choice_index: index }, box);
    afterTurn(view, box);
  } catch (e) {
    addSystem("（生成失败: " + e.message + "）");
    if (LAST_CHOICES) renderChoiceButtons(LAST_CHOICES);   // 恢复交互点
    else setBusy(false);
  }
}

async function freeAct() {
  const text = $("free-input").value.trim();
  if (!text || busy) return;
  setBusy(true);
  $("free-input").value = "";
  $("choices").innerHTML = "";
  appendPcAction(text, false);   // 自由输入同样以"你"的气泡呈现
  const box = beginStream();
  try {
    const view = await streamTurn(SID, { free_text: text }, box);
    afterTurn(view, box);
  } catch (e) {
    addSystem("（生成失败: " + e.message + "）");
    if (LAST_CHOICES) renderChoiceButtons(LAST_CHOICES);   // 恢复交互点
    else setBusy(false);
  }
}

/* ---------- 流式渲染 ---------- */
function beginStream() {
  const root = document.createElement("div");
  root.className = "stream-root";
  $("chat").appendChild(root);
  Player.container = root;   // 本回合的行渲染进流式容器
  scrollBottom();
  return { root: root, rows: [] };   // rows: 已流入播放器的对话行
}

function streamLine(box, speaker, text) {
  box.rows.push({ speaker: speaker, text: text });
  Player.pushLine(speaker, text);   // 流入逐句播放器，一句一句显示
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
    Player.stop();
    showEnding();
    return;
  }
  const final = view.scene.dialogue || [];
  const choices = view.scene.choices || [];
  // 流式行与最终对话一致则保留（选项在队列播完后出现）；
  // 不一致（重写/降级）则整体重播，保证所见即最终剧本
  if (box && linesMatch(box.rows, final)) {
    Player.setChoices(choices);
  } else {
    Player.reset(box ? box.root : $("chat"), final, choices);
  }
  if (box) box.rows = [];
  if (!choices.length) setBusy(false);   // 无选项场景兜底（正常由 renderChoiceButtons 复位）
}

/* ---------- 结局 ---------- */
async function showEnding() {
  Player.stop();
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
  Player.stop();
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
    // 回放历史时间线（历史行即时渲染；当前场景的行跳过，交给逐句播放器）
    const hist = view.history || [];
    for (let i = 0; i < hist.length; i++) {
      const h = hist[i];
      if (h.is_current) break;   // 到达当前场景首行：其后由播放器负责
      if (h.kind === "line") {
        appendLineInstant(h.speaker, h.text);
      } else {
        appendPcAction(h.text, true);
      }
    }
    renderState(view);
    $("choices").innerHTML = "";
    Player.play($("chat"), view.scene.dialogue, view.scene.choices);
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
$("btn-auto").onclick = () => Player.setAutoplay(!Player.autoplay);
$("btn-send").onclick = freeAct;
$("free-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") freeAct();
});

Player.init();
loadStories();
/* 注意:不再自动 resume()——打开网站始终先展示选故事页,
   有存档时由"继续上次的故事"卡片显式进入(同样走加载页)。 */
