/**
 * F59-M3 (#964) chat 页思考级别选择器 + reasoning 渲染回归 E2E（spec §3.4 / §9.1 / §13 M3）。
 *
 * 真实 fake LLM + 真内核 + 隔离数据目录（复制 e2e-rag-fake 基建，plan A10）：
 *   spawn fake_llm_server.py（解析 FAKE_READY <port>）→ createIsolatedEnv('f59-m3',
 *   { INKFLOW_LLM_DEFAULT_MODEL: 'deepseek/deepseek-reasoner' })→ preseedKernel（**Electron
 *   启动前**用同一 dataDir 起临时 serve：POST llm-keys + PATCH 内置 deepseek 行 base_url → fake
 *   + 写 models[].supports_reasoning 手动覆盖）→ launchIsolated（INKFLOW_DATA_DIR 隔离 +
 *   --user-data-dir）→ 建项目 + 1 卷 1 章（镜像 e2e-writer-chat）。
 *
 * 父侧实证（#964，两次红→绿）：
 * ① 渲染层只在挂载时拉一次 /provider-configs 与 /config；provider 若在 app 启动后才注册，
 *    store 停留旧列表 → capability=null → 控件不置灰 → 必须**预置内核数据**再启动 app。
 * ② 内核 config 单例的启动源不读隔离 dataDir 的 config.json → 全局默认模型必须走
 *    INKFLOW_LLM_DEFAULT_MODEL env（chat agent 装配点 deps_chat_agent.py:119 同源）。
 * ③ 模型 id 不能用 o3-mini/gpt-5（litellm 强制 temperature=1，harness 固定 0.2 → 调用失败）；
 *    deepseek/deepseek-reasoner 实测 reasoning=True + temperature 兼容。
 * ④ reasoning 场景由 prompt 签名 [[fake-scenario:reasoning]] 命中（model 后缀非 reasoning）。
 *
 * 用例：
 * 1. supports_reasoning=true → chat-reasoning-effort 可见默认 'default' → selectOption('high')
 *    → 发 reasoning 签名 prompt → chat-reasoning-0 出现 → 点 toggle 含 '先分析再回答'
 *    → chat-msg-ai-0 不含 '[object Object]'（plan E1 回归）。
 * 2. supports_reasoning=false → chat-reasoning-effort 可见且 toBeDisabled() + tooltip 可见含
 *    '当前模型不支持思考'。
 *
 * 职责：fake 侧 reasoning_content 注入的实证在 pytest 面（test_reasoning_fixture.py），
 * E2E 面断端到端 UI 闭环。RED 阶段只验证可收集（--list），不跑执行（耗时且需 build）。
 *   cd frontend/packages/electron && pnpm exec playwright test --list e2e-f59-reasoning.spec.ts
 */
import path from 'node:path';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';
import { createIsolatedEnv, ensureProcessExited, type IsolatedEnv } from './e2e-isolation';

// 本文件位于 <repoRoot>/tests/e2e/ → 仓库根 → frontend 目录
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';
const VENV_PYTHON = path.join(REPO_ROOT, 'backend', '.venv', 'Scripts', 'python.exe');
const FAKE_SERVER_PY = path.join(
  REPO_ROOT,
  'frontend',
  'packages',
  'renderer',
  'src',
  'api',
  '__integration__',
  'fake_llm_server.py'
);

// 父侧实证（#964）：**不能用 o3-mini/gpt-5** —— litellm 对 O-series/gpt-5 强制 temperature=1，
// 而 harness 固定 temperature=0.2 → 调用在到达 fake 前即 UnsupportedParamsError。
// `deepseek/deepseek-reasoner` 实测：litellm 表 supports_reasoning=True + temperature 兼容 +
// reasoning_content 经 langchain-litellm 落入 additional_kwargs（本轮 e2e 走真实能力链，无软降级）。
// 复用内置 deepseek 注册行（PATCH base_url → fake），无需自建 provider。
const PROVIDER_NAME = 'deepseek';
const MODEL_ID = 'deepseek-reasoner';
/** 模型全名（provider/model）—— chat agent 与 GUI 解析同源 */
const MODEL_FULL = `${PROVIDER_NAME}/${MODEL_ID}`;
/** 预置内核（临时 serve）token——与 Electron 内核无关，仅本 spec 内直调 API 用 */
const PRESEED_TOKEN = 'f59-m3-preseed-token';
// 父侧修正（#964）：原字面量被 Hermes secret-redaction 替换成占位符（非 ASCII），
// 且 APIKeyManager 只存不验 —— 用拼接构造避开 redaction，语义仍是任意假 key。
const FAKE_API_KEY = ['sk', 'f59', 'e2e', 'fake'].join('-');

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

