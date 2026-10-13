// Compact graphics alignment-correction fixture. Same Element/DOM shape as storyboard_audio.cjs.
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
    if (selector.includes(",")) {
      const selectors = selector.split(",").map((part) => part.trim());
      return [...new Set(selectors.flatMap((part) => this.querySelectorAll(part)))];
    }
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
  click() {
    if (typeof this.onclick === "function") this.onclick({ type: "click" });
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

function alignmentForm(row, { editable, suffix }) {
  const candidate = el("input", { "data-alignment-candidate": "" });
  candidate.dataset.alignmentCandidate = "";
  const start = el("input", { "data-alignment-start": "" });
  start.dataset.alignmentStart = "";
  const end = el("input", { "data-alignment-end": "" });
  end.dataset.alignmentEnd = "";
  const statement = el("textarea", { "data-alignment-statement": "" });
  statement.dataset.alignmentStatement = "";
  const record = el("button", { "data-alignment-record": "", text: "Record correction" });
  record.dataset.alignmentRecord = "";
  const status = el("p", { "data-alignment-status": "", className: "graphics-alignment-status" });
  status.dataset.alignmentStatus = "";
  const form = el("div", { className: "graphics-alignment-correct" }, [
    candidate,
    start,
    end,
    statement,
    record,
    status,
  ]);
  form.dataset.alignmentId = row.id;
  form.dataset.alignmentSignature = editable ? row.signature : "00".repeat(32);
  form.dataset.alignmentEpoch = editable ? row.reviewEpoch : "00".repeat(32);
  form.dataset.alignmentEditable = editable ? "1" : "0";
  form.setAttribute("data-alignment-id", row.id);
  form.setAttribute("data-alignment-signature", form.dataset.alignmentSignature);
  form.setAttribute("data-alignment-epoch", form.dataset.alignmentEpoch);
  form.setAttribute("data-alignment-editable", form.dataset.alignmentEditable);
  return { form, candidate, start, end, statement, record, status, suffix };
}

function alignmentCard(row) {
  const card = el("article", { className: "graphics-card" });
  card.dataset.occurrence = row.occurrence_id;
  const first = el("audio", {
    className: "graphics-alignment-preview",
    src: "previews/alignment-stat-01-c1.wav",
    "data-candidate": "c1",
  });
  first.dataset.candidate = "c1";
  const second = el("audio", {
    className: "graphics-alignment-preview",
    src: "previews/alignment-stat-01-c2.wav",
    "data-candidate": "c2",
  });
  second.dataset.candidate = "c2";
  const video = el("video", { className: "graphics-preview" });
  video.className = "graphics-preview";
  const vo = el("audio", { className: "graphics-vo-preview" });
  vo.className = "graphics-vo-preview";
  const hiddenPreview = el("audio", {
    className: "graphics-alignment-preview",
    src: "previews/alignment-old.wav",
    "data-candidate": "old",
  });
  hiddenPreview.dataset.candidate = "old";
  const override = el("audio", {
    className: "graphics-alignment-preview",
    src: "previews/alignment-stat-01-override.wav",
    "data-candidate": "override",
  });
  override.dataset.candidate = "override";
  const overrideError = el("p", { className: "graphics-alignment-override-error", text: "" });
  const frozen = alignmentForm(row, { editable: false, suffix: "frozen" });
  const current = alignmentForm(row, { editable: true, suffix: "current" });
  const frozenPane = el("div", { className: "graphics-version is-compare", "data-version": "v1" }, [
    el("ul", { className: "graphics-alignment-candidates" }, [el("li", { "data-candidate-id": "old" }, [hiddenPreview])]),
    frozen.form,
  ]);
  frozenPane.dataset.version = "v1";
  const currentPane = el("div", { className: "graphics-version is-shown", "data-version": "v2" }, [
    video,
    vo,
    el("ul", { className: "graphics-alignment-candidates" }, [
      el("li", { "data-candidate-id": "c1" }, [first]),
      el("li", { "data-candidate-id": "c2" }, [second]),
    ]),
    el("div", { className: "graphics-alignment-override" }, [override, overrideError]),
    current.form,
  ]);
  currentPane.dataset.version = "v2";
  const display = el("select", { "data-graphics-display": "" }, []);
  display.dataset.graphicsDisplay = "";
  display.value = "v2";
  const compare = el("select", { "data-graphics-compare": "" }, []);
  compare.dataset.graphicsCompare = "";
  card.append(display, compare, frozenPane, currentPane);
  card.first = first;
  card.second = second;
  card.video = video;
  card.vo = vo;
  card.hiddenPreview = hiddenPreview;
  card.override = override;
  card.frozen = frozen;
  card.candidate = current.candidate;
  card.start = current.start;
  card.end = current.end;
  card.statement = current.statement;
  card.record = current.record;
  card.status = current.status;
  card.frozenStatus = frozen.status;
  card.currentPane = currentPane;
  card.frozenPane = frozenPane;
  card.display = display;
  card.compare = compare;
  return card;
}

function makeDocument(card, main, board, storage, done, exportButton, printButton) {
  return {
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
      if (selector === "#export-review") return exportButton;
      if (selector === "#print-review") return printButton;
      return main.querySelector(selector);
    },
    querySelectorAll(selector) {
      if (selector === "[data-storage-status]") return [storage];
      if (selector === "[data-summary]") return [el("p")];
      if (selector === ".export-done") return [done];
      if (selector === ".shot") return [];
      if (selector === ".graphics-card") return [card];
      if (selector === ".graphics-alignment-preview") {
        return [card.first, card.second, card.hiddenPreview, card.override];
      }
      if (selector === ".graphics-preview, .graphics-vo-preview, .graphics-alignment-preview") {
        return [card.video, card.vo, card.first, card.second, card.hiddenPreview, card.override];
      }
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
}

async function run(reviewPath) {
  const row = {
    id: "alignment:stat-01",
    project: "synthetic-alignment",
    scene_id: "numeric-stat",
    occurrence_id: "stat-01",
    signature: "aa".repeat(32),
    reviewEpoch: "aa".repeat(32),
    analysis_id: "na-1",
    recording_id: "rec-1",
    recording_sha256: "bb".repeat(32),
    recording_duration_s: 16,
    transcript_sha256: "cc".repeat(32),
    scenario_sha256: "dd".repeat(32),
    input_fingerprint: "ee".repeat(32),
    order: 0,
    fps: 30,
    state: "uncertain",
    selected_candidate_id: null,
    timing: null,
    candidates: [
      { id: "c1", start_s: 0, end_s: 1.5, preview: { ref: "previews/alignment-stat-01-c1.wav" } },
      { id: "c2", start_s: 4, end_s: 5.5, preview: { ref: "previews/alignment-stat-01-c2.wav" } },
    ],
  };
  const graphicsRowV1 = {
    id: "graphics:stat-01:v1",
    project: "synthetic-alignment",
    scene_id: "numeric-stat",
    occurrence_id: "stat-01",
    version: "v1",
    current: false,
    signature: "22".repeat(32),
    reviewEpoch: "22".repeat(32),
    state: "pending",
    timing_basis: "explicit",
    requests: [],
  };
  const graphicsRow = {
    id: "graphics:stat-01:v2",
    project: "synthetic-alignment",
    scene_id: "numeric-stat",
    occurrence_id: "stat-01",
    version: "v2",
    current: true,
    signature: "11".repeat(32),
    reviewEpoch: "11".repeat(32),
    state: "pending",
    timing_basis: "estimated",
    requests: [],
  };
  const card = alignmentCard(row);
  const main = el("main");
  const board = el("section", { className: "graphics-board" }, [card]);
  const storage = el("span", { "data-storage-status": "" });
  storage.dataset.storageStatus = "";
  const done = el("p", { className: "export-done" });
  const exportButton = el("button", { id: "export-review" });
  exportButton.attrs.id = "export-review";
  const printButton = el("button", { id: "print-review" });
  printButton.attrs.id = "print-review";
  main.append(el("div", { className: "review-summary" }, [exportButton, printButton, storage, done]), board);
  const store = {};
  let exported;
  let printed = 0;
  const payload = {
    type: "getbrolls-review",
    templateVersion: 2,
    project: "synthetic-alignment",
    items: [],
    graphics: [graphicsRowV1, graphicsRow],
    alignment: [row],
  };
  function boot(localStore) {
    exported = undefined;
    // A real reload creates fresh controls; this fixture reuses its DOM objects.
    exportButton.dataset.wired = "";
    printButton.dataset.wired = "";
    card.querySelectorAll(".graphics-alignment-correct").forEach((box) => {
      box.dataset.alignmentMounted = "";
    });
    const windowObj = {
      GETBROLLS_REVIEW: payload,
      addEventListener() {},
      print() {
        printed += 1;
      },
      Event: class {
        constructor(type) {
          this.type = type;
        }
      },
    };
    const context = {
      setTimeout,
      clearTimeout,
      window: windowObj,
      document: makeDocument(card, main, board, storage, done, exportButton, printButton),
      Event: windowObj.Event,
      localStorage: {
        getItem(name) {
          return Object.prototype.hasOwnProperty.call(localStore, name) ? localStore[name] : null;
        },
        setItem(name, value) {
          localStore[name] = value;
        },
      },
      print() {
        printed += 1;
      },
      matchMedia: () => ({ matches: true }),
      MutationObserver: class {
        observe() {}
      },
      IntersectionObserver: undefined,
      URL: {
        createObjectURL() {
          return "blob:alignment";
        },
        revokeObjectURL() {},
      },
      Blob: class {
        constructor(parts) {
          exported = JSON.parse(parts[0]);
        }
      },
      fetch: async () => ({ ok: true, json: async () => ({ name: "saved.json", path: "reviews/saved.json" }) }),
      navigator: {},
      console,
    };
    vm.runInNewContext(fs.readFileSync(reviewPath, "utf8"), context);
    return context;
  }
  boot(store);
  assert.equal(card.frozen.record.disabled, true);
  assert.equal(card.frozen.candidate.disabled, true);
  assert.match(card.frozenStatus.textContent, /will not retarget|original alignment context/i);
  assert.equal(card.record.disabled, false);
  card.video.paused = false;
  card.vo.paused = false;
  card.first.play();
  assert.equal(card.first.paused, false);
  assert.equal(card.video.paused, true);
  assert.equal(card.vo.paused, true);
  card.second.play();
  assert.equal(card.first.paused, true);
  assert.equal(card.second.paused, false);
  card.override.play();
  assert.equal(card.override.paused, false);
  assert.equal(card.second.paused, true);
  assert.equal(card.video.paused, true);
  assert.equal(card.vo.paused, true);
  card.override.end();
  assert.equal(card.override.ended, true);
  assert.equal(card.override.paused, true);
  card.hiddenPreview.paused = false;
  card.override.paused = false;
  card.currentPane.dataset.version = "v2";
  card.frozenPane.dataset.version = "v1";
  card.display.value = "v1";
  card.display.onchange && card.display.onchange();
  assert.equal(card.second.paused, true);
  assert.equal(card.override.paused, true);
  assert.equal(card.video.paused, true);
  assert.equal(card.vo.paused, true);
  assert.equal(card.currentPane.className.split(/\s+/).includes("is-shown"), false);
  assert.equal(card.frozenPane.className.split(/\s+/).includes("is-shown"), true);
  await printButton.onclick();
  assert.equal(printed, 1);
  card.candidate.value = "c2";
  card.statement.value = "Synthetic fixture: keep the second repeat.";
  card.record.onclick();
  exportButton.onclick();
  assert.ok(exported);
  assert.equal(exported.templateVersion, 2);
  assert.equal(exported.alignment[0].candidate_id, "c2");
  assert.equal(exported.alignment[0].statement, "Synthetic fixture: keep the second repeat.");
  assert.equal(exported.alignment[0].signature, row.signature);
  assert.equal(exported.alignment[0].analysis_id, row.analysis_id);
  assert.equal(exported.alignment[0].recording_id, row.recording_id);
  assert.equal(exported.alignment[0].recording_duration_s, row.recording_duration_s);
  assert.equal(exported.alignment[0].order, row.order);
  assert.equal(exported.alignment[0].fps, row.fps);
  const overrideStore = {};
  boot(overrideStore);
  card.candidate.value = "";
  card.start.value = "1.25";
  card.end.value = "2.5";
  card.statement.value = "Synthetic fixture: bounded override already received.";
  card.record.onclick();
  exportButton.onclick();
  assert.equal(exported.alignment[0].start_s, 1.25);
  assert.equal(exported.alignment[0].end_s, 2.5);
  assert.equal(exported.alignment[0].statement, "Synthetic fixture: bounded override already received.");
  assert.equal(exported.alignment[0].signature, row.signature);
  const stale = JSON.parse(store["getbrolls-v2-alignment:synthetic-alignment"]);
  stale[row.id].signature = "ff".repeat(32);
  stale[row.id].reviewEpoch = "ff".repeat(32);
  store["getbrolls-v2-alignment:synthetic-alignment"] = JSON.stringify(stale);
  card.candidate.value = "";
  card.statement.value = "";
  card.record.dataset.alignmentMounted = "";
  card.querySelectorAll(".graphics-alignment-correct").forEach((box) => {
    box.dataset.alignmentMounted = "";
  });
  boot(store);
  exportButton.onclick();
  assert.ok(exported);
  assert.notEqual(exported.alignment[0].candidate_id, "c2");
  assert.equal(exported.alignment[0].statement, "");
}

Promise.resolve(run(process.argv[2])).catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
