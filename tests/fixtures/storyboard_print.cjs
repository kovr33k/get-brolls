// Execute the actual review script with delayed image decoding and native beforeprint.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.value = "";
  }
  append(...children) {
    children.forEach((child) => {
      child.parentNode = this;
      this.children.push(child);
    });
  }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
    this.parentNode = null;
  }
  querySelectorAll(selector) {
    return this.children.flatMap((child) => [
      ...(child.tag === selector || "." + child.className === selector ? [child] : []),
      ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  setAttribute() {}
}

async function exercise({ broken = false, printThrows = false } = {}) {
  const main = new Element("main");
  const printButton = new Element("button");
  const fields = new Map();
  const rejectButton = new Element("button");
  rejectButton.dataset.decision = "rejected";
  const panel = new Element();
  panel.querySelector = (selector) => {
    if (!fields.has(selector)) fields.set(selector, new Element());
    return fields.get(selector);
  };
  panel.querySelectorAll = (selector) => selector === "[data-decision]" ? [rejectButton] : [];
  const viewer = new Element();
  viewer.querySelector = (selector) => selector === ".review-panel" ? panel : null;
  const select = new Element();
  select.value = "0";
  const document = {
    querySelector(selector) {
      if (selector === "main") return main;
      if (selector === "#print-review") return printButton;
      if (selector === "#viewer") return viewer;
      if (selector === "#select") return select;
      return main.querySelector(selector);
    },
    querySelectorAll() { return []; },
    createElement(tag) {
      const element = new Element(tag);
      if (tag === "img") element.decode = () => new Promise((resolve, reject) => {
        element.finishDecode = broken ? reject : resolve;
      });
      return element;
    },
  };
  const events = {};
  const items = ["fast.jpg", "delayed.jpg"].map((poster, index) => ({
    id: String(index), signature: String(index), reviewEpoch: "fixture",
    title: "Synthetic frame " + index, poster, source: "https://example.org/fixture",
    segment: { start_s: 0, end_s: 3 }, narration: "Original narration",
  }));
  let printed = 0;
  let printedImages;
  const window = {
    GETBROLLS_REVIEW: { project: "synthetic-print", items },
    addEventListener(name, callback) { events[name] = callback; },
    print() {
      events.beforeprint();
      printedImages = main.querySelectorAll("img");
      printed++;
      if (printThrows) throw new Error("Native print unavailable");
    },
  };
  vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), {
    window, document,
    localStorage: { getItem() { return null; }, setItem() {} },
    matchMedia: () => ({ matches: true }),
    MutationObserver: class { observe() {} },
  });
  assert.equal(main.querySelectorAll("img").length, 2, "Native browser printing needs images prepared during review");
  rejectButton.onclick();
  const printing = printButton.onclick();
  assert.equal(printed, 0, "Native print must wait for delayed images");
  assert.equal(printButton.disabled, true);
  const originalImages = main.querySelectorAll("img");
  assert.equal(originalImages.length, 2);
  originalImages[0].finishDecode();
  await Promise.resolve();
  assert.equal(printed, 0, "One decoded image must not release printing");
  originalImages[1].finishDecode();
  if (printThrows) await assert.rejects(printing, /Native print unavailable/);
  else await printing;
  assert.equal(printed, 1);
  assert.equal(printButton.disabled, false);
  assert.deepEqual(printedImages, originalImages, "beforeprint must retain decoded image nodes");
  assert.ok(main.querySelectorAll("p").some((p) => p.textContent === "Review: Rejected"));
  assert.ok(main.querySelectorAll("p").some((p) => p.textContent === "Narration: “Original narration”"));
  assert.equal(main.querySelectorAll("article").length, 2, "Repeated preparation must not duplicate pages");
  console.log("Print waits for images, retains current decisions and restores its button");
}

(async () => {
  await exercise();
  await exercise({ broken: true });
  await exercise({ printThrows: true });
})().catch((error) => { console.error(error); process.exitCode = 1; });