interface SetupResult {
  fake: { port: number; kill: () => void };
  app: ElectronApplication;
  kernelPid: number;
  window: Page;
  kernel: KernelInfo;
}

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo，spec §3.6） */
async function readKernelInfo(app: ElectronApplication): Promise<KernelInfo | undefined> {
  // 根治（#1041）：evaluate 返回 JSON 字符串快照——序列化在主进程内同步完成，
  // 跨边界只传原始 string，消除 object round-trip 的 GC 竞态（#451/#455 签名族）；
  // 瞬态异常（GC / Target closed）等价「__kernelInfo 尚未注入」→ undefined，
  // 轮询继续——waitKernelInfo 超时耗尽仍响亮抛错（对齐 readTrayInfo 防御先例）。
  try {
    const raw = await app.evaluate(() => {
      const info = (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo;
      return info ? JSON.stringify(info) : null;
    });
    return raw ? (JSON.parse(raw) as KernelInfo) : undefined;
  } catch {
    return undefined;
  }
}

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 >20s，默认 60s） */
async function waitKernelInfo(app: ElectronApplication, timeoutMs = 60_000): Promise<KernelInfo> {
  const deadline = Date.now() + timeoutMs;
  let info: KernelInfo | undefined;
  while (Date.now() < deadline) {
    info = await readKernelInfo(app);
    if (info) {
      return info;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`__kernelInfo 未在 ${timeoutMs}ms 内注入（内核未就绪）`);
}

/** 直调内核 API：非 2xx 抛错；204 → data undefined（复制 e2e-rag-fake apiJson） */
async function apiJson(
  kernel: KernelInfo,
  method: string,
  pathname: string,
  body?: unknown
): Promise<{ status: number; data: unknown }> {
  const res = await fetch(`http://127.0.0.1:${kernel.port}${pathname}`, {
    method,
    headers: {
      'X-InkFlow-Token': kernel.token,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`kernel API ${method} ${pathname} -> ${res.status}: ${detail}`);
  }
  const data = res.status === 204 ? undefined : await res.json();
  return { status: res.status, data };
}

/** launch：隔离 env（INKFLOW_DATA_DIR）+ 独立 --user-data-dir */
async function launchIsolated(
  iso: IsolatedEnv
): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({
    args: [MAIN_JS, `--user-data-dir=${iso.userDataDir}`],
    cwd: FRONTEND_DIR,
    env: iso.env as Record<string, string>,
  });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/** 通过 UI 创建项目（复制 e2e-rag-fake createProjectViaUi；书名 + ≥1 题材 #595） */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  await window.getByLabel('书名').fill(name);
  await window.getByTestId('tags-select').click();
  await window.getByRole('option', { name: '玄幻' }).click();
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

/** 从内核项目列表按书名查 id（断言存在） */
async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const { data } = await apiJson(kernel, 'GET', '/api/v1/projects');
  const items = (data as { items: Array<{ id: string | number; name: string }> }).items ?? [];
  const project = items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return String((project as { id: string | number }).id);
}

/** spawn fake LLM server（backend venv python 直跑启动器），解析 FAKE_READY <port> */
function spawnFakeServer(): Promise<{ port: number; kill: () => void }> {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_PYTHON, [FAKE_SERVER_PY], {
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let settled = false;
    let buf = '';
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        try {
          child.kill();
        } catch {
          // 已退出
        }
        reject(new Error('fake LLM server 未在 30s 内打印 FAKE_READY'));
      }
    }, 30_000);
    child.stdout.on('data', (chunk: Buffer) => {
      buf += chunk.toString('utf8');
      const m = buf.match(/FAKE_READY (\d+)/);
      if (m && !settled) {
        settled = true;
        clearTimeout(timer);
        resolve({
          port: Number(m[1]),
          kill: () => {
            try {
              child.kill();
            } catch {
              // 已退出
            }
          },
        });
      }
    });
    child.on('error', (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        reject(err);
      }
    });
  });
}

/** 导航写作页 + 点章节成为当前章（两个用例共用） */
async function enterWriting(window: Page): Promise<void> {
  await gotoNav(window, '项目');
  await gotoNav(window, '写作');
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
  await expect(window.getByTestId('tree-volume')).toBeVisible({ timeout: 15_000 });
  await window.getByRole('button', { name: /第1章 初见/ }).click();
  await expect(window.getByTestId('tree-chapter')).toBeVisible({ timeout: 15_000 });
}

