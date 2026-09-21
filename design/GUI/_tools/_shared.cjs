/*
 * design/GUI/_tools/_shared.cjs — 截图脚本公共自解析工具（#1361）
 *
 * 🔴 为什么需要它：
 *   本目录下 shot-*.cjs 曾把「GUI 根」和「playwright 依赖路径」写死成某个 worktree 的绝对路径
 *   （形如 <仓库父目录>/InkFlow-ft/<某历史 worktree>/...）。worktree 一旦被清理：
 *     - 若写死的是 ROOT  → 图静默出到别的目录（假绿：git status 干净，看着像成功）
 *     - 若写死的是 require → 脚本硬崩（Cannot find module）
 *   两者都让「原型截图」这个验证手段不可信。
 *
 * ✅ 正确形态：一切从 __dirname（脚本自身位置）向上推导，与脚本被放在哪个 worktree 无关。
 *
 * 用法（所有 shot-*.cjs 统一）：
 *   const { guiRoot, requirePlaywright } = require('./_shared.cjs');
 *   const ROOT = guiRoot();
 *   const chromium = requirePlaywright();
 */

const path = require('path');
const fs = require('fs');

/** 上溯时最大层数（design/GUI/_tools → 仓库根 = 4 层，留余量） */
const MAX_UP = 8;

/** electron 包内 playwright 的相对位置（本仓既有约定：复用 electron 的依赖，不额外装） */
const PW_REL = path.join('frontend', 'packages', 'electron', 'node_modules', '@playwright', 'test');

/**
 * 从本文件位置向上找 `design/GUI` 根目录。
 * 判据 = 目录名为 GUI 且内含至少一个页面子目录（不写死具体页面，避免新增页面时失效）。
 *
 * @returns {string} design/GUI 的绝对路径
 * @throws {Error} 上溯 MAX_UP 层仍找不到 → 明确报错（不静默落别处）
 */
function guiRoot() {
  let dir = __dirname;
  for (let i = 0; i < MAX_UP; i += 1) {
    if (path.basename(dir) === 'GUI' && looksLikeGuiRoot(dir)) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break; // 到盘根了
    dir = parent;
  }
  throw new Error(
    `[#1361] 找不到 design/GUI 根目录（从 ${__dirname} 上溯 ${MAX_UP} 层）。\n` +
    '  本文件应位于 design/GUI/_tools/ 下——请确认脚本未被移出该目录。',
  );
}

/** design/GUI 的判据：存在 _tools 目录（本目录），且存在任意页面目录 */
function looksLikeGuiRoot(dir) {
  if (!fs.existsSync(path.join(dir, '_tools'))) return false;
  try {
    return fs.readdirSync(dir, { withFileTypes: true }).some(
      (e) => e.isDirectory() && e.name !== '_tools' && !e.name.startsWith('.'),
    );
  } catch {
    return false;
  }
}

/**
 * 从本文件位置向上找 electron 包内的 @playwright/test 并 require 它。
 * 判据 = 候选路径存在 pyproject/package.json 意义上的真实目录即可（不依赖主仓）。
 *
 * @returns {typeof import('@playwright/test').chromium}
 * @throws {Error} 找不到 → 明确提示先跑 pnpm install
 */
function requirePlaywright() {
  let dir = __dirname;
  for (let i = 0; i < MAX_UP; i += 1) {
    const candidate = path.join(dir, PW_REL);
    if (fs.existsSync(candidate)) return require(candidate).chromium;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(
    `[#1361] 找不到 @playwright/test（从 ${__dirname} 上溯 ${MAX_UP} 层查找 ${PW_REL}）。\n` +
    '  请先在仓库 frontend/ 下执行：pnpm install --frozen-lockfile',
  );
}

/**
 * 断言截图输出目录存在（防御：目录不存在时明确报错，而不是让 playwright 静默写失败/落别处）。
 *
 * @param {string} pageDir 页面子目录名，如 'timeline'
 * @param {string} root GUI 根目录（默认取 guiRoot()）
 * @returns {string} 该页面目录的绝对路径
 */
function assertPageDir(pageDir, root) {
  const base = root || guiRoot();
  const dir = path.join(base, pageDir);
  if (!fs.existsSync(dir)) {
    throw new Error(
      `[#1361] 截图输出目录不存在：${dir}\n` +
      `  design/GUI 下没有页面目录「${pageDir}」——请核对脚本里的 PAGES 配置。`,
    );
  }
  return dir;
}

/**
 * 断言 GUI 根可解析且可读（脚本入口最早的防御点）。
 * @returns {string} GUI 根绝对路径
 */
function assertGuiRoot() {
  const root = guiRoot();
  if (!fs.existsSync(root)) throw new Error(`[#1361] design/GUI 不存在：${root}`);
  return root;
}

module.exports = { guiRoot, assertGuiRoot, requirePlaywright, assertPageDir, PW_REL };
