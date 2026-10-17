// AI Storyboard review: no generation while editing, exact-still drafts, mocked transport.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") {
    this.tag = String(tag).toLowerCase();
    this.children = [];
    this.parentNode = null;
    this.attrs = {};
    this.dataset = {};
    this.className = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this._text = "";
    this.onclick = null;
    this.onchange = null;
    this.oninput = null;
    this.listeners = {};
    this.style = {};
  }
  get textContent() {
    if (this.children.length) return this.children.map((child) => child.textContent).join("");
    return this._text;
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  set innerHTML(value) {
    this._text = String(value);
  }
  matches(selector) {
    if (selector.startsWith("#")) return this.attrs.id === selector.slice(1);
    if (selector.startsWith(".")) return this.className.split(/\s+/).includes(selector.slice(1));
    const attr = selector.match(/^\[([^\]]+)\]$/);
    if (attr) {
      const [name, raw] = attr[1].split("=");
      const key = name.replace(/^data-/, "");
      const datasetKey = key.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      const actual = this.dataset[datasetKey] ?? this.attrs[name];
      if (raw == null) return actual != null;
      return String(actual) === raw.replace(/^["']|["']$/g, "");
    }
    return this.tag === selector;
  }
  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+/);
    if (parts.length > 1) {
      const [first, ...rest] = parts;
      return this.querySelectorAll(first).flatMap((node) => node.querySelectorAll(rest.join(" ")));
    }
    return this.children.flatMap((child) => [
      ...(child.matches(selector) ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  append(...nodes) {
    nodes.forEach((node) => {
      if (typeof node === "string") {
        const text = new Element("#text");
        text.textContent = node;
        node = text;
      }
      node.parentNode = this;
      this.children.push(node);
    });
  }
  prepend(node) {
    node.parentNode = this;
    this.children.unshift(node);
  }
  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains(node));
  }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name === "class") this.className = String(value);
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      this.dataset[key] = String(value);
    }
  }
  getAttribute(name) {
    if (name === "class") return this.className;
    return this.attrs[name] ?? null;
  }
  removeAttribute(name) {
    delete this.attrs[name];
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      delete this.dataset[key];
    }
  }
  addEventListener(name, handler) {
    this.listeners[name] = this.listeners[name] || [];
    this.listeners[name].push(handler);
  }
  dispatchEvent(event) {
    const handler = this["on" + event.type];
    if (typeof handler === "function") handler(event);
    (this.listeners[event.type] || []).forEach((fn) => fn(event));
    return true;
  }
  click() {
    if (typeof this.onclick === "function") this.onclick();
    (this.listeners.click || []).forEach((fn) => fn());
  }
  scrollIntoView() {
    this.scrolledIntoView = true;
  }
}

function el(tag, attrs = {}, children = []) {
  const node = new Element(tag);
  Object.entries(attrs).forEach(([name, value]) => {
    if (name === "className") node.className = value;
    else if (name === "text") node.textContent = value;
    else if (name === "value") node.value = value;
    else if (name === "checked") node.checked = value;
    else node.setAttribute(name, value);
  });
  children.forEach((child) => node.append(child));
  return node;
}