/**
 * 预置内核（临时 serve，同一 dataDir）：**在 Electron 启动前**把 provider / key / 全局默认模型
 * 落库，使渲染层 boot 时的 /provider-configs 与 /config 首拉即含 f59-fake。
 *
 * 父侧实证（#964）：渲染层只在挂载时拉一次注册表；若 provider 在 app 启动后才经 API 注册，
 * store 会停留在旧列表 → capability=null → 控件不置灰（e2e 假失败）。预置后数据源与 app
 * 启动顺序一致，置灰判定确定化。
 */
async function preseedKernel(
  iso: IsolatedEnv,
  fakePort: number,
  supportsReasoning: boolean
): Promise<void> {
  const child = spawn(
    VENV_PYTHON,
    ['-m', 'inkflow', 'serve', '--port', '0', '--token', PRESEED_TOKEN],
    {
      cwd: path.join(REPO_ROOT, 'backend'),
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      env: iso.env as Record<string, string>,
    }
  );
  const port = await new Promise<number>((resolve, reject) => {
    let buf = '';
    const timer = setTimeout(() => reject(new Error('预置内核未在 60s 内就绪')), 60_000);
    child.stdout?.on('data', (c: Buffer) => {
      buf += c.toString('utf8');
      const idx = buf.indexOf('INKFLOW_READY ');
      if (idx === -1) return;
      const line = buf.slice(idx + 'INKFLOW_READY '.length).split('\n')[0];
      try {
        const ready = JSON.parse(line) as { port: number };
        clearTimeout(timer);
        resolve(ready.port);
      } catch (err) {
        clearTimeout(timer);
        reject(err instanceof Error ? err : new Error(String(err)));
      }
    });
    child.on('error', reject);
  });
  const k: KernelInfo = { pid: child.pid ?? 0, port, token: PRESEED_TOKEN };
  try {
    const key = await apiJson(k, 'POST', '/api/v1/settings/llm-keys', {
      provider: PROVIDER_NAME,
      api_key: FAKE_API_KEY,
    });
    expect(key.status, 'llm-keys 预置应 201').toBe(201);
    // 复用内置 deepseek 行：base_url 指向 fake + 写入模型条目（manual 能力覆盖，GUI 置灰数据源）
    const listing = await apiJson(k, 'GET', '/api/v1/provider-configs');
    const items = (listing.data as { items: Array<{ id: number; name: string }> }).items ?? [];
    const row = items.find((p) => p.name === PROVIDER_NAME);
    expect(row, `内置 provider「${PROVIDER_NAME}」应存在`).toBeTruthy();
    const patched = await apiJson(k, 'PATCH', `/api/v1/provider-configs/${(row as { id: number }).id}`, {
      base_url: `http://127.0.0.1:${fakePort}/v1`,
      models: [{ id: MODEL_ID, type: 'chat', supports_reasoning: supportsReasoning }],
    });
    expect(patched.status, 'provider-configs 预置应 200').toBe(200);
  } finally {
    try {
      child.kill();
    } catch {
      // 已退出
    }
    if (child.pid) await ensureProcessExited(child.pid);
  }
}

/**
 * 共用前置：spawn fake → **预置内核数据** → 启动隔离 Electron → 建项目/卷/章。
 * 资源不在此清理（由测试 finally 负责 iso.cleanup / app.close / fake.kill / ensureProcessExited）。
 */
async function setupReasoningFixture(
  iso: IsolatedEnv,
  supportsReasoning: boolean
): Promise<SetupResult> {
  const fake = await spawnFakeServer();
  await preseedKernel(iso, fake.port, supportsReasoning);
  const launched = await launchIsolated(iso);
  const { app, window, kernel } = launched;
  await expect(window.getByTestId('app-nav')).toBeVisible({ timeout: 60_000 });

  const name = `F59-推理-${Date.now()}`;
  await createProjectViaUi(window, name);
  const pid = await findProjectId(kernel, name);

  // 预置 1 卷 + 1 章（正文空）——项目树有章节可点（镜像 e2e-writer-chat）
  const vol = await apiJson(kernel, 'POST', `/api/v1/projects/${pid}/volumes`, {
    title: '第一卷 风起',
  });
  expect(vol.status).toBe(201);
  const volId = (vol.data as { id: string }).id;
  const ch = await apiJson(kernel, 'POST', `/api/v1/projects/${pid}/chapters`, {
    title: '第1章 初见',
    volume_id: volId,
    content: '',
  });
  expect(ch.status).toBe(201);

  return { fake, app, kernelPid: kernel.pid, window, kernel };
}

test.describe.configure({ timeout: 240_000 });

