// Screenshots and deterministic browser checks on GitHub-hosted runner only.
// Targets are fixed public sites: no arbitrary URL, private IP or credential fetch.
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";

const TARGETS = Object.freeze({
  pv: "https://dday2301.github.io/PROJEKT/",
  bloglab: "https://bloglab.eu/",
});
const target = process.argv[2];
if (!Object.hasOwn(TARGETS, target)) {
  throw new Error("Use the fixed target 'pv' or 'bloglab'.");
}
const base = TARGETS[target];
const output = "pv-visual-qa-output";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const profile of [
    { name: "desktop", width: 1440, height: 900, isMobile: false },
    { name: "mobile", width: 390, height: 844, isMobile: true },
  ]) {
    const context = await browser.newContext({
      viewport: { width: profile.width, height: profile.height },
      isMobile: profile.isMobile, reducedMotion: "reduce",
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error).slice(0, 300)));
    const response = await page.goto(base, {
      waitUntil: "domcontentloaded", timeout: 45000,
    });
    await page.waitForTimeout(1800);
    const metrics = await page.evaluate(() => {
      const images = [...document.images];
      const buttons = [...document.querySelectorAll("button")];
      return {
        title: document.title,
        width: document.documentElement.scrollWidth,
        viewport: window.innerWidth,
        broken_images: images.filter(x => x.complete && x.naturalWidth === 0).length,
        unlabeled_buttons: buttons.filter(b => !(
          b.getAttribute("aria-label") || b.getAttribute("title") ||
          (b.textContent || "").trim()
        )).length,
        h1_count: document.querySelectorAll("h1").length,
      };
    });
    await page.screenshot({ path: `${output}/${target}-${profile.name}.png`,
      fullPage: true, animations: "disabled" });
    results.push({
      profile: profile.name, http_status: response?.status() ?? null,
      url: page.url(), metrics, errors,
      passed: Boolean(response && response.status() < 400 &&
        metrics.width <= metrics.viewport + 2 &&
        metrics.broken_images === 0 && metrics.unlabeled_buttons === 0),
    });
    await context.close();
  }
} finally {
  await browser.close();
}
const report = {
  tool: "remote-visual-qa-v8", target, base,
  checked_utc: new Date().toISOString(), results,
  conclusion: results.every(x => x.passed) ? "pass" : "needs_review",
};
await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify({ target, conclusion: report.conclusion, results }));
// These checks are diagnostic; they create visual evidence, never deploy.