function stillNonce(beat, fingerprint, alternative, comment) {
  const raw = ["still", beat, fingerprint, alternative, comment, "economy"].join("\u001f");
  let hash = 2166136261;
  for (let index = 0; index < raw.length; index += 1) {
    hash ^= raw.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return "still-" + (hash >>> 0).toString(16);
}

function aiCard({
  withStill = false,
  approval = "pending",
  beat = "beat-1",
  fingerprint = "fp-1",
  version = "still-1",
  signature = "sig-1",
  job = "job-1",
  commentText = null,
} = {}) {
  const images = el("option", { value: "images", text: "Three-image comparison is not available yet" });
  images.value = "images";
  const economy = el("option", { value: "economy", text: "Descriptions, then one still" });
  economy.value = "economy";
  const mode = el("select", { "data-ai-mode": "" }, [economy, images]);
  mode.value = "economy";
  const comment = el("textarea", { "data-ai-comment": "" });
  comment.value = commentText != null ? commentText : (withStill ? "Keep this still" : "");
  const first = el("input", { type: "radio", "data-ai-alternative": "", value: "option-1" });
  first.value = "option-1";
  first.checked = true;
  const second = el("input", { type: "radio", "data-ai-alternative": "", value: "option-2" });
  second.value = "option-2";
  const generate = el("button", { type: "button", "data-ai-generate": "", text: "Generate still" });
  const video = el("button", { type: "button", "data-ai-video": "", text: "Video is not available on the GPT subscription route" });
  const figure = el("figure", { "data-ai-result": "" });
  if (withStill) {
    const image = el("img");
    image.setAttribute("src", "previews/ai-still-1.png");
    image.setAttribute("alt", "Generated illustration");
    figure.append(image, el("figcaption", { text: "Generated illustration" }));
  }
  const review = el("div", { className: "ai-review" }, [
    el("button", { type: "button", "data-ai-decision": "approved", text: "Approve this still" }),
    el("button", { type: "button", "data-ai-decision": "changes", text: "Request changes" }),
    el("button", { type: "button", "data-ai-decision": "rejected", text: "Reject" }),
  ]);
  review.hidden = !withStill;
  const card = el("article", {
    className: "ai-card",
    "data-ai-beat": beat,
    "data-ai-fingerprint": fingerprint,
    "data-ai-mode": "economy",
  }, [
    el("h3", { text: "Wide shot" }),
    el("p", { className: "ai-purpose", text: "Show the room" }),
    el("blockquote", { className: "ai-text", text: "Original scenario excerpt" }),
    el("fieldset", { className: "ai-alternatives" }, [
      el("label", {}, [first, " option-1 description"]),
      el("label", {}, [second, " option-2 description"]),
    ]),
    el("label", {}, ["Comment ", comment]),
    el("label", {}, ["Comparison ", mode]),
    generate,
    video,
    el("p", { "data-ai-progress": "" }),
    figure,
    review,
    el("details", { className: "ai-details" }, [el("summary", { text: "Details" })]),
  ]);
  if (withStill) {
    card.setAttribute("data-ai-version", version);
    card.setAttribute("data-ai-signature", signature);
    card.setAttribute("data-ai-job", job);
    card.setAttribute("data-ai-approval", approval);
  }
  return card;
}

function run({ live = false, withStill = false, approval = "pending", saved = null, rows = null, generateState = "queued", failReview = false, holdReview = false, boardCards = null } = {}) {
  const store = saved ? { ...saved } : {};
  const tasks = [];
  let nextTimer = 1;
  const world = {
    calls: [],
    selectQueue: [],
    reviewQueue: [],
    holdSelect: true,
    holdReview,
    failReview,
    selectOk: true,
    generateState,
    reloads: 0,
    state: { beats: [], jobs: [], versions: [], style: "Agreed style" },
    downloaded: "",
  };
  const main = el("main");
  const cards = boardCards || [aiCard({ withStill, approval })];
  const board = el("section", { className: "ai-board", "aria-label": "AI production" }, [
    el("h2", { text: "AI stills" }),
    el("p", { className: "ai-style", "data-ai-style": "", text: "Agreed style" }),
    ...cards,
  ]);
  const exportButton = el("button", { id: "export-review", text: "Save decisions" });
  exportButton.attrs.id = "export-review";
  const printButton = el("button", { id: "print-review", text: "Print / PDF" });
  printButton.attrs.id = "print-review";
  const nextButton = el("button", { id: "next-pending" });
  nextButton.attrs.id = "next-pending";
  const storage = el("span", { "data-storage-status": "" });
  const done = el("p", { className: "export-done" });
  const summaryText = el("p", { "data-summary": "" });
  main.append(board, exportButton, printButton, nextButton, storage, done, summaryText);
  const byId = {
    "export-review": exportButton,
    "print-review": printButton,
    "next-pending": nextButton,
  };
  const document = {
    querySelector(selector) {
      if (selector === "main") return main;
      if (selector.startsWith("#") && byId[selector.slice(1)]) return byId[selector.slice(1)];
      if (selector === ".export-done") return done;
      if (selector === "[data-storage-status]") return storage;
      if (selector === ".review-toolbar" || selector === "#pending-only" || selector === "#viewer" || selector === ".graphics-board") return null;
      return main.querySelector(selector);
    },
    querySelectorAll(selector) {
      if (selector === "[data-storage-status]") return [storage];
      if (selector === "[data-summary]") return [summaryText];
      return main.querySelectorAll(selector);
    },
    createElement(tag) {
      return new Element(tag);
    },
    addEventListener() {},
  };
  function setInterval(fn, ms) {
    const id = nextTimer;
    nextTimer += 1;
    tasks.push({ id, fn, ms, left: ms });
    return id;
  }
  function clearInterval(id) {
    const index = tasks.findIndex((task) => task.id === id);
    if (index >= 0) tasks.splice(index, 1);
  }
  function advance(ms) {
    let remaining = ms;
    let guard = 0;
    while (remaining > 0 && tasks.length && guard < 30) {
      guard += 1;
      const step = Math.min(remaining, ...tasks.map((task) => task.left));
      remaining -= step;
      for (const task of [...tasks]) task.left -= step;
      for (const task of tasks.filter((item) => item.left <= 0)) {
        if (!tasks.includes(task)) continue;
        task.left = task.ms;
        task.fn();
      }
    }
  }
  const window = {
    GETBROLLS_REVIEW: {
      type: "getbrolls-review",
      templateVersion: 2,
      project: "synthetic-ai",
      items: [],
      ai: rows || [{
        id: "ai:beat-1",
        project: "synthetic-ai",
        beat: "beat-1",
        fingerprint: "fp-1",
        selected: "option-1",
        comment: "old",
        mode: "economy",
        job: "job-old",
        version: "still-9",
        signature: "sig-9",
        state: "pending",
      }],
    },
    GETBROLLS_SAVE: live ? { aiUrl: "/__ai", header: "X-GetBrolls-Token", token: "synthetic-token" } : null,
    location: { reload() { world.reloads += 1; } },
    addEventListener() {},
    print() {},
  };
  const context = {
    window,
    document,
    localStorage: {
      getItem(name) { return Object.prototype.hasOwnProperty.call(store, name) ? store[name] : null; },
      setItem(name, value) { store[name] = value; },
    },
    MutationObserver: class { observe() {} },
    URL: {
      createObjectURL(blob) {
        world.downloaded = blob.parts ? blob.parts.join("") : String(blob);
        return "blob:fixture";
      },
      revokeObjectURL() {},
    },
    Blob: class { constructor(parts) { this.parts = parts; } },
    fetch: async (url, options = {}) => {
      const method = String(options.method || "GET").toUpperCase();
      const body = options.body ? JSON.parse(options.body) : null;
      world.calls.push({ url, method, body, headers: options.headers || {} });
      if (method === "GET") return { ok: true, json: async () => world.state };
      if (body && body.action === "select" && world.holdSelect) {
        return new Promise((resolve) => {
          world.selectQueue.push(() => resolve({
            ok: world.selectOk !== false,
            json: async () => ({ beat: { id: body.beat, comment: "SERVER", selected: "option-1", mode: "economy", fingerprint: body.expected } }),
          }));
        });
      }
      if (body && body.action === "generate") {
        return { ok: true, json: async () => ({ job: { id: "job-1", state: world.generateState, beat: body.beat, error: null } }) };
      }
      if (body && body.action === "review" && world.holdReview) {
        return new Promise((resolve) => {
          world.reviewQueue.push(() => resolve({
            ok: world.failReview !== true,
            json: async () => ({ error: world.failReview ? "not saved" : "", version: body.version, decision: body.decision }),
          }));
        });
      }
      if (body && body.action === "review") {
        return { ok: world.failReview !== true, json: async () => ({ error: world.failReview ? "not saved" : "", version: body.version, decision: body.decision }) };
      }
      return { ok: true, json: async () => ({}) };
    },
    navigator: {},
    matchMedia: () => ({ matches: true }),
    setTimeout() { return 0; },
    setInterval,
    clearInterval,
    console,
  };
  vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context);
  const card = board.querySelector(".ai-card");
  return { world, store, advance, card, board, exportButton, window, summaryText, nextButton, cards: board.querySelectorAll(".ai-card") };
}