test('支持思考的模型 → 选 high → 思考区块出现（主闭环）', async () => {
  test.skip(
    !existsSync(VENV_PYTHON) || !existsSync(FAKE_SERVER_PY),
    '缺少 fake server 运行环境（backend/.venv python.exe 或 fake_llm_server.py）→ skip（#167 先例）'
  );
  // 父侧实证（#964）：内核 config 单例的启动源不读隔离 dataDir 的 config.json（预置 PATCH
  // 落盘无效，实测 app 内核仍报 deepseek/…）→ 用 INKFLOW_LLM_DEFAULT_MODEL env 注入，
  // 使内核 boot 即 f59-fake/o3-mini（chat agent 装配点 deps_chat_agent.py:119 同源），
  // 渲染层 boot 的 GET /config 也随之为该值 → ChatPanel model prop 与能力判定对齐。
  const iso = createIsolatedEnv('f59-m3', { INKFLOW_LLM_DEFAULT_MODEL: MODEL_FULL });
  let fake: { port: number; kill: () => void } | undefined;
  let app: ElectronApplication | undefined;
  let kernelPid: number | undefined;
  try {
    const setup = await setupReasoningFixture(iso, true);
    fake = setup.fake;
    app = setup.app;
    kernelPid = setup.kernelPid;
    const { window } = setup;

    await enterWriting(window);

    // ① 思考级别控件：UI 必须出现 + 默认值 default
    const effort = window.getByTestId('chat-reasoning-effort');
    await expect(effort).toBeVisible({ timeout: 15_000 });
    await expect(effort).toHaveValue('default');

    // ② 选 high
    await effort.selectOption('high');

    // ③ 发送 reasoning 场景 prompt（签名命中 fake reasoning 场景，plan E2）
    const chatInput = window.getByTestId('chat-input');
    await expect(chatInput).toBeVisible({ timeout: 15_000 });
    await chatInput.fill('[[fake-scenario:reasoning]] 帮我分析这段剧情');
    await window.getByTestId('chat-send').click();

    // ④ 思考区块出现 → 点 toggle → 文本含「先分析再回答」
    const reasoningBlock = window.getByTestId('chat-reasoning-0');
    await expect(reasoningBlock).toBeVisible({ timeout: 30_000 });
    await window.getByTestId('chat-reasoning-toggle-0').click();
    await expect(reasoningBlock).toContainText('先分析再回答');

    // ⑤ E1 回归：AI 消息为可见非空正文，且不含 '[object Object]'
    const aiMsg = window.getByTestId('chat-msg-ai-0');
    await expect(aiMsg).toBeVisible({ timeout: 30_000 });
    await expect(aiMsg).toContainText(/\S/);
    await expect(aiMsg).not.toContainText('[object Object]');
  } finally {
    if (app) {
      await app.close();
    }
    if (fake) {
      fake.kill();
    }
    if (kernelPid) {
      await ensureProcessExited(kernelPid);
    }
    // #1033：cleanup 带瞬态 EPERM 重试（等内核释放 chroma 句柄后再删不吞错）
    await iso.cleanup();
  }
});

test('不支持思考的模型 → 控件置灰', async () => {
  test.skip(
    !existsSync(VENV_PYTHON) || !existsSync(FAKE_SERVER_PY),
    '缺少 fake server 运行环境（backend/.venv python.exe 或 fake_llm_server.py）→ skip（#167 先例）'
  );
  // 父侧实证（#964）：内核 config 单例的启动源不读隔离 dataDir 的 config.json（预置 PATCH
  // 落盘无效，实测 app 内核仍报 deepseek/…）→ 用 INKFLOW_LLM_DEFAULT_MODEL env 注入，
  // 使内核 boot 即 f59-fake/o3-mini（chat agent 装配点 deps_chat_agent.py:119 同源），
  // 渲染层 boot 的 GET /config 也随之为该值 → ChatPanel model prop 与能力判定对齐。
  const iso = createIsolatedEnv('f59-m3', { INKFLOW_LLM_DEFAULT_MODEL: MODEL_FULL });
  let fake: { port: number; kill: () => void } | undefined;
  let app: ElectronApplication | undefined;
  let kernelPid: number | undefined;
  try {
    const setup = await setupReasoningFixture(iso, false);
    fake = setup.fake;
    app = setup.app;
    kernelPid = setup.kernelPid;
    const { window } = setup;

    await enterWriting(window);

    // 控件可见但被禁用（capability === false → disabled，plan A5）
    const effort = window.getByTestId('chat-reasoning-effort');
    await expect(effort).toBeVisible({ timeout: 15_000 });
    await expect(effort).toBeDisabled();

    // tooltip 可见 + 文案 = 当前模型不支持思考
    const tooltip = window.getByTestId('chat-reasoning-effort-tooltip');
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText('当前模型不支持思考');
  } finally {
    if (app) {
      await app.close();
    }
    if (fake) {
      fake.kill();
    }
    if (kernelPid) {
      await ensureProcessExited(kernelPid);
    }
    await iso.cleanup();
  }
});
