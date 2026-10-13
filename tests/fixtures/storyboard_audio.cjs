// Compact graphics media-sync fixture. Same Element/DOM shape as storyboard_graphics.cjs.
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
    this.muted = false;
    this.paused = true;
    this.ended = false;
    this.currentTime = 0;
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
  get innerHTML() {
    return this._text;
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
  closest(selector) {
    let node = this;
    while (node) {
      if (node.matches(selector)) return node;
      node = node.parentNode;
    }
    return null;
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
  appendChild(node) {
    this.append(node);
    return node;
  }
  contains(node) {
    if (node === this) return true;
    return this.children.some((child) => child.contains(node));
  }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }
  insertAdjacentElement(position, node) {
    if (position === "afterend" && this.parentNode) {
      const siblings = this.parentNode.children;
      const index = siblings.indexOf(this);
      node.parentNode = this.parentNode;
      siblings.splice(index + 1, 0, node);
      return node;
    }
    this.append(node);
    return node;
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
  addEventListener(name, handler) {
    this.listeners[name] = this.listeners[name] || [];
    this.listeners[name].push(handler);
  }
  dispatchEvent(event) {
    const name = event.type;
    const handler = this["on" + name];
    if (typeof handler === "function") handler(event);
    (this.listeners[name] || []).forEach((fn) => fn(event));
    return true;
  }
  play() {
    this.paused = false;
    this.ended = false;
    this.dispatchEvent({ type: "play" });
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
    this.dispatchEvent({ type: "pause" });
  }
  seek(time) {
    this.currentTime = time;
    this.dispatchEvent({ type: "seeking" });
    this.dispatchEvent({ type: "seeked" });
  }
  end() {
    this.ended = true;
    this.paused = true;
    this.dispatchEvent({ type: "ended" });
  }
  get classList() {
    const el = this;
    return {
      add(name) {
        const parts = new Set(el.className.split(/\s+/).filter(Boolean));
        parts.add(name);
        el.className = [...parts].join(" ");
      },
      toggle(name, force) {
        const parts = new Set(el.className.split(/\s+/).filter(Boolean));
        const on = force == null ? !parts.has(name) : !!force;
        if (on) parts.add(name);
        else parts.delete(name);
        el.className = [...parts].join(" ");
        return on;
      },
      contains(name) {
        return el.className.split(/\s+/).includes(name);
      },
    };
  }
}

function el(tag, attrs = {}, children = []) {
  const node = new Element(tag);
  Object.entries(attrs).forEach(([name, value]) => {
    if (name === "className") node.className = value;
    else if (name === "dataset") Object.assign(node.dataset, value);
    else if (name === "text") node.textContent = value;
    else node.setAttribute(name, value);
  });
  children.forEach((child) => node.append(child));
  return node;
}

function versionPane(row) {
  const pane = el("div", {
    className: row.current ? "graphics-version is-shown" : "graphics-version",
    "data-version": row.version,
    "data-row-id": row.id,
    "data-current": String(!!row.current),
  });
  pane.dataset.version = row.version;
  pane.dataset.rowId = row.id;
  pane.dataset.current = String(!!row.current);
  const video = el("video", { className: "graphics-preview", src: row.artifact, "data-fps": "30" });
  video.dataset.fps = "30";
  const audio = el("audio", {
    className: "graphics-vo-preview",
    src: row.voPreview || "previews/graphics-stat-01-v1-vo.m4a",
    "data-fps": "30",
  });
  audio.dataset.fps = "30";
  const record = el("p", { "data-graphics-decision-record": "", className: "graphics-decision-record" });
  record.dataset.graphicsDecisionRecord = "";
  pane.append(video, audio, record);
  pane.video = video;
  pane.audio = audio;
  return pane;
}

function graphicsCard(rows) {
  const current = rows.find((row) => row.current) || rows[0];
  const card = el("article", { className: "graphics-card" });
  card.dataset.occurrence = current.occurrence_id;
  const display = el("select", { "data-graphics-display": "" });
  display.dataset.graphicsDisplay = "";
  const compare = el("select", { "data-graphics-compare": "" });
  compare.dataset.graphicsCompare = "";
  compare.append(el("option", { value: "", text: "None" }));
  rows.forEach((row) => {
    const option = el("option", { value: row.version, text: row.version });
    if (row.current) option.attrs.selected = "selected";
    display.append(option);
    compare.append(el("option", { value: row.version, text: row.version }));
  });
  display.value = current.version;
  compare.value = "";
  const tools = el("div", { className: "graphics-version-tools" }, [display, compare]);
  const versions = el("div", { className: "graphics-versions" }, rows.map(versionPane));
  const badge = el("span", { className: "timing-basis explicit", text: "Explicit narration timing" });
  const approve = el("button", { "data-graphics-decision": "approved" });
  approve.dataset.graphicsDecision = "approved";
  const changes = el("button", { "data-graphics-decision": "changes" });
  changes.dataset.graphicsDecision = "changes";
  const comment = el("textarea", { "data-graphics-comment": "" });
  comment.dataset.graphicsComment = "";
  const shared = el("input", { type: "checkbox", "data-graphics-shared": "" });
  shared.dataset.graphicsShared = "";
  const fields = el("div", { className: "review-fields" }, [comment, shared]);
  fields.hidden = true;
  const panel = el("section", { className: "graphics-review-panel" }, [
    el("div", { className: "graphics-review-actions review-actions" }, [approve, changes]),
    el("button", { className: "comment-toggle", text: "Comment" }),
    fields,
    el("p", { "data-graphics-readiness": "", className: "graphics-readiness" }),
    el("div", { "data-graphics-requests": "", className: "graphics-request-status" }),
    el("p", { "data-graphics-status": "", className: "feedback" }),
  ]);
  panel.querySelector("[data-graphics-readiness]").dataset.graphicsReadiness = "";
  panel.querySelector("[data-graphics-requests]").dataset.graphicsRequests = "";
  panel.querySelector("[data-graphics-status]").dataset.graphicsStatus = "";
  card.append(el("p", { className: "graphics-meta" }, [badge]), tools, versions, panel);
  card.display = display;
  card.panes = versions.children;
  return card;
}

function row(version, current) {
  return {
    id: "graphics:stat-01:" + version,
    project: "synthetic-audio",
    scene_id: "numeric-stat",
    occurrence_id: "stat-01",
    version,
    parent: version === "v1" ? null : "v1",
    current,
    signature: version === "v1" ? "aa".repeat(32) : "bb".repeat(32),
    reviewEpoch: "epoch-" + version,
    state: "pending",
    comment: "",
    scope: "scene",
    requestId: null,
    timing_basis: "explicit",
    artifact: "previews/graphics-stat-01-" + version + ".mp4",
    voPreview: "previews/graphics-stat-01-" + version + "-vo.m4a",
    approval: null,
    readiness: { complete: true, reviewable: true, approved: false, deliverable: false, reasons: [] },
    versions: [
      { id: "v1", parent: null, status: "complete" },
      { id: "v2", parent: "v1", status: "complete" },
    ],
    requests: [],
    context: {
      narration: "The count stands at twelve units.",
      timing: { basis: "explicit", start_s: 0, end_s: 1.5, duration_in_frames: 45 },
      props: { value: "12", unit: "units", claim_status: "synthetic" },
    },
  };
}

function run(reviewPath) {
  const v1 = row("v1", true);
  const v2 = row("v2", false);
  const card = graphicsCard([v1, v2]);
  const main = el("main");
  const board = el("section", { className: "graphics-board" }, [card]);
  const storage = el("span", { "data-storage-status": "" });
  storage.dataset.storageStatus = "";
  const done = el("p", { className: "export-done" });
  const exportButton = el("button", { id: "export-review" });
  exportButton.attrs.id = "export-review";
  main.append(el("div", { className: "review-summary" }, [exportButton, storage, done]), board);
  const document = {
    body: { classList: { contains: () => false } },
    querySelector(selector) {
      if (selector === "main") return main;
      if (selector === ".graphics-board") return board;
      if (selector === ".export-done") return done;
      if (selector === "[data-storage-status]") return storage;
      if (selector === ".review-toolbar") return null;
      if (selector === "#pending-only") return null;
      if (selector === "#select") return null;
      if (selector === "#viewer") return null;
      if (selector === "#tools") return null;
      return main.querySelector(selector);
    },
    querySelectorAll(selector) {
      if (selector === "[data-storage-status]") return [storage];
      if (selector === "[data-summary]") return [el("p")];
      if (selector === ".export-done") return [done];
      if (selector === ".shot") return [];
      return main.querySelectorAll(selector);
    },
    createElement(tag) {
      return new Element(tag);
    },
    createTextNode(text) {
      const node = new Element("#text");
      node.textContent = text;
      return node;
    },
    addEventListener() {},
  };
  const store = {};
  const window = {
    GETBROLLS_REVIEW: {
      type: "getbrolls-review",
      templateVersion: 2,
      project: "synthetic-audio",
      items: [],
      graphics: [v1, v2],
    },
    addEventListener() {},
    Event: class {
      constructor(type) {
        this.type = type;
      }
    },
  };
  const context = {
    window,
    document,
    Event: window.Event,
    localStorage: {
      getItem(name) {
        return Object.prototype.hasOwnProperty.call(store, name) ? store[name] : null;
      },
      setItem(name, value) {
        store[name] = value;
      },
    },
    matchMedia: () => ({ matches: true }),
    MutationObserver: class {
      observe() {}
    },
    IntersectionObserver: undefined,
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    navigator: {},
    setTimeout,
    console,
  };
  vm.runInNewContext(fs.readFileSync(reviewPath, "utf8"), context);
  const paneV1 = card.panes[0];
  const paneV2 = card.panes[1];
  assert.equal(paneV1.video.paused, true, "preview does not autoplay");
  assert.equal(paneV1.audio.paused, true, "VO preview does not autoplay");
  paneV1.video.currentTime = 0.4;
  paneV1.audio.currentTime = 0;
  paneV1.video.play();
  assert.equal(paneV1.audio.paused, false, "VO preview plays with the effects video");
  assert.ok(Math.abs(paneV1.audio.currentTime - paneV1.video.currentTime) <= 1 / 30);
  paneV1.video.seek(1.2);
  assert.ok(Math.abs(paneV1.audio.currentTime - 1.2) <= 1 / 30);
  paneV1.video.pause();
  assert.equal(paneV1.audio.paused, true);
  paneV1.video.play();
  card.display.value = "v2";
  card.display.onchange();
  assert.equal(paneV1.video.paused, true, "hidden version pauses");
  assert.equal(paneV1.audio.paused, true);
  paneV2.video.currentTime = 0.2;
  paneV2.audio.currentTime = 0;
  paneV2.video.play();
  assert.equal(paneV2.audio.paused, false);
  assert.ok(Math.abs(paneV2.audio.currentTime - paneV2.video.currentTime) <= 1 / 30);
  paneV2.video.end();
  assert.equal(paneV2.audio.paused, true);
  const mute = paneV2.querySelector("[data-graphics-mute-vo]");
  assert.ok(mute);
  mute.checked = true;
  mute.onchange();
  assert.equal(paneV2.audio.muted, true);
  assert.equal(paneV1.audio.muted, false, "only the displayed pane mute changes");
  assert.equal(window.GETBROLLS_REVIEW.graphics[0].state, "pending");
  console.log("ok");
}

run(process.argv[2]);