function posted(world, action) {
  return world.calls.filter((call) => call.body && call.body.action === action);
}

async function drain() {
  for (let step = 0; step < 30; step += 1) await Promise.resolve();
}

(async () => {
  const live = run({ live: true });
  const card = live.card;
  const comment = card.querySelector("[data-ai-comment]");
  const progress = card.querySelector("[data-ai-progress]");
  const figure = card.querySelector("[data-ai-result]");
  const images = [...card.querySelectorAll("option")].find((option) => option.value === "images");
  const video = card.querySelector("[data-ai-video]");
  const generate = card.querySelector("[data-ai-generate]");
  const option1 = [...card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.value === "option-1");
  const option2 = [...card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.value === "option-2");
  assert.equal(live.world.calls.length, 0, "Opening the board must not generate or save");
  assert.equal(images.disabled, true, "Three-image comparison stays disabled");
  assert.equal(video.disabled, true, "GPT video stays disabled");
  assert.equal(generate.disabled, false);
  assert.equal(card.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");

  comment.value = "one";
  comment.dispatchEvent({ type: "input" });
  assert.equal(live.world.calls.length, 0, "Typing must not generate immediately");
  live.advance(400);
  assert.equal(posted(live.world, "generate").length, 0);
  assert.equal(posted(live.world, "select").length, 1);
  assert.equal(posted(live.world, "select")[0].body.comment, "one");
  assert.equal(Object.hasOwn(posted(live.world, "select")[0].body, "alternative"), false);
  assert.equal(posted(live.world, "select")[0].headers["X-GetBrolls-Token"], "synthetic-token");

  comment.value = "two";
  comment.dispatchEvent({ type: "input" });
  live.advance(400);
  option2.checked = true;
  option2.dispatchEvent({ type: "change" });
  assert.equal(card.getAttribute("data-ai-current"), "true");
  live.world.selectQueue[0]();
  await drain();
  assert.equal(comment.value, "two", "An older select response must not replace the newer draft");
  assert.equal(option2.checked, true);
  assert.equal(option1.checked, false);
  live.advance(400);
  const selects = posted(live.world, "select");
  assert.equal(selects.at(-1).body.alternative, "option-2");
  assert.equal(selects.at(-1).body.comment, "two");
  assert.equal(selects.at(-1).body.expected, "fp-1");
  while (live.world.selectQueue.length) live.world.selectQueue.shift()();
  await drain();
  assert.equal(comment.value, "two");
  assert.equal(option2.checked, true);

  generate.click();
  generate.click();
  const generated = posted(live.world, "generate");
  assert.equal(generated.length, 1, "A duplicate click must not launch another job");
  const nonce = stillNonce("beat-1", "fp-1", "option-2", "two");
  assert.equal(generated[0].body.nonce, nonce);
  assert.equal(generated[0].body.requestId, nonce);
  assert.equal(generated[0].body.action, "generate");
  assert.equal(generated[0].body.beat, "beat-1");
  assert.equal(generated[0].body.expected, "fp-1");
  assert.equal(generated[0].body.alternative, "option-2");
  assert.equal(generated[0].body.comment, "two");
  assert.equal(generated[0].url, "/__ai");
  await drain();
  assert.equal(progress.textContent, "queued");
  assert.equal(card.getAttribute("data-ai-approval") || "", "", "Generation must not approve the still");

  live.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      selected: "option-1",
      comment: "SERVER",
      mode: "economy",
      job: { id: "job-1", state: "complete", beat: "beat-1", error: null, result: "still-1" },
      version: { id: "still-1", path: "previews/ai-still-1.png", signature: "sig-1", approval: null, width: 640, height: 360, codec: "png" },
    }],
    jobs: [],
    versions: [],
    style: "Agreed style",
  };
  live.advance(1000);
  await drain();
  const image = figure.querySelector("img");
  assert.equal(image.getAttribute("src"), "previews/ai-still-1.png");
  assert.equal(image.getAttribute("alt"), "Generated illustration");
  assert.equal(figure.querySelector("figcaption").textContent, "Generated illustration");
  assert.equal(live.board.querySelectorAll(".ai-card").length, 1, "Status updates stay on the existing card");
  assert.equal(live.world.reloads, 0, "Polling must not reload the page");
  assert.equal(comment.value, "two");
  assert.equal(option2.checked, true);
  assert.equal(card.getAttribute("data-ai-current"), "true");
  assert.equal(card.getAttribute("data-ai-version"), "still-1");
  assert.equal(card.getAttribute("data-ai-signature"), "sig-1");
  const firstPoll = live.world.calls.find((call) => call.method === "GET");
  assert.equal(firstPoll.url, "/__ai/state");
  assert.equal(firstPoll.headers["X-GetBrolls-Token"], "synthetic-token");
  assert.equal(card.querySelector("[data-ai-diagnostics]").textContent.includes("640×360"), true);
  assert.equal(card.querySelector("[data-ai-diagnostics]").textContent.includes("Generation is not approval"), true);
  assert.equal(posted(live.world, "review").length, 0, "A finished still is not an approval");

  card.querySelector('[data-ai-decision="approved"]').click();
  await drain();
  const review = posted(live.world, "review");
  assert.equal(review.length, 1);
  assert.equal(review[0].body.version, "still-1");
  assert.equal(review[0].body.signature, "sig-1");
  assert.equal(review[0].body.decision, "approved");
  assert.equal(review[0].body.by, "Storyboard");
  assert.equal(card.querySelector("[data-ai-decision-label]").textContent, "Approved");

  comment.value = "two revised";
  comment.dispatchEvent({ type: "input" });
  live.advance(400);
  generate.click();
  assert.equal(posted(live.world, "generate").length, 2);
  assert.notEqual(posted(live.world, "generate")[1].body.nonce, nonce);
  assert.equal(posted(live.world, "generate")[1].body.nonce, stillNonce("beat-1", "fp-1", "option-2", "two revised"));
  await drain();
  live.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-changed",
      selected: "option-1",
      comment: "SERVER",
      mode: "images",
      job: { id: "job-2", state: "complete", beat: "beat-1", error: null, result: "still-2" },
      version: { id: "still-2", path: "previews/ai-still-2.png", signature: "sig-2", approval: "approved", width: 10, height: 10, codec: "png" },
    }],
    jobs: [],
    versions: [],
    style: "Agreed style",
  };
  live.advance(1000);
  await drain();
  assert.equal(figure.querySelector("img").getAttribute("src"), "previews/ai-still-1.png");
  assert.equal(card.getAttribute("data-ai-version"), "still-1");
  assert.equal(card.getAttribute("data-ai-signature"), "sig-1");
  assert.equal(card.getAttribute("data-ai-state"), "complete");
  assert.equal(progress.textContent, "complete");
  assert.equal(live.world.calls.filter((call) => call.method === "GET" && call.url === "/__ai/state").length, 2);
  assert.equal(comment.value, "two revised");
  assert.equal(option2.checked, true);
  assert.equal(card.getAttribute("data-ai-current"), "true");
  assert.equal(live.world.reloads, 0);

  live.exportButton.click();
  const saved = JSON.parse(live.world.downloaded);
  const exact = saved.ai.find((row) => row.version === "still-1");
  const older = saved.ai.find((row) => row.version === "still-9");
  assert.equal(exact.id, "ai:beat-1");
  assert.equal(exact.beat, "beat-1");
  assert.equal(exact.fingerprint, "fp-1");
  assert.equal(exact.selected, "option-2");
  assert.equal(exact.comment, "two", "A later scene instruction does not rewrite the displayed still's review comment");
  assert.equal(exact.mode, "economy");
  assert.equal(exact.job, "job-1");
  assert.equal(exact.signature, "sig-1");
  assert.equal(exact.state, "approved");
  assert.equal(exact.decision, "approved");
  assert.equal(older.version, "still-9");
  assert.equal(older.signature, "sig-9");
  assert.equal(older.state, "pending");
  assert.deepEqual(saved.items, []);
  const stored = JSON.parse(live.store["getbrolls-v2-ai:synthetic-ai"]);
  assert.equal(stored["beat-1"].version, "still-1");
  assert.equal(stored["beat-1"].signature, "sig-1");
  assert.equal(stored["beat-1"].state, "approved");

  const portable = run({ withStill: true });
  const portableCard = portable.card;
  const portableGenerate = portableCard.querySelector("[data-ai-generate]");
  assert.equal(portableGenerate.disabled, true, "A portable page cannot generate");
  assert.equal(portableCard.querySelector("[data-ai-video]").disabled, true);
  assert.equal([...portableCard.querySelectorAll("option")].find((option) => option.value === "images").disabled, true);
  portableCard.querySelector("[data-ai-comment]").value = "Offline note";
  portableCard.querySelector("[data-ai-comment]").dispatchEvent({ type: "input" });
  portable.advance(400);
  portableGenerate.click();
  assert.equal(portable.world.calls.length, 0, "Portable editing and generate clicks stay local");
  portableCard.querySelector('[data-ai-decision="rejected"]').click();
  assert.equal(portable.world.calls.length, 0);
  assert.equal(portableCard.querySelector("[data-ai-decision-label]").textContent, "Rejected");
  portable.exportButton.click();
  const offline = JSON.parse(portable.world.downloaded);
  assert.equal(offline.ai[0].version, "still-1");
  assert.equal(offline.ai[0].signature, "sig-1");
  assert.equal(offline.ai[0].state, "rejected");
  assert.equal(offline.ai[0].decision, "rejected");
  assert.equal(offline.ai[0].comment, "Offline note");
  assert.equal(offline.ai[0].id, "ai:beat-1");
  const offlineStore = JSON.parse(portable.store["getbrolls-v2-ai:synthetic-ai"]);
  assert.equal(offlineStore["beat-1"].signature, "sig-1");
  assert.equal(offlineStore["beat-1"].state, "rejected");

  const approved = run({ withStill: true, approval: "approved" });
  assert.equal(approved.card.querySelector("[data-ai-decision-label]").textContent, "Approved");
  approved.exportButton.click();
  assert.equal(JSON.parse(approved.world.downloaded).ai.find((row) => row.version === "still-1").state, "approved");

  const fromRow = run({
    withStill: true,
    rows: [{ id: "ai:beat-1", beat: "beat-1", fingerprint: "fp-1", version: "still-1", signature: "sig-1", state: "changes", mode: "economy", job: "job-1" }],
  });
  assert.equal(fromRow.card.querySelector("[data-ai-decision-label]").textContent, "Changes requested");

  const sameContext = run({
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "fp-1", version: "", signature: "", comment: "SAME CONTEXT", commentDirty: true, state: "pending" } }) },
  });
  assert.equal(sameContext.card.querySelector("[data-ai-comment]").value, "SAME CONTEXT");

  const oldContext = run({
    live: true,
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "old-context", signature: "", comment: "OLD CONTEXT", commentDirty: true, state: "pending" } }) },
  });
  assert.equal(oldContext.card.querySelector("[data-ai-comment]").value, "");
  assert.equal(posted(oldContext.world, "generate").length, 0);

  const localDecision = run({
    withStill: true,
    approval: "approved",
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "fp-1", version: "still-1", signature: "sig-1", state: "rejected", comment: "Keep this still" } }) },
  });
  assert.equal(localDecision.card.querySelector("[data-ai-decision-label]").textContent, "Rejected");
  const otherStill = run({
    withStill: true,
    approval: "approved",
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "fp-1", version: "still-2", signature: "sig-2", state: "rejected", comment: "NO" } }) },
  });
  assert.equal(otherStill.card.querySelector("[data-ai-decision-label]").textContent, "Approved");
  assert.equal(otherStill.card.querySelector("[data-ai-comment]").value, "Keep this still");

  const fast = run({ live: true, generateState: "complete" });
  fast.world.state = {
    beats: [{ id: "beat-1", fingerprint: "fp-1", job: { id: "job-1", state: "complete" }, version: { id: "still-fast", signature: "sig-fast", path: "previews/fast.png", approval: null } }],
  };
  fast.card.querySelector("[data-ai-generate]").click();
  fast.card.querySelector("[data-ai-generate]").click();
  await drain();
  assert.equal(posted(fast.world, "generate").length, 1);
  assert.ok(fast.world.calls.some((call) => call.method === "GET" && call.url === "/__ai/state"));
  assert.equal(fast.card.getAttribute("data-ai-version"), "still-fast");
  assert.equal(fast.card.querySelector("img").getAttribute("src"), "previews/fast.png");

  const quota = run({ live: true, generateState: "quota" });
  quota.card.querySelector("[data-ai-generate]").click();
  await drain();
  quota.card.querySelector("[data-ai-generate]").click();
  assert.equal(posted(quota.world, "generate").length, 1);
  assert.equal(quota.card.querySelector("[data-ai-progress]").textContent, "quota");
  assert.equal(quota.world.calls.filter((call) => call.method === "GET").length, 0);
  assert.equal(quota.card.getAttribute("data-ai-version"), null);

  const unknown = run({ live: true, generateState: "unknown" });
  unknown.card.querySelector("[data-ai-generate]").click();
  await drain();
  unknown.card.querySelector("[data-ai-generate]").click();
  assert.equal(posted(unknown.world, "generate").length, 1);
  assert.equal(unknown.card.querySelector("[data-ai-progress]").textContent, "unknown");
  assert.equal(unknown.world.calls.filter((call) => call.method === "GET").length, 0);

  const drifted = run({ live: true });
  const driftedComment = drifted.card.querySelector("[data-ai-comment]");
  driftedComment.value = "keep me";
  driftedComment.dispatchEvent({ type: "input" });
  drifted.card.querySelector("[data-ai-generate]").click();
  await drain();
  drifted.world.state = {
    beats: [{ id: "beat-1", fingerprint: "different-context", job: { id: "other-job", state: "complete" }, version: { id: "other-still", signature: "other-signature", path: "previews/other.png" } }],
  };
  drifted.advance(1000);
  await drain();
  assert.equal(drifted.card.getAttribute("data-ai-version"), null);
  assert.equal(driftedComment.value, "keep me");
  assert.equal(drifted.card.getAttribute("data-ai-stale"), "true");
  assert.equal(drifted.card.querySelector("[data-ai-generate]").disabled, true);
  assert.equal(drifted.card.querySelector('[data-ai-decision="approved"]').disabled, true);
  assert.equal(drifted.card.querySelector("[data-ai-new-result]"), null);
  assert.equal(drifted.card.querySelector("[data-ai-stale-note]").textContent.includes("unsent text were kept"), true);

  const next = run({ live: true, withStill: true });
  next.card.querySelector('[data-ai-decision="approved"]').click();
  await drain();
  assert.equal(next.card.querySelector("[data-ai-decision-label]").textContent, "Approved");
  next.card.querySelector("[data-ai-generate]").click();
  await drain();
  next.world.state = {
    beats: [{ id: "beat-1", fingerprint: "fp-1", job: { id: "job-2", state: "complete" }, version: { id: "still-2", signature: "sig-2", path: "previews/ai-still-2.png", approval: null } }],
  };
  next.advance(1000);
  await drain();
  assert.equal(next.card.getAttribute("data-ai-version"), "still-1");
  assert.equal(next.card.querySelector("img").getAttribute("src"), "previews/ai-still-1.png");
  const showNew = next.card.querySelector("[data-ai-new-result]");
  assert.equal(showNew.hidden, false);
  assert.equal(showNew.textContent, "Show the new still");
  showNew.click();
  assert.equal(next.card.getAttribute("data-ai-version"), "still-2");
  assert.equal(next.card.getAttribute("data-ai-signature"), "sig-2");
  assert.equal(next.card.querySelector("img").getAttribute("src"), "previews/ai-still-2.png");
  assert.equal(next.card.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");
  next.exportButton.click();
  const switched = JSON.parse(next.world.downloaded);
  assert.equal(switched.ai.find((row) => row.version === "still-1").state, "approved");
  assert.equal(switched.ai.find((row) => row.version === "still-1").signature, "sig-1");
  assert.equal(switched.ai.find((row) => row.version === "still-2").state, "pending");
  assert.equal(switched.ai.find((row) => row.version === "still-2").signature, "sig-2");
  const switchedStore = JSON.parse(next.store["getbrolls-v2-ai:synthetic-ai"])["beat-1"];
  assert.equal(switchedStore.version, "still-2");
  assert.equal(switchedStore.versions["still-1\u001fsig-1"].state, "approved");

  const failedSave = run({ live: true, withStill: true, failReview: true });
  const failedComment = failedSave.card.querySelector("[data-ai-comment]");
  failedComment.value = "before";
  failedSave.card.querySelector('[data-ai-decision="approved"]').click();
  failedComment.value = "after";
  failedComment.dispatchEvent({ type: "input" });
  await drain();
  assert.equal(failedSave.card.querySelector("[data-ai-decision-label]").textContent, "Approved · not saved");
  assert.equal(failedComment.value, "after");
  failedSave.exportButton.click();
  const failedExport = JSON.parse(failedSave.world.downloaded).ai.find((row) => row.version === "still-1");
  assert.equal(failedExport.state, "approved");
  assert.equal(failedExport.signature, "sig-1");
  assert.equal(failedExport.comment, "before", "The failed save keeps the comment of that decision while the newer scene input stays editable");

  const raced = run({ live: true, withStill: true, holdReview: true });
  raced.card.querySelector('[data-ai-decision="approved"]').click();
  raced.card.querySelector('[data-ai-decision="rejected"]').click();
  raced.world.reviewQueue[0]();
  await drain();
  assert.notEqual(raced.card.querySelector("[data-ai-decision-label]").textContent, "Approved");
  raced.world.failReview = true;
  raced.world.reviewQueue[1]();
  await drain();
  assert.equal(raced.card.querySelector("[data-ai-decision-label]").textContent, "Rejected · not saved");

  const choice = run({ live: true });
  const choiceBox = choice.card.querySelector("[data-ai-comment]");
  choiceBox.value = "one";
  choiceBox.dispatchEvent({ type: "input" });
  choice.advance(400);
  choiceBox.value = "two";
  choiceBox.dispatchEvent({ type: "input" });
  choice.world.selectOk = false;
  choice.world.selectQueue[0]();
  await drain();
  assert.equal(choiceBox.value, "two");
  choice.advance(400);
  while (choice.world.selectQueue.length) choice.world.selectQueue.shift()();
  await drain();
  assert.equal(choiceBox.value, "two");
  assert.equal(choice.card.querySelector("[data-ai-save]").textContent, "The scene choice was not saved.");
  assert.equal(posted(choice.world, "generate").length, 0);

  const arrived = run({ live: true, generateState: "complete" });
  assert.equal(arrived.summaryText.textContent, "0 approved · 0 reviewed · 0 pending");
  assert.equal(arrived.nextButton.disabled, true);
  arrived.world.state = {
    beats: [{ id: "beat-1", fingerprint: "fp-1", active: true, job: { id: "job-1", state: "complete" }, version: { id: "still-fast", signature: "sig-fast", path: "previews/fast.png", approval: null } }],
  };
  arrived.card.querySelector("[data-ai-generate]").click();
  await drain();
  assert.notEqual(arrived.card.getAttribute("data-ai-stale"), "true");
  assert.equal(arrived.card.getAttribute("data-ai-version"), "still-fast");
  assert.equal(arrived.summaryText.textContent, "0 approved · 0 reviewed · 1 pending");
  assert.equal(arrived.nextButton.disabled, false);
  arrived.card.querySelector('[data-ai-decision="approved"]').click();
  assert.equal(arrived.summaryText.textContent, "1 approved · 0 reviewed · 0 pending");
  await drain();
  assert.equal(arrived.summaryText.textContent, "1 approved · 0 reviewed · 0 pending");

  const firstCard = aiCard({ withStill: true });
  const textCard = aiCard({ beat: "beat-3", fingerprint: "fp-3" });
  const pendingCard = aiCard({ withStill: true, beat: "beat-2", fingerprint: "fp-2", version: "still-2", signature: "sig-2", job: "job-2" });
  const pair = run({ live: true, rows: [], boardCards: [firstCard, textCard, pendingCard] });
  assert.equal(pair.cards.length, 3);
  assert.equal(pair.summaryText.textContent, "0 approved · 0 reviewed · 2 pending");
  pair.cards[0].querySelector('[data-ai-decision="approved"]').click();
  assert.equal(pair.summaryText.textContent, "1 approved · 0 reviewed · 1 pending");
  await drain();
  assert.equal(pair.summaryText.textContent, "1 approved · 0 reviewed · 1 pending");
  assert.equal(pair.nextButton.disabled, false);
  pair.nextButton.click();
  assert.equal(pair.cards[2].getAttribute("data-ai-current"), "true");
  assert.equal(pair.cards[2].scrolledIntoView, true);
  assert.equal(pair.cards[1].scrolledIntoView, undefined);
  assert.notEqual(pair.cards[0].getAttribute("data-ai-current"), "true");

  const uncertain = run({
    withStill: true,
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "fp-1", version: "still-1", signature: "sig-1", state: "approved", save: "pending", comment: "queued note", commentDirty: true, selected: "option-2", selectedDirty: true } }) },
  });
  assert.equal(uncertain.card.querySelector("[data-ai-decision-label]").textContent, "Approved · not saved");
  assert.equal(uncertain.card.querySelector("[data-ai-comment]").value, "queued note");
  assert.equal([...uncertain.card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.value === "option-2").checked, true);
  const unconfirmed = run({
    withStill: true,
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "fp-1", version: "still-1", signature: "sig-1", state: "approved", save: "unconfirmed", comment: "queued note" } }) },
  });
  assert.equal(unconfirmed.card.querySelector("[data-ai-decision-label]").textContent, "Approved · not saved");
  const knownSaved = run({
    withStill: true,
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "fp-1", version: "still-1", signature: "sig-1", state: "approved", save: "saved", comment: "queued note" } }) },
  });
  assert.equal(knownSaved.card.querySelector("[data-ai-decision-label]").textContent, "Approved");
  const reconciled = run({
    withStill: true,
    approval: "approved",
    saved: { "getbrolls-v2-ai:synthetic-ai": JSON.stringify({ "beat-1": { fingerprint: "fp-1", version: "still-1", signature: "sig-1", state: "approved", save: "pending", comment: "queued note" } }) },
  });
  assert.equal(reconciled.card.querySelector("[data-ai-decision-label]").textContent, "Approved");
  assert.equal(reconciled.card.querySelector("[data-ai-comment]").value, "queued note");

  const history = run({ live: true, withStill: true });
  const historyComment = history.card.querySelector("[data-ai-comment]");
  historyComment.value = "decision one";
  historyComment.dispatchEvent({ type: "input" });
  const historyOption1 = [...history.card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.value === "option-1");
  const historyOption2 = [...history.card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.value === "option-2");
  history.card.querySelector('[data-ai-decision="approved"]').click();
  await drain();
  assert.equal(history.summaryText.textContent, "1 approved · 0 reviewed · 0 pending");
  historyComment.value = "later instruction";
  historyComment.dispatchEvent({ type: "input" });
  history.exportButton.click();
  assert.equal(JSON.parse(history.world.downloaded).ai.find(row => row.version === "still-1").comment, "decision one");
  historyOption2.checked = true;
  historyOption2.dispatchEvent({ type: "change" });
  history.card.querySelector("[data-ai-generate]").click();
  await drain();
  history.world.state = {
    beats: [{ id: "beat-1", fingerprint: "fp-1", active: true, job: { id: "job-2", state: "complete" }, version: { id: "still-2", signature: "sig-2", path: "previews/ai-still-2.png", approval: null } }],
  };
  history.advance(1000);
  await drain();
  history.card.querySelector("[data-ai-new-result]").click();
  assert.equal(history.card.getAttribute("data-ai-version"), "still-2");
  assert.equal(historyComment.value, "later instruction");
  assert.equal(historyOption2.checked, true);
  assert.equal(historyOption1.checked, false);
  assert.equal(history.summaryText.textContent, "0 approved · 0 reviewed · 1 pending");
  history.exportButton.click();
  const historyRows = JSON.parse(history.world.downloaded).ai;
  const historyOld = historyRows.find((row) => row.version === "still-1");
  const historyNew = historyRows.find((row) => row.version === "still-2");
  assert.equal(historyOld.state, "approved");
  assert.equal(historyOld.comment, "decision one");
  assert.equal(historyOld.selected, "option-1");
  assert.equal(historyNew.state, "pending");
  assert.equal(historyNew.comment, "later instruction");
  assert.equal(historyNew.selected, "option-2");
  const historyStore = JSON.parse(history.store["getbrolls-v2-ai:synthetic-ai"])["beat-1"];
  assert.equal(historyStore.versions["still-1\u001fsig-1"].comment, "decision one");
  assert.equal(historyStore.versions["still-1\u001fsig-1"].selected, "option-1");

  const reopened = run({
    live: true,
    rows: [],
    boardCards: [aiCard({ withStill: true, version: "still-2", signature: "sig-2", job: "job-2", commentText: "" })],
    saved: { "getbrolls-v2-ai:synthetic-ai": history.store["getbrolls-v2-ai:synthetic-ai"] },
  });
  const reopenedComment = reopened.card.querySelector("[data-ai-comment]");
  assert.equal(reopenedComment.value, "later instruction");
  assert.equal(JSON.parse(reopened.store["getbrolls-v2-ai:synthetic-ai"])["beat-1"].versions["still-1\u001fsig-1"].comment, "decision one");
  reopenedComment.value = "fresh scene";
  reopenedComment.dispatchEvent({ type: "input" });
  reopened.exportButton.click();
  const reopenedRows = JSON.parse(reopened.world.downloaded).ai;
  assert.equal(reopenedRows.find((row) => row.version === "still-1").comment, "decision one");
  assert.equal(reopenedRows.find((row) => row.version === "still-1").selected, "option-1");
  assert.equal(reopenedRows.find((row) => row.version === "still-2").comment, "fresh scene");
  assert.equal(reopenedRows.find((row) => row.version === "still-2").state, "pending");
  assert.equal(JSON.parse(reopened.store["getbrolls-v2-ai:synthetic-ai"])["beat-1"].versions["still-1\u001fsig-1"].comment, "decision one");

  const gone = run({ live: true, withStill: true });
  assert.equal(gone.summaryText.textContent, "0 approved · 0 reviewed · 1 pending");
  const goneComment = gone.card.querySelector("[data-ai-comment]");
  goneComment.value = "unsent";
  goneComment.dispatchEvent({ type: "input" });
  const goneOption = [...gone.card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.value === "option-2");
  goneOption.checked = true;
  goneOption.dispatchEvent({ type: "change" });
  gone.world.state = { beats: [], jobs: [], versions: [], style: "Agreed style" };
  gone.card.querySelector("[data-ai-generate]").click();
  await drain();
  gone.advance(1000);
  await drain();
  assert.equal(gone.card.getAttribute("data-ai-version"), "still-1");
  assert.equal(gone.card.querySelector("img").getAttribute("src"), "previews/ai-still-1.png");
  assert.equal(goneComment.value, "unsent");
  assert.equal(goneOption.checked, true);
  assert.equal(gone.card.getAttribute("data-ai-stale"), "true");
  assert.equal(gone.card.querySelector("[data-ai-generate]").disabled, true);
  assert.equal(gone.card.querySelector('[data-ai-decision="approved"]').disabled, true);
  assert.equal(gone.summaryText.textContent, "0 approved · 0 reviewed · 0 pending");
  assert.equal(gone.nextButton.disabled, true);
  gone.nextButton.click();
  assert.equal(gone.card.scrolledIntoView, undefined);

  const inactive = run({ live: true, withStill: true });
  inactive.card.querySelector('[data-ai-decision="approved"]').click();
  await drain();
  assert.equal(inactive.summaryText.textContent, "1 approved · 0 reviewed · 0 pending");
  const inactiveComment = inactive.card.querySelector("[data-ai-comment]");
  inactiveComment.value = "still mine";
  inactiveComment.dispatchEvent({ type: "input" });
  inactive.world.state = {
    beats: [{ id: "beat-1", fingerprint: "fp-1", active: false, job: { id: "job-x", state: "complete" }, version: { id: "still-x", signature: "sig-x", path: "previews/x.png", approval: "approved" } }],
  };
  inactive.card.querySelector("[data-ai-generate]").click();
  await drain();
  inactive.advance(1000);
  await drain();
  assert.equal(inactive.card.getAttribute("data-ai-version"), "still-1");
  assert.equal(inactive.card.getAttribute("data-ai-signature"), "sig-1");
  assert.equal(inactive.card.querySelector("img").getAttribute("src"), "previews/ai-still-1.png");
  assert.equal(inactiveComment.value, "still mine");
  assert.equal(inactive.card.getAttribute("data-ai-stale"), "true");
  assert.equal(inactive.card.querySelector("[data-ai-generate]").disabled, true);
  assert.equal(inactive.card.querySelector('[data-ai-decision="approved"]').disabled, true);
  assert.equal(!inactive.card.querySelector("[data-ai-new-result]") || inactive.card.querySelector("[data-ai-new-result]").hidden === true, true);
  assert.equal(inactive.summaryText.textContent, "0 approved · 0 reviewed · 0 pending");
  assert.equal(inactive.nextButton.disabled, true);

  console.log("AI storyboard edits stay local until an explicit still launch, and review keeps the displayed version");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
