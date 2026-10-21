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

function groupNonce(beat, fingerprint, ids, comment) {
  const raw = [beat, fingerprint, ...ids, comment, "3"].join("\u001f");
  let hash = 2166136261;
  for (let index = 0; index < raw.length; index += 1) {
    hash ^= raw.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return "group-" + (hash >>> 0).toString(16);
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
  alternatives = null,
} = {}) {
  const images = el("option", { value: "images", text: "Generate three stills" });
  images.value = "images";
  const economy = el("option", { value: "economy", text: "Descriptions, then one still" });
  economy.value = "economy";
  const mode = el("select", { "data-ai-mode": "" }, [economy, images]);
  mode.value = "economy";
  const comment = el("textarea", { "data-ai-comment": "" });
  comment.value = commentText != null ? commentText : (withStill ? "Keep this still" : "");
  const labels = alternatives || ["option-1", "option-2"];
  const radios = labels.map((id, index) => {
    const radio = el("input", { type: "radio", "data-ai-alternative": "", value: id });
    radio.value = id;
    radio.checked = index === 0;
    return el("label", {}, [radio, " " + id + " description"]);
  });
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
    el("fieldset", { className: "ai-alternatives" }, radios),
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

function run({ live = false, withStill = false, approval = "pending", saved = null, rows = null, generateState = "queued", failReview = false, holdReview = false, boardCards = null, stillProvider = null } = {}) {
  const store = saved ? { ...saved } : {};
  const tasks = [];
  let nextTimer = 1;
  const world = {
    calls: [],
    selectQueue: [],
    reviewQueue: [],
    uploadQueue: [],
    previewQueue: [],
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
      let body = null;
      let binary = false;
      if (options.body != null && options.body !== "") {
        if (typeof options.body === "string") body = JSON.parse(options.body);
        else {
          binary = true;
          body = { byteLength: options.body.byteLength || options.body.length || 0 };
        }
      }
      world.calls.push({ url, method, body, binary, headers: options.headers || {} });
      if (method === "GET" && String(url).includes("/reference/")) {
        if (world.holdPreview) return new Promise((resolve) => world.previewQueue.push(() => resolve({
          ok: true, blob: async () => ({ parts: ["late-preview"] }),
        })));
        return { ok: true, blob: async () => ({ parts: ["preview-bytes"] }), json: async () => ({}) };
      }
      if (method === "GET" && world.failStateRead) throw new Error("Synthetic status transport failure");
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
        if (body.outputs === 3) {
          return { ok: true, json: async () => ({ group: "group-1", jobs: world.comparisonJobs || [] }) };
        }
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
      if (method === "GET" && String(url).includes("/reference/")) {
        return { ok: true, blob: async () => ({ parts: ["preview-bytes"] }), json: async () => ({}) };
      }
      if (binary && String(url).includes("/reference")) {
        const metadata = JSON.parse(decodeURIComponent(options.headers["X-GetBrolls-Ai-Reference"]));
        if (world.failUpload || (metadata.declared_type === "video/mp4" && !metadata.interval && !/\d/.test(metadata.instructions))) {
          return { ok: false, json: async () => ({ error: "Name the video interval. The reference was not kept." }) };
        }
        const kept = (contextId) => {
          const reference = {
            context_id: contextId, kind: "image", received: true, name: metadata.name,
            instructions: metadata.instructions, target_still: metadata.still || null,
          };
          const beat = world.state.beats.find((row) => row.id === metadata.beat);
          if (beat) beat[metadata.still ? "reference" : "guidance"] = reference;
          return { ok: true, json: async () => ({ reference }) };
        };
        if (world.holdUpload) return new Promise((resolve) => world.uploadQueue.push(() => resolve(kept("ctx-late"))));
        return kept("ctx-fixture");
      }
      if (body && body.action === "apply") {
        return { ok: true, json: async () => ({ job: { id: "job-apply", state: "queued", error: null, operation: "apply" } }) };
      }
      if (body && body.action === "reference-remove") {
        const beat = world.state.beats.find((row) => row.id === body.beat);
        if (beat && beat.reference && beat.reference.context_id === body.context) beat.reference = null;
        if (beat && beat.guidance && beat.guidance.context_id === body.context) beat.guidance = null;
        return { ok: true, json: async () => ({ reference: { received: false } }) };
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
  world.state = {
    beats: cards.map((card) => {
      const comment = card.querySelector("[data-ai-comment]");
      const selected = [...card.querySelectorAll("[data-ai-alternative]")].find((radio) => radio.checked);
      return {
        id: card.getAttribute("data-ai-beat"),
        fingerprint: card.getAttribute("data-ai-fingerprint"),
        active: true,
        mode: card.getAttribute("data-ai-mode") || "economy",
        selected: selected ? (selected.value || selected.getAttribute("value") || "") : "",
        comment: comment && typeof comment.value === "string" ? comment.value : "",
      };
    }),
    jobs: [],
    versions: [],
    style: "Agreed style",
    ...(stillProvider ? { still_provider: stillProvider } : {}),
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
  assert.equal(posted(live.world, "generate").length, 0, "Opening the board must not generate");
  assert.equal(posted(live.world, "select").length, 0, "Opening the board must not save");
  assert.equal(posted(live.world, "review").length, 0, "Opening the board must not review");
  assert.equal(live.world.calls.some((call) => call.method === "GET" && call.url === "/__ai/state"), true);
  assert.equal(images.disabled, false, "Images mode is available and does not generate by itself");
  assert.equal(video.disabled, true, "GPT video stays disabled");
  assert.equal(generate.disabled, false);
  assert.equal(card.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");

  comment.value = "one";
  comment.dispatchEvent({ type: "input" });
  assert.equal(posted(live.world, "generate").length, 0, "Typing must not generate immediately");
  assert.equal(posted(live.world, "select").length, 0, "Typing must not save before the debounce");
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
  assert.equal(Object.hasOwn(generated[0].body, "outputs"), false);
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
  assert.equal(live.world.calls.filter((call) => call.method === "GET" && call.url === "/__ai/state").length, 3);
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
  assert.equal([...portableCard.querySelectorAll("option")].find((option) => option.value === "images").disabled, false);
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
  const quotaInitialReads = quota.world.calls.filter((call) => call.method === "GET").length;
  assert.equal(quotaInitialReads, 1, "A live review reads current state on opening");
  quota.card.querySelector("[data-ai-generate]").click();
  await drain();
  quota.card.querySelector("[data-ai-generate]").click();
  assert.equal(posted(quota.world, "generate").length, 1);
  assert.equal(quota.card.querySelector("[data-ai-progress]").textContent, "quota");
  assert.equal(quota.world.calls.filter((call) => call.method === "GET").length, quotaInitialReads, "Quota failure does not start extra polling");
  assert.equal(quota.card.getAttribute("data-ai-version"), null);

  const unknown = run({ live: true, generateState: "unknown" });
  const unknownInitialReads = unknown.world.calls.filter((call) => call.method === "GET").length;
  assert.equal(unknownInitialReads, 1, "A live review reads current state on opening");
  unknown.card.querySelector("[data-ai-generate]").click();
  await drain();
  unknown.card.querySelector("[data-ai-generate]").click();
  assert.equal(posted(unknown.world, "generate").length, 1);
  assert.equal(unknown.card.querySelector("[data-ai-progress]").textContent, "unknown");
  assert.equal(unknown.world.calls.filter((call) => call.method === "GET").length, unknownInitialReads, "Unknown submit does not start extra polling");

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

  const afterComparison = run({ live: true, withStill: true });
  afterComparison.card.querySelector('[data-ai-decision="approved"]').click();
  await drain();
  afterComparison.card.querySelector("[data-ai-generate]").click();
  await drain();
  afterComparison.world.state = {
    beats: [{
      id: "beat-1", fingerprint: "fp-1", mode: "economy", active: true,
      job: { id: "job-paid", state: "complete" },
      version: { id: "still-paid", signature: "sig-paid", path: "previews/paid.jpg", approval: "pending" },
      slots: [{ alternative: "option-1", version: { id: "still-1", signature: "sig-1", path: "previews/ai-still-1.png" } }],
    }],
  };
  afterComparison.advance(1000);
  await drain();
  const economyOffer = afterComparison.card.querySelector("[data-ai-new-result]");
  assert.ok(economyOffer && !economyOffer.hidden, "Historical comparison slots must not hide a later economy result");
  assert.equal(afterComparison.card.getAttribute("data-ai-version"), "still-1", "Keep the exact reviewed target until the new result is explicitly selected");
  economyOffer.click();
  assert.equal(afterComparison.card.getAttribute("data-ai-version"), "still-paid");
  assert.equal(afterComparison.card.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");

  const reopenedEconomy = run({ live: true, withStill: true, saved: next.store });
  reopenedEconomy.world.state = {
    beats: [{
      id: "beat-1", fingerprint: "fp-1", mode: "economy", active: true,
      version: { id: "still-2", signature: "sig-2", path: "previews/ai-still-2.png", approval: "pending" },
    }],
    versions: [],
  };
  await drain();
  assert.equal(reopenedEconomy.card.getAttribute("data-ai-version"), "still-2", "The explicitly chosen economy revision must survive reopening old saved HTML");

  const reopenedComparisonEdit = run({ live: true, withStill: true, saved: next.store });
  reopenedComparisonEdit.world.state = {
    beats: [{
      id: "beat-1", fingerprint: "fp-1", mode: "images", active: true, selected: "option-1",
      version: { id: "still-2", signature: "sig-2", path: "previews/ai-still-2.png", approval: "pending" },
      slots: [{ alternative: "option-1", version: { id: "still-1", signature: "sig-1", path: "previews/ai-still-1.png" } }],
    }],
    versions: [],
  };
  await drain();
  assert.equal(reopenedComparisonEdit.card.getAttribute("data-ai-version"), "still-2", "A chosen Apply result is retained even though it is separate from the three original slots");

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

  const comparison = run({
    live: true,
    boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })],
  });
  const comparisonCard = comparison.card;
  const comparisonComment = comparisonCard.querySelector("[data-ai-comment]");
  const comparisonMode = comparisonCard.querySelector("select");
  assert.equal([...comparisonCard.querySelectorAll("option")].find((option) => option.value === "images").disabled, false);
  assert.equal(comparisonCard.querySelector("[data-ai-video]").disabled, true);
  comparisonComment.value = "keep me";
  comparisonComment.dispatchEvent({ type: "input" });
  comparisonMode.value = "images";
  comparisonMode.dispatchEvent({ type: "change" });
  assert.equal(comparisonCard.querySelector("[data-ai-generate]").textContent, "Generate three stills");
  assert.equal(posted(comparison.world, "generate").length, 0, "Switching mode or typing must not generate");
  comparison.advance(400);
  while (comparison.world.selectQueue.length) comparison.world.selectQueue.shift()();
  await drain();
  assert.equal(posted(comparison.world, "select").at(-1).body.mode, "images");
  assert.equal(posted(comparison.world, "select").at(-1).body.comment, "keep me");
  assert.equal(posted(comparison.world, "generate").length, 0);
  comparison.world.comparisonJobs = [
    { id: "job-a", alternative: "option-1", state: "complete" },
    { id: "job-b", alternative: "option-2", state: "failed", error: "provider failed" },
    { id: "job-c", alternative: "option-3", state: "queued" },
  ];
  comparisonCard.querySelector("[data-ai-generate]").click();
  comparisonCard.querySelector("[data-ai-generate]").click();
  const comparisonGenerate = posted(comparison.world, "generate");
  assert.equal(comparisonGenerate.length, 1, "A duplicate three-still click must not launch another group");
  assert.equal(comparisonGenerate[0].body.outputs, 3);
  assert.equal(Object.hasOwn(comparisonGenerate[0].body, "alternative"), false);
  assert.equal(comparisonGenerate[0].body.comment, "keep me");
  assert.equal(comparisonGenerate[0].body.nonce, groupNonce("beat-1", "fp-1", ["option-1", "option-2", "option-3"], "keep me"));
  await drain();
  assert.equal(comparisonCard.getAttribute("data-ai-state"), "queued");
  assert.equal(posted(comparison.world, "review").length, 0, "Launching three stills is not approval");
  comparison.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      mode: "images",
      selected: "option-1",
      comment: "SERVER",
      job: { id: "job-a", state: "complete", alternative: "option-1" },
      version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "approved" },
      slots: [
        { alternative: "option-1", comment: "keep me", job: { id: "job-a", state: "complete", error: null }, version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: null } },
        { alternative: "option-2", job: { id: "job-b", state: "failed", error: "provider failed" }, version: null },
        { alternative: "option-3", job: { id: "job-c", state: "queued", error: null }, version: null },
      ],
    }],
  };
  comparison.advance(1000);
  await drain();
  assert.equal(comparisonComment.value, "keep me");
  assert.equal(comparisonCard.querySelectorAll(".ai-slot").length, 3);
  assert.equal(comparisonCard.querySelector(".ai-slot img").getAttribute("src"), "previews/a.png");
  assert.equal(comparisonCard.querySelector(".ai-slot img").getAttribute("alt"), "Generated illustration");
  assert.equal(comparisonCard.querySelector(".ai-slot").getAttribute("data-ai-approval"), "pending");
  assert.equal(comparisonCard.getAttribute("data-ai-state"), "queued");
  assert.equal(comparisonCard.querySelector("[data-ai-progress]").textContent.includes("provider failed"), true);
  assert.equal(comparisonCard.querySelector("[data-ai-progress]").textContent.includes("queued"), true);
  assert.equal(comparisonCard.getAttribute("data-ai-version") || "", "");
  const choose = [...comparisonCard.querySelectorAll("[data-ai-choose]")].find((button) => button.getAttribute("data-ai-choose") === "option-1");
  const generatesBefore = posted(comparison.world, "generate").length;
  choose.click();
  assert.equal(comparisonComment.value, "keep me", "Choosing a generated slot retains its frozen scene comment");
  assert.equal(posted(comparison.world, "generate").length, generatesBefore);
  assert.equal(posted(comparison.world, "review").length, 0);
  assert.equal(comparisonCard.getAttribute("data-ai-version"), "still-a");
  assert.equal(comparisonCard.getAttribute("data-ai-signature"), "sig-a");
  assert.equal(comparisonCard.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");
  comparison.advance(400);
  while (comparison.world.selectQueue.length) comparison.world.selectQueue.shift()();
  await drain();
  const chosen = posted(comparison.world, "select").at(-1);
  assert.equal(chosen.body.alternative, "option-1");
  assert.equal(Object.hasOwn(chosen.body, "outputs"), false);
  comparisonCard.querySelector('[data-ai-decision="approved"]').click();
  await drain();
  assert.equal(posted(comparison.world, "review").length, 1);
  assert.equal(posted(comparison.world, "review")[0].body.version, "still-a");
  assert.equal(posted(comparison.world, "review")[0].body.signature, "sig-a");
  comparisonComment.value = "keep me still";
  comparisonComment.dispatchEvent({ type: "input" });
  comparison.advance(1000);
  await drain();
  assert.equal(comparisonComment.value, "keep me still");
  assert.equal(comparisonCard.getAttribute("data-ai-version"), "still-a");
  assert.equal(comparisonCard.getAttribute("data-ai-signature"), "sig-a");

  const finished = run({
    live: true,
    boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })],
  });
  await drain();
  const finishedCard = finished.card;
  const finishedComment = finishedCard.querySelector("[data-ai-comment]");
  const finishedMode = finishedCard.querySelector("select");
  finishedComment.value = "kept";
  finishedComment.dispatchEvent({ type: "input" });
  finishedMode.value = "images";
  finishedMode.dispatchEvent({ type: "change" });
  finished.advance(400);
  while (finished.world.selectQueue.length) finished.world.selectQueue.shift()();
  await drain();
  finished.world.comparisonJobs = [
    { id: "job-a", alternative: "option-1", state: "complete" },
    { id: "job-b", alternative: "option-2", state: "complete" },
    { id: "job-c", alternative: "option-3", state: "complete" },
  ];
  finished.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "images",
      selected: "option-1",
      comment: "SERVER",
      job: { id: "job-a", state: "complete", alternative: "option-1" },
      version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "pending" },
      slots: [
        { alternative: "option-1", job: { id: "job-a", state: "complete" }, version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "pending" } },
        { alternative: "option-2", job: { id: "job-b", state: "complete" }, version: { id: "still-b", signature: "sig-b", path: "previews/b.png", approval: "pending" } },
        { alternative: "option-3", job: { id: "job-c", state: "complete" }, version: { id: "still-c", signature: "sig-c", path: "previews/c.png", approval: "pending" } },
      ],
    }],
  };
  finishedCard.querySelector("[data-ai-generate]").click();
  await drain();
  assert.equal(posted(finished.world, "generate").length, 1);
  assert.equal(finishedCard.querySelectorAll(".ai-slot").length, 3);
  assert.equal(finishedCard.querySelectorAll(".ai-slot img").length, 3);
  assert.equal(finishedCard.querySelector(".ai-slot img").getAttribute("alt"), "Generated illustration");
  assert.equal(finishedComment.value, "kept");
  assert.equal(finishedCard.getAttribute("data-ai-version") || "", "");

  const reopen = run({
    live: true,
    boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })],
  });
  reopen.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "images",
      selected: "option-1",
      comment: "shared scene",
      job: { id: "job-a", state: "complete", alternative: "option-1" },
      version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "approved" },
      slots: [
        { alternative: "option-1", job: { id: "job-a", state: "complete" }, version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "approved" } },
        { alternative: "option-2", job: { id: "job-b", state: "complete" }, version: { id: "still-b", signature: "sig-b", path: "previews/b.png", approval: "pending" } },
        { alternative: "option-3", job: { id: "job-c", state: "failed", error: "provider failed" }, version: null },
      ],
    }],
  };
  await drain();
  const reopenCard = reopen.card;
  const reopenComment = reopenCard.querySelector("[data-ai-comment]");
  assert.equal(posted(reopen.world, "generate").length, 0, "Reopening retained results must not generate");
  assert.equal(reopenCard.querySelector("select").value, "images");
  assert.equal(reopenCard.querySelector("[data-ai-generate]").textContent, "Generate three stills");
  assert.equal(reopenCard.querySelectorAll(".ai-slot").length, 3);
  assert.equal(reopenCard.querySelectorAll(".ai-slot img").length, 2);
  assert.equal(reopenCard.getAttribute("data-ai-version"), "still-a");
  assert.equal(reopenCard.getAttribute("data-ai-signature"), "sig-a");
  assert.equal(reopenCard.getAttribute("data-ai-approval"), "approved");
  assert.equal(reopenCard.querySelector("[data-ai-decision-label]").textContent, "Approved");
  assert.equal(reopen.summaryText.textContent, "1 approved · 0 reviewed · 0 pending");
  assert.equal(reopen.nextButton.disabled, true);
  assert.equal(reopenComment.value, "shared scene");
  assert.equal(reopenCard.querySelector('[data-ai-slot="option-1"]').getAttribute("data-ai-approval"), "approved");
  assert.equal(reopenCard.querySelector('[data-ai-slot="option-2"]').getAttribute("data-ai-approval"), "pending");
  const reopenChoose = (alternative) => [...reopenCard.querySelectorAll("[data-ai-choose]")].find((button) => button.getAttribute("data-ai-choose") === alternative);
  reopenChoose("option-1").click();
  assert.equal(posted(reopen.world, "review").length, 0);
  assert.equal(posted(reopen.world, "generate").length, 0);
  assert.equal(reopenCard.querySelector("[data-ai-decision-label]").textContent, "Approved");
  assert.equal(reopenCard.getAttribute("data-ai-version"), "still-a");
  reopenComment.value = "only still a";
  reopenComment.dispatchEvent({ type: "input" });
  reopenChoose("option-2").click();
  assert.equal(posted(reopen.world, "review").length, 0);
  assert.equal(posted(reopen.world, "generate").length, 0);
  assert.equal(reopenCard.getAttribute("data-ai-version"), "still-b");
  assert.equal(reopenCard.getAttribute("data-ai-approval"), "pending");
  assert.equal(reopenCard.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");
  assert.equal(reopenComment.value, "shared scene");
  assert.equal(reopen.summaryText.textContent, "0 approved · 0 reviewed · 1 pending");
  reopenChoose("option-1").click();
  assert.equal(reopenCard.getAttribute("data-ai-version"), "still-a");
  assert.equal(reopenCard.getAttribute("data-ai-approval"), "approved");
  assert.equal(reopenCard.querySelector("[data-ai-decision-label]").textContent, "Approved");
  assert.equal(reopenComment.value, "only still a");
  assert.equal(reopen.summaryText.textContent, "1 approved · 0 reviewed · 0 pending");
  assert.equal(posted(reopen.world, "review").length, 0);

  const heldState = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "images",
      selected: "option-1",
      comment: "shared",
      job: { id: "job-a", state: "complete", alternative: "option-1" },
      version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "approved" },
      slots: [
        { alternative: "option-1", comment: "a note", job: { id: "job-a", state: "complete" }, version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "approved" } },
        { alternative: "option-2", comment: "b only", job: { id: "job-b", state: "complete" }, version: { id: "still-b", signature: "sig-b", path: "previews/b.png", approval: "pending" } },
        { alternative: "option-3", comment: "shared", job: { id: "job-c", state: "failed", error: "provider failed" }, version: null },
      ],
    }],
  };
  const held = run({
    live: true,
    boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })],
  });
  held.world.state = heldState;
  await drain();
  const heldChoose = [...held.card.querySelectorAll("[data-ai-choose]")].find((button) => button.getAttribute("data-ai-choose") === "option-2");
  heldChoose.click();
  assert.equal(held.card.getAttribute("data-ai-version"), "still-b");
  assert.equal(held.card.getAttribute("data-ai-approval"), "pending");
  assert.equal(held.card.querySelector("[data-ai-comment]").value, "b only");
  assert.equal(posted(held.world, "select").length, 0, "The slot choice stays local until the selection debounce");
  assert.equal(posted(held.world, "generate").length, 0);
  const heldAgain = run({
    live: true,
    saved: held.store,
    boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })],
  });
  heldAgain.world.state = heldState;
  await drain();
  assert.equal(heldAgain.card.getAttribute("data-ai-version"), "still-b");
  assert.equal(heldAgain.card.getAttribute("data-ai-signature"), "sig-b");
  assert.equal(heldAgain.card.getAttribute("data-ai-approval"), "pending");
  assert.equal(heldAgain.card.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");
  assert.equal(heldAgain.card.querySelector("[data-ai-comment]").value, "b only");
  assert.equal(heldAgain.card.querySelector("[data-ai-result] img").getAttribute("src"), "previews/b.png");
  assert.equal(heldAgain.card.querySelector('[data-ai-slot="option-1"]').getAttribute("data-ai-approval"), "approved");
  assert.equal(heldAgain.card.querySelector('[data-ai-slot="option-2"]').getAttribute("data-ai-approval"), "pending");
  assert.equal(heldAgain.card.querySelector("[data-ai-slot-note]").textContent, "");
  assert.equal(posted(heldAgain.world, "generate").length, 0);
  assert.equal(posted(heldAgain.world, "review").length, 0);
  assert.equal(posted(heldAgain.world, "select").length, 0);
  const heldRendered = run({
    live: true,
    saved: held.store,
    boardCards: [aiCard({
      withStill: true,
      approval: "approved",
      version: "still-a",
      signature: "sig-a",
      commentText: "a note",
      alternatives: ["option-1", "option-2", "option-3"],
    })],
  });
  heldRendered.world.state = heldState;
  await drain();
  assert.equal(heldRendered.card.getAttribute("data-ai-version"), "still-b");
  assert.equal(heldRendered.card.getAttribute("data-ai-signature"), "sig-b");
  assert.equal(heldRendered.card.getAttribute("data-ai-approval"), "pending");
  assert.equal(heldRendered.card.querySelector("[data-ai-comment]").value, "b only");
  assert.equal(posted(heldRendered.world, "generate").length, 0);
  const heldMissing = run({
    live: true,
    saved: held.store,
    boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })],
  });
  heldMissing.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "images",
      selected: "option-1",
      comment: "shared",
      job: { id: "job-a", state: "complete", alternative: "option-1" },
      version: { id: "still-a", signature: "sig-a", path: "previews/a.png", approval: "approved" },
      slots: [
        heldState.beats[0].slots[0],
        { alternative: "option-2", comment: "b only", job: { id: "job-b", state: "complete" }, version: { id: "still-b", signature: "sig-stale", path: "previews/b.png", approval: "approved" } },
        heldState.beats[0].slots[2],
      ],
    }],
  };
  await drain();
  assert.equal(heldMissing.card.getAttribute("data-ai-version"), null);
  assert.notEqual(heldMissing.card.getAttribute("data-ai-approval"), "approved");
  assert.notEqual(heldMissing.card.querySelector("[data-ai-decision-label]").textContent, "Approved");
  assert.equal(heldMissing.card.querySelector("[data-ai-slot-note]").textContent, "The chosen still is missing from the current comparison.");
  assert.equal(posted(heldMissing.world, "generate").length, 0);
  const heldForeign = run({
    live: true,
    saved: {
      "getbrolls-v2-ai:synthetic-ai": JSON.stringify({
        "beat-1": {
          fingerprint: "old-context",
          version: "still-b",
          signature: "sig-b",
          state: "pending",
          selected: "option-2",
          selectedDirty: true,
          comment: "b only",
        },
      }),
    },
    boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })],
  });
  heldForeign.world.state = heldState;
  await drain();
  assert.equal(heldForeign.card.getAttribute("data-ai-version"), "still-a");
  assert.equal(heldForeign.card.getAttribute("data-ai-approval"), "approved");
  assert.equal(heldForeign.card.querySelector("[data-ai-comment]").value, "shared");
  assert.equal(heldForeign.card.querySelector("[data-ai-slot-note]"), null);
  assert.equal(posted(heldForeign.world, "generate").length, 0);

  const narration = run({
    live: true,
    boardCards: [aiCard()],
  });
  narration.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "economy",
      selected: "option-1",
      comment: "",
      job: { id: "job-still", state: "queued", kind: "image" },
      video_ready: false,
      timing: {
        resolved: false,
        reasons: ["uncertain_match"],
        candidates: [
          { id: "c0", text: "first spoken span", start_s: 0, end_s: 2 },
          { id: "c1", text: "second spoken span", start_s: 4, end_s: 6 },
        ],
        ambiguous: true,
        analysis_id: "na-1",
      },
    }],
    versions: [],
  };
  await drain();
  const narrationCard = narration.card;
  assert.equal(posted(narration.world, "video").length, 0, "Opening must not launch video");
  assert.equal(posted(narration.world, "timing").length, 0, "Opening must not match narration");
  assert.equal(posted(narration.world, "resolve").length, 0, "Opening must not resolve narration");
  assert.equal(posted(narration.world, "generate").length, 0);
  assert.equal(posted(narration.world, "review").length, 0);
  assert.equal(narrationCard.querySelector("[data-ai-video]").disabled, true);
  narrationCard.querySelector("[data-ai-video]").click();
  assert.equal(posted(narration.world, "video").length, 0, "A disabled video button must not post");
  const candidateChoice = narrationCard.querySelector('[data-ai-candidate-choice="c1"]');
  assert.equal(candidateChoice.textContent.includes("c1"), true);
  assert.equal(candidateChoice.textContent.includes("4"), true);
  assert.equal(candidateChoice.textContent.includes("6"), true);
  assert.equal(candidateChoice.textContent.includes("second spoken span"), true);
  assert.equal(narrationCard.querySelector("[data-ai-timing]").textContent.includes("second spoken span"), true);
  assert.equal(narrationCard.querySelector("[data-ai-timing]").textContent.includes("4"), true);
  candidateChoice.click();
  assert.equal(posted(narration.world, "resolve").length, 0, "Choosing a candidate must not resolve it");
  assert.equal(narrationCard.querySelector("[data-ai-candidate]").value, "c1");
  narrationCard.querySelector("[data-ai-timing-resolve]").click();
  assert.equal(posted(narration.world, "resolve").length, 0, "Resolve waits for an explicit statement");
  narrationCard.querySelector("[data-ai-analysis]").value = "na-1";
  narrationCard.querySelector("[data-ai-statement]").value = "Use the second spoken span.";
  narrationCard.querySelector("[data-ai-timing-resolve]").click();
  await drain();
  assert.equal(posted(narration.world, "resolve").length, 1);
  assert.equal(posted(narration.world, "resolve")[0].body.candidate, "c1");
  assert.equal(posted(narration.world, "resolve")[0].body.statement, "Use the second spoken span.");
  assert.equal(posted(narration.world, "generate").length, 0);
  narrationCard.querySelector("[data-ai-timing-match]").click();
  await drain();
  assert.equal(posted(narration.world, "timing").length, 1);
  assert.equal(posted(narration.world, "timing")[0].body.analysis, "na-1");
  narration.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "economy",
      selected: "option-1",
      comment: "",
      job: { id: "job-still", state: "complete", kind: "image" },
      video_ready: true,
      video_job: { id: "job-video", state: "running", kind: "video" },
      timing: {
        resolved: true,
        start_s: 0,
        end_s: 8,
        analysis_id: "na-1",
        still: "still-v",
        preview: "previews/ai-vo-beat-1-abcdef.wav",
        candidates: ["c0", "c1"],
      },
      video: {
        id: "clip-1",
        signature: "sig-clip",
        path: "clips/ai-clip-1.mp4",
        approval: "pending",
        kind: "video",
        width: 854,
        height: 480,
        duration_s: 2,
        fps: 24,
        audio: true,
        coverage: "short",
        native_full_hd: false,
        resolution: "480p",
      },
    }],
    versions: [{ id: "still-v", signature: "sig-v", approval: "approved", kind: "image", path: "previews/still-v.png" }],
  };
  narration.advance(1000);
  await drain();
  assert.equal(narrationCard.getAttribute("data-ai-state"), "complete");
  assert.equal(narrationCard.getAttribute("data-ai-video-state"), "running");
  assert.equal(narrationCard.getAttribute("data-ai-video-ready"), "true");
  assert.equal(narrationCard.querySelector("[data-ai-video]").disabled, false);
  assert.equal(narrationCard.querySelector("[data-ai-comment]").value, "");
  const preview = narrationCard.querySelector("[data-ai-vo]");
  assert.equal(preview.getAttribute("src"), "previews/ai-vo-beat-1-abcdef.wav");
  assert.equal(preview.autoplay, false);
  assert.equal(preview.getAttribute("preload"), "metadata");
  const clipMedia = narrationCard.querySelector("[data-ai-video-review] video");
  assert.equal(clipMedia.autoplay, false);
  assert.equal(clipMedia.getAttribute("preload"), "metadata");
  assert.match(narrationCard.querySelector("[data-ai-video-meta]").textContent, /24 fps/);
  assert.equal(narrationCard.querySelector("[data-ai-video-box] [data-ai-video-model]"), null);
  assert.equal(narrationCard.querySelector("[data-ai-video-tool]").value, "");
  narrationCard.querySelector("[data-ai-video]").click();
  assert.equal(posted(narration.world, "video").length, 0, "Video waits for recorded project setup");
  assert.match(narrationCard.querySelector("[data-ai-video-note]").textContent, /unverified|No model was guessed|not recorded/i);
  narration.world.state.native_video = {
    route: "grok-subscription",
    model: "grok-video",
    tool: "reference_to_video",
    capability: "unverified",
    message: "Native Grok video is unverified for this installation. Generate video freezes this model and tool, then fails closed.",
  };
  narration.advance(1000);
  await drain();
  assert.equal(narrationCard.querySelector("[data-ai-video-model]").value, "");
  narrationCard.querySelector("[data-ai-video]").click();
  await drain();
  assert.equal(posted(narration.world, "video").length, 1);
  const videoBody = posted(narration.world, "video")[0].body;
  assert.equal(videoBody.version, "still-v");
  assert.equal(videoBody.signature, "sig-v");
  assert.equal(videoBody.model, "grok-video");
  assert.equal(videoBody.tool, "reference_to_video");
  assert.equal(videoBody.resolution, "480p");
  assert.equal(videoBody.speech, false);
  assert.equal(videoBody.music, false);
  assert.equal(videoBody.atmosphere, false);
  assert.equal(videoBody.effects, false);
  narration.world.state.beats[0].timing.identity = "replacement-recording-same-seconds";
  narration.world.state.beats[0].video.context_current = false;
  narration.advance(1000);
  await drain();
  assert.match(narrationCard.querySelector("[data-ai-video-meta]").textContent, /not verified against the current narration/);
  narrationCard.querySelector("[data-ai-video]").click();
  await drain();
  assert.equal(posted(narration.world, "video").length, 2);
  assert.notEqual(posted(narration.world, "video")[1].body.requestId, videoBody.requestId,
    "Replacing recording/analysis identity needs a new launch even when seconds match");
  assert.equal(posted(narration.world, "generate").length, 0);
  assert.equal(posted(narration.world, "review").length, 0);
  const videoNote = narrationCard.querySelector("[data-ai-video-comment]");
  videoNote.value = "Hold the last frame";
  narrationCard.querySelector('[data-ai-video-decision="approved"]').click();
  await drain();
  assert.equal(posted(narration.world, "review").length, 1);
  assert.equal(posted(narration.world, "review")[0].body.version, "clip-1");
  assert.equal(posted(narration.world, "review")[0].body.signature, "sig-clip");
  assert.equal(posted(narration.world, "review")[0].body.comment, "Hold the last frame");
  assert.equal(narrationCard.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");
  assert.equal(narrationCard.querySelector("[data-ai-video-decision-label]").textContent, "Approved");
  assert.equal(narrationCard.querySelector("[data-ai-comment]").value, "");
  assert.equal(videoNote.value, "Hold the last frame");
  assert.equal(narrationCard.getAttribute("data-ai-approval") || "", "");
  videoNote.value = "Do not send this yet";
  videoNote.dispatchEvent({ type: "input" });
  narration.world.state = {
    native_video: narration.world.state.native_video,
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "economy",
      selected: "option-1",
      comment: "",
      job: { id: "job-still", state: "complete", kind: "image" },
      video_ready: true,
      video_job: { id: "job-video", state: "running", kind: "video" },
      timing: {
        resolved: true,
        start_s: 0,
        end_s: 8,
        analysis_id: "na-1",
        still: "still-v",
        preview: "previews/ai-vo-beat-1-abcdef.wav",
      },
      video: {
        id: "clip-2",
        signature: "sig-clip-2",
        path: "clips/ai-clip-2.mp4",
        approval: "changes",
        comment: "Server note for the other clip",
        kind: "video",
        width: 854,
        height: 480,
        duration_s: 2,
        audio: false,
        coverage: "short",
        native_full_hd: false,
        resolution: "480p",
      },
    }],
    versions: [{ id: "still-v", signature: "sig-v", approval: "approved", kind: "image", path: "previews/still-v.png" }],
  };
  narration.advance(1000);
  await drain();
  assert.equal(narrationCard.querySelector("[data-ai-video-comment]").value, "Server note for the other clip");
  assert.equal(narrationCard.querySelector("[data-ai-video-decision-label]").textContent, "Changes requested");
  assert.equal(narrationCard.querySelector("[data-ai-comment]").value, "");
  assert.equal(narrationCard.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");
  const readsBeforeClipReturn = narration.world.calls.filter((row) => !row.body).length;
  narration.world.state.beats[0].video = {
    id: "clip-1",
    signature: "sig-clip",
    path: "clips/ai-clip-1.mp4",
    approval: "pending",
    comment: "",
    kind: "video",
    width: 854,
    height: 480,
    duration_s: 2,
    audio: true,
    coverage: "short",
    native_full_hd: false,
    resolution: "480p",
  };
  narration.advance(1000);
  await drain();
  assert.ok(narration.world.calls.filter((row) => !row.body).length > readsBeforeClipReturn, "The new retained clip state must actually be fetched");
  assert.equal(narrationCard.querySelector("[data-ai-video-comment]").value, "Do not send this yet");
  assert.equal(narrationCard.querySelector("[data-ai-comment]").value, "");
  assert.equal(narrationCard.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");
  const videoReopened = run({
    live: true,
    saved: { ...narration.store },
    boardCards: [aiCard()],
  });
  videoReopened.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "economy",
      selected: "option-1",
      comment: "server still",
      video_ready: false,
      timing: { resolved: true, start_s: 0, end_s: 8, still: "still-v" },
      video: {
        id: "clip-1",
        signature: "sig-clip",
        path: "clips/ai-clip-1.mp4",
        approval: "pending",
        comment: "",
        kind: "video",
        width: 854,
        height: 480,
        duration_s: 2,
        audio: true,
        coverage: "short",
        native_full_hd: false,
        resolution: "480p",
      },
    }],
    versions: [],
  };
  await drain();
  assert.equal(videoReopened.card.querySelector("[data-ai-video-comment]").value, "Do not send this yet");
  assert.equal(videoReopened.card.querySelector("[data-ai-comment]").value, "server still");
  assert.equal(videoReopened.card.querySelector("[data-ai-decision-label]").textContent, "Awaiting decision");

  const portableStill = run({});
  assert.equal(portableStill.world.calls.length, 0, "A static portable review does not fetch");

  function applyCard(withStill = true) {
    const card = aiCard({ withStill, commentText: "No lettering" });
    const instruction = el("textarea", { "data-ai-instruction": "" });
    const file = el("input", { type: "file", "data-ai-file": "" });
    file.files = [];
    const role = el("select", { "data-ai-role": "" }, [el("option", { value: "appearance", text: "Appearance" })]);
    role.value = "appearance";
    const scope = el("select", { "data-ai-scope": "" }, [
      el("option", { value: "beat", text: "This beat" }),
      el("option", { value: "shared", text: "Shared style" }),
    ]);
    scope.value = "beat";
    const start = el("input", { "data-ai-interval-start": "" });
    const end = el("input", { "data-ai-interval-end": "" });
    const scopeText = el("textarea", { "data-ai-scope-instruction": "" });
    const upload = el("button", { type: "button", "data-ai-upload": "", text: "Keep reference" });
    const remove = el("button", { type: "button", "data-ai-remove-reference": "", text: "Remove reference" });
    const apply = el("button", { type: "button", "data-ai-apply": "", text: "Apply" });
    const preview = el("img", { "data-ai-reference-preview": "" });
    preview.hidden = true;
    card.append(
      instruction,
      file,
      role,
      start,
      end,
      scope,
      scopeText,
      upload,
      remove,
      apply,
      el("p", { "data-ai-file-note": "" }),
      el("p", { "data-ai-reference-note": "" }),
      el("p", { "data-ai-apply-note": "" }),
      preview,
    );
    return card;
  }
  const portableApply = run({ boardCards: [applyCard()] });
  const portableFile = portableApply.card.querySelector("[data-ai-file]");
  portableFile.files = [{ name: "ref.png", type: "image/png", bytes: Uint8Array.from([1, 2, 3]) }];
  portableFile.dispatchEvent({ type: "change" });
  portableApply.card.querySelector("[data-ai-apply]").click();
  assert.equal(portableApply.world.calls.length, 0, "A portable selection and Apply stay unsent");
  assert.equal(portableApply.card.querySelector("[data-ai-file-note]").textContent, "Selected, not sent.");
  assert.equal(portableApply.card.querySelector("[data-ai-apply-note]").textContent, "Selected, not sent.");

  const liveApply = run({ live: true, boardCards: [applyCard()] });
  const liveCard = liveApply.card;
  const liveInstruction = liveCard.querySelector("[data-ai-instruction]");
  const liveComment = liveCard.querySelector("[data-ai-comment]");
  const liveFile = liveCard.querySelector("[data-ai-file]");
  liveInstruction.value = "Keep the reservoir";
  liveInstruction.dispatchEvent({ type: "input" });
  liveFile.files = [{ name: "ref.png", type: "image/png", bytes: Uint8Array.from([9, 8, 7]) }];
  liveFile.dispatchEvent({ type: "change" });
  assert.equal(liveApply.world.calls.some((call) => call.method === "POST"), false, "Choosing a file does not upload");
  liveCard.querySelector("[data-ai-generate]").click();
  await drain();
  assert.equal(posted(liveApply.world, "generate").length, 0, "Generate must not silently omit a selected unsent reference");
  liveApply.world.state = {
    beats: [{
      id: "beat-1",
      fingerprint: "fp-1",
      active: true,
      mode: "economy",
      selected: "option-1",
      comment: "No lettering",
      job: { id: "job-1", state: "complete" },
      version: { id: "still-1", signature: "sig-1", path: "previews/ai-still-1.png", approval: "approved" },
      reference: { context_id: "ctx-server", name: "ref.png", role: "appearance", kind: "image", received: true },
    }],
  };
  await drain();
  assert.equal(liveInstruction.value, "Keep the reservoir");
  assert.equal(liveComment.value, "No lettering");
  assert.equal(liveCard.querySelector("[data-ai-file-note]").textContent, "Keep the selected reference before generating.");
  const videoFile = liveCard.querySelector("[data-ai-file]");
  videoFile.files = [{ name: "later.mp4", type: "video/mp4", bytes: Uint8Array.from([1]) }];
  videoFile.dispatchEvent({ type: "change" });
  liveCard.querySelector("[data-ai-upload]").click();
  await drain();
  assert.equal(posted(liveApply.world, "apply").length, 0, "A video without an interval cannot start production");
  liveFile.files = [{ name: "ref.png", type: "image/png", bytes: Uint8Array.from([9, 8, 7]) }];
  liveFile.dispatchEvent({ type: "change" });
  liveCard.querySelector("[data-ai-apply]").click();
  await drain();
  const uploads = liveApply.world.calls.filter((call) => call.binary);
  assert.equal(uploads.length, 2);
  assert.equal(uploads[1].body.byteLength, 3);
  assert.equal(String(uploads[1].url).includes("/__ai/reference"), true);
  const applied = posted(liveApply.world, "apply");
  assert.equal(applied.length, 1);
  assert.equal(applied[0].body.action, "apply");
  assert.equal(applied[0].body.instruction, "Keep the reservoir");
  assert.equal(liveCard.querySelector("[data-ai-reference-note]").textContent, "ref.png: Keep the reservoir");
  assert.deepEqual(applied[0].body.still, { id: "still-1", signature: "sig-1" });
  assert.equal(posted(liveApply.world, "generate").length, 0, "Apply does not use the generate action");
  assert.equal(String(liveCard.querySelector("[data-ai-reference-preview]").src || "").includes("ai-data"), false);

  const beatReference = run({ live: true, boardCards: [applyCard()] });
  beatReference.world.state.beats[0].guidance = {
    context_id: "ctx-beat", kind: "image", received: true, still: null,
  };
  await drain();
  beatReference.card.querySelector("[data-ai-remove-reference]").click();
  await drain();
  const removedBeat = posted(beatReference.world, "reference-remove");
  assert.equal(removedBeat.length, 1);
  assert.equal("still" in removedBeat[0].body, false, "Remove must cancel the displayed beat-level guidance even when a still exists");

  const delayed = run({ live: true, boardCards: [applyCard()] });
  await drain();
  delayed.world.holdUpload = true;
  const delayedFile = delayed.card.querySelector("[data-ai-file]");
  const delayedInstruction = delayed.card.querySelector("[data-ai-instruction]");
  delayedInstruction.value = "The original request";
  delayedInstruction.dispatchEvent({ type: "input" });
  delayedFile.files = [{ name: "original.png", type: "image/png", bytes: Uint8Array.from([1]) }];
  delayedFile.dispatchEvent({ type: "change" });
  delayed.card.querySelector("[data-ai-apply]").click();
  delayed.card.querySelector("[data-ai-apply]").click();
  await drain();
  assert.equal(delayed.world.uploadQueue.length, 1, "Double Apply must not send two concurrent uploads");
  delayed.card.setAttribute("data-ai-version", "still-new");
  delayed.card.setAttribute("data-ai-signature", "sig-new");
  delayedInstruction.value = "A new unsent instruction";
  delayedInstruction.dispatchEvent({ type: "input" });
  delayedFile.files = [{ name: "new.png", type: "image/png", bytes: Uint8Array.from([2]) }];
  delayedFile.dispatchEvent({ type: "change" });
  delayed.world.uploadQueue.shift()();
  await drain();
  const delayedApply = posted(delayed.world, "apply");
  assert.equal(delayedApply.length, 1);
  assert.deepEqual(delayedApply[0].body.still, { id: "still-1", signature: "sig-1" });
  assert.equal(delayedApply[0].body.instruction, "The original request");
  assert.equal(delayedApply[0].body.reference, "ctx-late");
  assert.equal(delayedFile.files[0].name, "new.png");
  assert.equal(delayedInstruction.value, "A new unsent instruction");
  assert.equal(delayed.card.querySelector("[data-ai-file-note]").textContent, "Selected, not sent.");
  const missingFile = run({ live: true, saved: delayed.store, boardCards: [applyCard()] });
  await drain();
  missingFile.card.querySelector("[data-ai-apply]").click();
  await drain();
  assert.equal(posted(missingFile.world, "apply").length, 0, "Reopening must not silently omit an unsent attachment");

  const failedUpload = run({ live: true, boardCards: [applyCard()] });
  await drain();
  failedUpload.world.failUpload = true;
  failedUpload.card.querySelector("[data-ai-instruction]").value = "Use this picture";
  const failedFile = failedUpload.card.querySelector("[data-ai-file]");
  failedFile.files = [{ name: "ref.png", type: "image/png", bytes: Uint8Array.from([1]) }];
  failedFile.dispatchEvent({ type: "change" });
  failedUpload.card.querySelector("[data-ai-apply]").click();
  await drain();
  assert.equal(posted(failedUpload.world, "apply").length, 0, "A refused upload must not fall through to generation");
  assert.equal(failedUpload.card.querySelector("[data-ai-file-note]").textContent,
    "Name the video interval. The reference was not kept.", "Polling must preserve the actual upload error");
  failedFile.files = [{ name: "new.png", type: "image/png", bytes: Uint8Array.from([2]) }];
  failedFile.dispatchEvent({ type: "change" });
  assert.equal(failedUpload.card.querySelector("[data-ai-file-note]").textContent, "Selected, not sent.");

  const stillReference = run({ live: true, boardCards: [applyCard()] });
  stillReference.world.holdPreview = true;
  stillReference.world.state.beats[0].reference = {
    context_id: "ctx-ancestor", kind: "image", received: true,
    still: { id: "ancestor", signature: "ancestor-sig" },
    target_still: { id: "still-1", signature: "sig-1" },
  };
  await drain();
  stillReference.card.querySelector("[data-ai-remove-reference]").click();
  await drain();
  assert.deepEqual(posted(stillReference.world, "reference-remove")[0].body.still, { id: "still-1", signature: "sig-1" });
  stillReference.world.previewQueue.shift()();
  await drain();
  assert.equal(stillReference.card.querySelector("[data-ai-reference-preview]").hidden, true, "Late preview bytes cannot restore a removed reference");

  const initialReference = run({ live: true, boardCards: [applyCard(false)] });
  initialReference.world.state.beats[0].reference = {
    context_id: "ctx-initial", kind: "image", received: true, target_still: null,
  };
  await drain();
  initialReference.card.querySelector("[data-ai-instruction]").value = "Use this blue palette";
  const initialFile = initialReference.card.querySelector("[data-ai-file]");
  initialFile.files = [{ name: "new.png", type: "image/png", bytes: Uint8Array.from([1]) }];
  initialFile.dispatchEvent({ type: "change" });
  initialReference.card.querySelector("[data-ai-upload]").click();
  await drain();
  const initialUpload = initialReference.world.calls.find((row) => row.binary);
  const initialMetadata = JSON.parse(decodeURIComponent(initialUpload.headers["X-GetBrolls-Ai-Reference"]));
  assert.equal("still" in initialMetadata, false, "Replacing initial guidance must not send an empty still identity");

  const changedReferenceTarget = run({ live: true, boardCards: [applyCard()] });
  changedReferenceTarget.world.state.beats[0].reference = {
    context_id: "ctx-old-target", kind: "image", received: true,
    target_still: { id: "still-1", signature: "sig-1" },
  };
  await drain();
  changedReferenceTarget.card.setAttribute("data-ai-version", "still-new");
  changedReferenceTarget.card.setAttribute("data-ai-signature", "sig-new");
  changedReferenceTarget.card.querySelector("[data-ai-remove-reference]").click();
  await drain();
  assert.equal(posted(changedReferenceTarget.world, "reference-remove").length, 0, "Navigation cannot remove another still's reference");

  const inheritedUpload = run({ live: true, boardCards: [applyCard()] });
  inheritedUpload.world.state.beats[0].reference = {
    context_id: "ctx-ancestor", kind: "image", received: true,
    target_still: { id: "still-1", signature: "sig-1" },
  };
  await drain();
  inheritedUpload.card.querySelector("[data-ai-generate]").click();
  await drain();
  inheritedUpload.world.state.beats[0].job = { id: "job-next", state: "complete" };
  inheritedUpload.world.state.beats[0].version = {
    id: "still-next", signature: "sig-next", path: "previews/next.png", approval: "pending",
  };
  inheritedUpload.world.state.beats[0].reference.target_still = { id: "still-next", signature: "sig-next" };
  inheritedUpload.advance(1000);
  await drain();
  inheritedUpload.card.querySelector("[data-ai-new-result]").click();
  const inheritedFile = inheritedUpload.card.querySelector("[data-ai-file]");
  inheritedFile.files = [{ name: "later.mp4", type: "video/mp4", bytes: Uint8Array.from([1, 2]) }];
  inheritedFile.dispatchEvent({ type: "change" });
  inheritedUpload.card.querySelector("[data-ai-instruction]").value = "Use the viewpoint from seconds 1 through 4";
  inheritedUpload.card.querySelector("[data-ai-interval-start]").value = "1";
  inheritedUpload.card.querySelector("[data-ai-interval-end]").value = "4";
  inheritedUpload.card.querySelector("[data-ai-upload]").click();
  await drain();
  const nextUploads = inheritedUpload.world.calls.filter((row) => row.binary);
  assert.equal(nextUploads.length, 1,
    "Selecting the saved revision must bind its inherited reference before the next upload");
  const nextMetadata = JSON.parse(decodeURIComponent(nextUploads[0].headers["X-GetBrolls-Ai-Reference"]));
  assert.deepEqual(nextMetadata.still, { id: "still-next", signature: "sig-next" });
  assert.equal(posted(inheritedUpload.world, "apply").length, 0, "Keeping the next reference does not generate");

  const paid = run({ live: true, boardCards: [aiCard({ alternatives: ["option-1", "option-2", "option-3"] })] });
  paid.world.state.openrouter = { image: { model: "test/image", resolution: "2K" } };
  paid.world.state.jobs = [1, 2, 3].map((slot) => ({
    id: "paid-" + slot, beat: "beat-1", kind: "image", route: "openrouter", group: "paid-group",
    state: "awaiting_confirmation", alternative: "option-" + slot,
    paid: { model: "test/image", fingerprint: "paid-fp-" + slot, prompt: "Frozen prompt " + slot, estimate: { usd: null } },
  }));
  await drain();
  paid.advance(1000);
  await drain();
  const paidBox = paid.card.querySelector("[data-ai-paid]");
  assert.equal(paidBox.querySelector("[data-ai-paid-image]").disabled, false);
  assert.equal(paidBox.querySelector("[data-ai-paid-video]").disabled, true);
  const confirmation = paidBox.querySelector("[data-ai-paid-confirm]");
  assert.ok(paidBox.textContent.includes("3 image output(s)"));
  assert.ok(paidBox.textContent.includes("Estimate unknown"));
  assert.ok(paidBox.textContent.includes("Frozen prompt 3"));
  assert.equal(posted(paid.world, "confirm-paid").length, 0, "Restoring prepared scope never authorizes spending");
  paid.card.querySelector("[data-ai-comment]").value = "An unsent later draft";
  paid.card.querySelector("[data-ai-comment]").dispatchEvent({ type: "input" });
  confirmation.click();
  confirmation.click();
  await drain();
  const confirmed = posted(paid.world, "confirm-paid");
  assert.equal(confirmed.length, 1, "Double click must confirm the one frozen group once");
  assert.deepEqual(Array.from(confirmed[0].body.jobs), ["paid-1", "paid-2", "paid-3"]);
  assert.equal(confirmed[0].body.signatures["paid-3"], "paid-fp-3");
  assert.equal(paid.card.querySelector("[data-ai-comment]").value, "An unsent later draft");
  assert.equal(posted(paid.world, "generate").length, 0, "Paid confirmation cannot invoke a subscription launch");
  paidBox.querySelector("[data-ai-paid-image]").click();
  await drain();
  assert.equal(posted(paid.world, "prepare-paid").length, 1);
  assert.equal(posted(paid.world, "prepare-paid")[0].body.comment, "An unsent later draft");
  const portablePaid = run({ live: false });
  assert.equal(portablePaid.card.querySelector("[data-ai-paid-image]").disabled, true);

  const ordered = run({ live: true, boardCards: [aiCard({ withStill: true, approval: "approved", version: "still-v", signature: "sig-v" })] });
  ordered.world.state = {
    native_video: { model: "grok-imagine-video-1.5", tool: "reference_to_video" },
    versions: [{ id: "still-v", signature: "sig-v", approval: "approved", kind: "image", beat: "beat-1" }],
    jobs: [],
    beats: [{ id: "beat-1", fingerprint: "fp-1", active: true, video_ready: true,
      timing: { resolved: true, start_s: 0, end_s: 8, still: "still-v" },
      sequence: { id: "seq-1", signature: "seq-fp", state: "planned", fps: 30, frames: 240, route: "grok-subscription", reasons: [],
        clips: [{ start_frame: 0, end_frame: 180, still: { id: "still-v" }, job: { id: "clip-a", state: "awaiting_confirmation" } },
          { start_frame: 180, end_frame: 240, still: { id: "still-v" }, job: { id: "clip-b", state: "awaiting_confirmation" } }], version: null } }],
  };
  await drain();
  const sequenceBox = ordered.card.querySelector("[data-ai-sequence]");
  assert.ok(sequenceBox, "A sequence has its own plan and review panel");
  assert.ok(sequenceBox.textContent.includes("240 frames"));
  assert.ok(sequenceBox.textContent.includes("2 clips"));
  assert.equal(posted(ordered.world, "launch-sequence").length, 0, "Restoring a sequence plan never launches it");
  const launchSequence = sequenceBox.querySelector("[data-ai-sequence-launch]");
  launchSequence.click(); launchSequence.click();
  ordered.world.state.beats[0].sequence.state = "running";
  await drain();
  assert.equal(posted(ordered.world, "launch-sequence").length, 1);
  assert.equal(posted(ordered.world, "launch-sequence")[0].body.signature, "seq-fp");
  ordered.world.state.beats[0].sequence.version = { id: "seq-media", kind: "sequence", signature: "seq-media-fp", path: "clips/ai-sequence.mp4", preview: { path: "previews/ai-sequence.mp4" }, approval: "pending", frames: 240, width: 854, height: 480, native_full_hd: false, clips: [] };
  ordered.advance(1000); await drain();
  const sequenceComment = sequenceBox.querySelector("[data-ai-sequence-comment]");
  assert.ok(sequenceComment);
  sequenceComment.value = "Keep this sequence draft";
  sequenceComment.dispatchEvent({ type: "input" });
  ordered.world.state.beats[0].sequence.state = "complete";
  ordered.advance(1000); await drain();
  assert.equal(sequenceBox.querySelector("[data-ai-sequence-comment]"), sequenceComment);
  assert.equal(sequenceComment.value, "Keep this sequence draft");
  sequenceBox.querySelector("[data-ai-sequence-decision='approved']").click();
  await drain();
  assert.equal(posted(ordered.world, "review").at(-1).body.version, "seq-media");
  ordered.exportButton.click(); await drain();
  assert.ok(JSON.parse(ordered.world.downloaded).ai.some((row) => row.version === "seq-media" && row.state === "approved"));
  assert.equal(portablePaid.card.querySelector("[data-ai-sequence-prepare]").disabled, true);

  const recovery = run({ live: true, boardCards: [aiCard({ withStill: true, approval: "approved" })] });
  recovery.world.state.jobs = [
    { id: "known-job", beat: "beat-1", state: "unknown", kind: "video", recovery: { action: "retrieve", reason: "retrieval_failed" }, correction_count: 0 },
    { id: "image-job", beat: "beat-1", state: "complete", kind: "image", result: "still-1", correction_count: 0, recovery: { action: null, reason: "complete" } },
    { id: "lost-job", beat: "beat-1", state: "unknown", kind: "image", recovery: { action: null, reason: "unknown_submit" } },
  ];
  recovery.world.state.versions = [{ id: "still-1", kind: "image", signature: "sig-1", path: "previews/ai-still-1.png" }];
  await drain();
  const historyBox = recovery.card.querySelector("[data-ai-recovery]");
  assert.ok(historyBox, "Known work has explicit recovery and attempt history");
  assert.ok(historyBox.textContent.includes("Submission outcome unknown"));
  const recoverKnown = historyBox.querySelector("[data-ai-recover='known-job']");
  const defect = historyBox.querySelector("[data-ai-defect='image-job']");
  const intent = historyBox.querySelector("[data-ai-correct-intent='image-job']");
  defect.value = "The wall edge is duplicated"; defect.dispatchEvent({ type: "input" });
  intent.value = "Remove the duplicate"; intent.dispatchEvent({ type: "input" });
  recovery.card.querySelector("[data-ai-comment]").value = "Keep my later draft";
  recovery.card.querySelector("[data-ai-comment]").dispatchEvent({ type: "input" });
  recoverKnown.click(); recoverKnown.click(); await drain();
  assert.equal(posted(recovery.world, "resume").length, 1);
  assert.equal(posted(recovery.world, "resume")[0].body.job, "known-job");
  assert.equal(defect.value, "The wall edge is duplicated");
  assert.equal(recovery.card.querySelector("[data-ai-comment]").value, "Keep my later draft");
  const correct = historyBox.querySelector("[data-ai-correct='image-job']");
  correct.click(); correct.click(); await drain();
  assert.equal(posted(recovery.world, "correct").length, 1);
  const correction = posted(recovery.world, "correct")[0].body;
  assert.equal(correction.signature, "sig-1");
  assert.equal(correction.defect, "The wall edge is duplicated");
  assert.equal(correction.instruction, "Remove the duplicate");
  assert.equal(posted(recovery.world, "generate").length, 0);
  const restoredRecovery = run({ live: true, saved: recovery.store, boardCards: [aiCard({ withStill: true, approval: "approved" })] });
  restoredRecovery.world.state = recovery.world.state;
  await drain();
  assert.equal(restoredRecovery.card.querySelector("[data-ai-defect='image-job']").value, defect.value);
  ordered.world.state.beats[0].sequence.version = null;
  ordered.world.state.beats[0].sequence.state = "partial";
  const partialSequence = run({ live: true });
  partialSequence.world.state = ordered.world.state;
  await drain();
  const recoverSequence = partialSequence.card.querySelector("[data-ai-sequence-resume]");
  assert.ok(recoverSequence);
  recoverSequence.click(); recoverSequence.click(); await drain();
  assert.equal(posted(partialSequence.world, "resume-sequence").length, 1);
  assert.equal(posted(partialSequence.world, "resume-sequence")[0].body.signature, "seq-fp");

  const handoff = run({ live: true, boardCards: [aiCard({ withStill: true, approval: "approved" })] });
  const delivery = { beat: "beat-1", version: "video-1", signature: "video-signature", approval: "approved", material_use: {}, delivery_state: "not_delivered", reasons: ["material_use_unresolved"] };
  handoff.world.state.beats[0].delivery = delivery;
  handoff.world.state.beats[0].job = { id: "running-fixture", state: "running", beat: "beat-1" };
  await drain();
  const useBox = handoff.card.querySelector("[data-ai-delivery]");
  for (const [name, value] of Object.entries({ state: "permitted", by: "Editor", conditions: "Only this project", evidence: "Fixture declaration" })) {
    const input = useBox.querySelector("[data-ai-use-" + name + "]");
    input.value = value; input.dispatchEvent({ type: "input" });
  }
  const conditions = useBox.querySelector("[data-ai-use-conditions]");
  handoff.advance(1000); await drain();
  assert.equal(useBox.querySelector("[data-ai-use-conditions]"), conditions);
  assert.equal(posted(handoff.world, "material-use").length, 0);
  useBox.querySelector("[data-ai-use-save]").click(); await drain();
  assert.equal(posted(handoff.world, "material-use")[0].body.signature, "video-signature");
  assert.equal(posted(handoff.world, "material-use")[0].body.conditions, "Only this project");
  handoff.world.state.beats[0].delivery = { ...delivery, version: "video-2", signature: "new-signature" };
  handoff.advance(1000); await drain();
  assert.equal(useBox.querySelector("[data-ai-use-conditions]").value, "");
  const reopenedUse = run({ live: true, saved: handoff.store, boardCards: [aiCard({ withStill: true, approval: "approved" })] });
  reopenedUse.world.state.beats[0].delivery = delivery;
  await drain();
  assert.equal(reopenedUse.card.querySelector("[data-ai-use-conditions]").value, "Only this project");

  const nativeRecovery = run({ live: true });
  const unknownNative = { id: "native-unknown", beat: "beat-1", state: "unknown", kind: "image", recovery: { action: "retrieve", reason: "retrieval_failed" } };
  nativeRecovery.world.state.jobs = [unknownNative];
  nativeRecovery.world.state.beats[0].job = unknownNative;
  await drain();
  nativeRecovery.card.querySelector("[data-ai-recover='native-unknown']").click();
  await drain();
  const nativeVersion = { id: "native-saved", kind: "image", path: "previews/native.png", signature: "native-sig", approval: "pending", width: 1600, height: 900, codec: "png" };
  const completeNative = { ...unknownNative, state: "complete", result: nativeVersion.id, recovery: { action: null, reason: "complete" } };
  nativeRecovery.world.state.jobs = [completeNative];
  nativeRecovery.world.state.beats[0].job = completeNative;
  nativeRecovery.world.state.beats[0].version = nativeVersion;
  nativeRecovery.world.state.versions = [nativeVersion];
  nativeRecovery.advance(1000); await drain();
  assert.equal(nativeRecovery.card.querySelector("[data-ai-result] img")?.getAttribute("src"), "previews/native.png", "An asynchronous unknown-result recovery appears without reload");
  assert.equal(nativeRecovery.world.reloads, 0);
  assert.equal(posted(nativeRecovery.world, "resume").length, 1);
  assert.equal(posted(nativeRecovery.world, "generate").length, 0);

  const stuckRecovery = run({ live: true });
  stuckRecovery.world.state.jobs = [unknownNative];
  stuckRecovery.world.state.beats[0].job = unknownNative;
  await drain();
  stuckRecovery.card.querySelector("[data-ai-recover='native-unknown']").click(); await drain();
  for (let minute = 0; minute < 6; minute += 1) { stuckRecovery.advance(30000); await drain(); }
  const observedReads = stuckRecovery.world.calls.filter((call) => call.method === "GET").length;
  stuckRecovery.advance(30000); await drain();
  assert.equal(stuckRecovery.world.calls.filter((call) => call.method === "GET").length, observedReads, "An unresolved recovery stops its bounded read-only watch");
  assert.equal(posted(stuckRecovery.world, "resume").length, 1);
  assert.equal(posted(stuckRecovery.world, "generate").length, 0);

  const disconnectedRecovery = run({ live: true });
  disconnectedRecovery.world.state.jobs = [unknownNative];
  disconnectedRecovery.world.state.beats[0].job = unknownNative;
  await drain();
  disconnectedRecovery.card.querySelector("[data-ai-recover='native-unknown']").click(); await drain();
  disconnectedRecovery.world.failStateRead = true;
  for (let minute = 0; minute < 6; minute += 1) { disconnectedRecovery.advance(30000); await drain(); }
  const failedReads = disconnectedRecovery.world.calls.filter((call) => call.method === "GET").length;
  disconnectedRecovery.advance(30000); await drain();
  assert.equal(disconnectedRecovery.world.calls.filter((call) => call.method === "GET").length, failedReads, "Failed status reads must also exhaust the recovery watch");
  assert.equal(disconnectedRecovery.card.querySelector("[data-ai-recover='native-unknown']").disabled, false);
  assert.equal(posted(disconnectedRecovery.world, "resume").length, 1);
  assert.equal(posted(disconnectedRecovery.world, "generate").length, 0);

  for (const mode of ["economy", "images", "apply"]) {
    async function providerLaunch(stillProvider, saved = null) {
      const fixture = run({ live: true, boardCards: mode === "apply" ? [applyCard()] : null, generateState: "failed", stillProvider, saved });
      await drain();
      const card = fixture.card;
      if (mode === "apply") {
        const instruction = card.querySelector("[data-ai-instruction]");
        instruction.value = "Preserve the composition and improve the light";
        instruction.dispatchEvent({ type: "input" });
      } else if (mode === "images") {
        const control = card.querySelector("[data-ai-mode]");
        control.value = "images";
        control.dispatchEvent({ type: "change" });
      }
      const button = card.querySelector(mode === "apply" ? "[data-ai-apply]" : "[data-ai-generate]");
      button.click(); button.click(); await drain();
      const launches = posted(fixture.world, mode === "apply" ? "apply" : "generate");
      assert.equal(launches.length, 1, mode + " retains double-click protection");
      return { nonce: launches[0].body.requestId, store: fixture.store };
    }
    const legacy = await providerLaunch(null);
    const oldSession = await providerLaunch({ route: "gpt-subscription", session_model: "fixture-old" }, legacy.store);
    const nextSession = await providerLaunch({ route: "gpt-subscription", session_model: "fixture-next" }, oldSession.store);
    assert.notEqual(oldSession.nonce, legacy.nonce, mode + " distinguishes an explicit session from the legacy default");
    assert.notEqual(nextSession.nonce, oldSession.nonce, mode + " uses a new identity after the session model changes");
    const reopened = await providerLaunch({ route: "gpt-subscription", session_model: "fixture-next" }, nextSession.store);
    assert.equal(reopened.nonce, nextSession.nonce, mode + " preserves replay identity on reopen");
    const grok = await providerLaunch({ route: "grok-subscription", model: "fixture-image" }, nextSession.store);
    assert.notEqual(grok.nonce, nextSession.nonce, mode + " distinguishes a changed subscription route");
    const defaultSetup = await providerLaunch({ route: "gpt-subscription", model: null }, legacy.store);
    assert.equal(defaultSetup.nonce, legacy.nonce, mode + " preserves old default identities");
  }

  console.log("AI storyboard recovery, material use and exact review preserve version-bound drafts");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
