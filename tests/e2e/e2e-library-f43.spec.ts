/**
 * 设定库域 E2E（当前为导航流中的设定库断言，ADR-028 E2 将补用例）
 *
 * 运行方式：
 *   cd frontend
 *   pnpm --filter renderer build          # 生成 renderer/dist/
 *   pnpm --filter inkflow-electron build  # 生成 out/main.js
 *   pnpm --filter inkflow-electron test:e2e e2e-library
 *
 * 基建（复用 electron-pages.spec.ts 模式）：
 * - _electron.launch + waitKernelInfo（__kernelInfo 注入轮询，窗口交互前必须先等内核就绪，否则 401）
 * - 真实内核 + 真实渲染：创建项目 = 真实 POST 落库；用例间用唯一书名 `E2E-<场景>-<ts>` 隔离数据
 * - 每个用例独立 launch app（workers=1，串行）
 */
import path from 'node:path';
import {
  test,
  expect,
  _electron as electron,
  type ElectronApplication,
  type Page,
} from '@playwright/test';

// 本文件位于 <repoRoot>/tests/e2e/ → 仓库根 → frontend 目录
const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FRONTEND_DIR = path.join(REPO_ROOT, 'frontend');
const MAIN_JS = 'packages/electron/out/main.js';

interface KernelInfo {
  pid: number;
  port: number;
  token: string;
}

/** 读主进程测试钩子（dev 模式暴露 globalThis.__kernelInfo，spec §3.6） */
async function readKernelInfo(
  app: ElectronApplication
): Promise<KernelInfo | undefined> {
  return app.evaluate(() => (globalThis as { __kernelInfo?: KernelInfo }).__kernelInfo);
}

/** 等待内核就绪（轮询 __kernelInfo 注入；CI 冷启动 chromadb+内核 >20s，默认 30s） */
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

/** 启动应用（Electron + 真实内核），等待窗口与内核就绪 */
async function launchApp(): Promise<{ app: ElectronApplication; window: Page; kernel: KernelInfo }> {
  const app = await electron.launch({ args: [MAIN_JS], cwd: FRONTEND_DIR });
  const window = await app.firstWindow();
  const kernel = await waitKernelInfo(app);
  return { app, window, kernel };
}

/** 侧边栏导航（AppNav 链接文本：项目 / 写作 / 设定库 / 设置；NavLink 与 Agent 快捷 Link 均为 role=link） */
async function gotoNav(window: Page, name: string): Promise<void> {
  await window.getByRole('link', { name }).click();
}

/**
 * 通过 UI 创建项目：new-project-btn → 对话框填书名 → 「创建」。
 * 契约：创建成功 → navigate('/writing')，等待写作页 project-tree 出现。
 */
async function createProjectViaUi(window: Page, name: string): Promise<void> {
  await window.getByTestId('new-project-btn').click();
  const dlg = window.getByRole('dialog');
  // getByLabel 通过关联 label / aria-label 查找（dialog 内唯一）
  await window.getByLabel('书名').fill(name);
  await dlg.getByRole('button', { name: '创建' }).click();
  await expect(window.getByTestId('project-tree')).toBeVisible({ timeout: 15_000 });
}

async function kernelFetch(
  info: KernelInfo,
  pathname: string,
  init?: { method?: string; body?: unknown }
): Promise<Response> {
  return fetch(`http://127.0.0.1:${info.port}${pathname}`, {
    method: init?.method ?? 'GET',
    headers: {
      'X-InkFlow-Token': info.token,
      'Content-Type': 'application/json',
    },
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
}

/** 从内核项目列表按书名查 id（断言存在） */

async function findProjectId(kernel: KernelInfo, name: string): Promise<string> {
  const res = await kernelFetch(kernel, '/api/v1/projects');
  expect(res.ok).toBe(true);
  const data = (await res.json()) as { items: Array<{ id: string; name: string }> };
  const project = data.items.find((p) => p.name === name);
  expect(project, `项目「${name}」应已创建并持久化`).toBeTruthy();
  return project!.id;
}


test.describe.configure({ timeout: 120_000 });


// ────────────────────────────────────────────────────────────────
// F43 P1/P3/P4 E2E（E2E-A1..A9，2026-08-14）——从 e2e-library.spec.ts 拆分（900 行护栏）
// 角色等级/标签 / 世界观树+分类筛选 / 跨项目复制 / 大纲三级+章关联 / 时间线双序+检查
// ────────────────────────────────────────────────────────────────

// ────────────────────────────────────────────────────────────────

/** F43 P1 预置：世界观节点（parent 用名称引用，顺序保证父先建）；返回 name → id（内核 UUID） */
async function presetWorldNodes(
  kernel: KernelInfo,
  pid: string,
  nodes: Array<{ name: string; category: string; parent?: string }>,
): Promise<Record<string, string>> {
  const ids: Record<string, string> = {};
  for (const n of nodes) {
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/world-settings`, {
      method: 'POST',
      body: {
        name: n.name,
        category: n.category,
        content: 'E2E 预置',
        ...(n.parent !== undefined ? { parent_id: ids[n.parent] } : {}),
      },
    });
    expect(res.status).toBe(201);
    const created = (await res.json()) as { id: string };
    ids[n.name] = created.id;
  }
  return ids;
}

/** #389 预置：世界观分类实体（POST /world-categories；chips 来源 = world_categories 表） */
async function presetWorldCategories(
  kernel: KernelInfo,
  pid: string,
  names: string[],
): Promise<void> {
  for (const name of names) {
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/world-categories`, {
      method: 'POST',
      body: { name },
    });
    expect(res.status).toBe(201);
  }
}

/** F43 P3 预置：大纲节点（parent 用名称引用）；返回 name → id */
async function presetOutlineNodes(
  kernel: KernelInfo,
  pid: string,
  nodes: Array<{ name: string; level: string; parent?: string; chapter_id?: string }>,
): Promise<Record<string, string>> {
  const ids: Record<string, string> = {};
  for (const n of nodes) {
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/outlines`, {
      method: 'POST',
      body: {
        name: n.name,
        level: n.level,
        ...(n.parent !== undefined ? { parent_id: ids[n.parent] } : {}),
        ...(n.chapter_id !== undefined ? { chapter_id: n.chapter_id } : {}),
      },
    });
    expect(res.status).toBe(201);
    const created = (await res.json()) as { id: string };
    ids[n.name] = created.id;
  }
  return ids;
}

/** F43 P4 预置：时间线事件；返回事件 id（内核 UUID） */
async function presetTimelineEvent(
  kernel: KernelInfo,
  pid: string,
  body: {
    title: string;
    time_value?: number | null;
    time_unit?: string;
    time_display?: string;
    narrative_position?: number | null;
  },
): Promise<string> {
  const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/timeline/events`, {
    method: 'POST',
    body,
  });
  expect(res.status).toBe(201);
  return ((await res.json()) as { id: string }).id;
}

/** #389：世界观 tab 停列表页（分类 chips + 树 + 复制）；「地图视图」按钮才是进工作台唯一入口 */
async function openWorldTabPlain(window: Page): Promise<void> {
  await window.getByRole('tab', { name: '世界观' }).click();
  await expect(window.getByTestId('library-list')).toBeVisible({ timeout: 15_000 });
}

/** F43 P4：时间线事件行序 = tl-check-one-<id> 的 DOM 顺序 → 事件 id 序列（契约：每行一个检查按钮） */
async function timelineRowIds(window: Page): Promise<string[]> {
  return window
    .locator('[data-testid^="tl-check-one-"]')
    .evaluateAll((els) => els.map((el) => el.getAttribute('data-testid')!.replace('tl-check-one-', '')));
}

test('设定库：角色创建带等级+标签（E2E-A1）——选「重要配角」+ 回车建标签 → 保存 → 徽标/标签 chips + 内核落库', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-角色创建-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    // 角色分类默认空态 → CTA 打开创建对话框
    await expect(window.getByTestId('library-tab-empty')).toBeVisible({ timeout: 15_000 });
    await window.getByTestId('library-tab-empty-cta').click();
    const dialog = window.getByTestId('library-create-dialog');
    await expect(dialog).toBeVisible({ timeout: 15_000 });

    // D1 必填 gate：仅填名称不选等级 → 保存 disabled
    const save = dialog.getByTestId('library-create-save');
    await expect(save).toBeDisabled();
    await dialog.getByTestId('library-create-name').fill('叶孤城');
    await expect(save).toBeDisabled();
    // 选等级「重要配角」（exact：避免子串同时命中「配角」档）
    await dialog.getByTestId('library-create-rank').click();
    await window.getByRole('option', { name: '重要配角', exact: true }).click();
    // 标签：输入回车创建（E15）
    const tagInput = dialog.getByTestId('lib-tag-input');
    await tagInput.fill('主角团');
    await tagInput.press('Enter');
    await expect(dialog.getByTestId('lib-tag-chip-主角团')).toBeVisible();
    await expect(save).toBeEnabled();
    await save.click();

    // 保存 → 对话框关闭 + 列表刷新出现新角色
    await expect(dialog).toBeHidden();
    await expect(window.getByTestId('library-list')).toContainText('叶孤城', { timeout: 15_000 });

    // 内核落库：POST body extra 生效（role_rank=major + groups）
    let item: { id: string; extra?: { role_rank?: string; groups?: string[] } } | undefined;
    await expect
      .poll(
        async () => {
          const r = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`);
          const data = (await r.json()) as {
            items: Array<{ id: string; name: string; extra?: { role_rank?: string; groups?: string[] } }>;
          };
          item = data.items.find((c) => c.name === '叶孤城');
          return item?.extra?.role_rank;
        },
        { timeout: 15_000 },
      )
      .toBe('major');
    expect(item?.extra?.groups).toContain('主角团');
    // 列表行等级徽标（lib-rank-<id>）+ 标签区（lib-tags-<id>）
    await expect(window.getByTestId(`lib-rank-${item!.id}`)).toContainText('重要配角');
    await expect(window.getByTestId(`lib-tags-${item!.id}`)).toContainText('主角团');
  } finally {
    await app.close();
  }
});

test('设定库：角色编辑改等级+标签（E2E-A2）——PATCH 整体替换 extra → 徽标/标签刷新 + 内核落库', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-角色编辑-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    // 预置角色（带完整 extra：role_rank 必填 gate，编辑保存才 enabled）
    const res = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`, {
      method: 'POST',
      body: { name: '林晚', personality: 'E2E', extra: { role_rank: 'major', groups: ['主角团', '青云宗'] } },
    });
    expect(res.status).toBe(201);
    const cid = ((await res.json()) as { id: string }).id;

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-list')).toContainText('林晚', { timeout: 15_000 });
    await window.getByTestId(`lib-edit-${cid}`).click();
    const dialog = window.getByTestId('library-create-dialog');
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    // 编辑预填：等级「重要配角」+ 标签 chip 存在
    await expect(dialog.getByTestId('library-create-rank')).toContainText('重要配角');
    await expect(dialog.getByTestId('lib-tag-chip-主角团')).toBeVisible();

    // 改等级 → 配角（exact）
    await dialog.getByTestId('library-create-rank').click();
    await window.getByRole('option', { name: '配角', exact: true }).click();
    // 移除标签「青云宗」（chip 内 ×）+ 回车新增「新标签」
    await dialog.getByTestId('lib-tag-chip-青云宗').getByRole('button').click();
    await expect(dialog.getByTestId('lib-tag-chip-青云宗')).toHaveCount(0);
    const tagInput = dialog.getByTestId('lib-tag-input');
    await tagInput.fill('新标签');
    await tagInput.press('Enter');
    await expect(dialog.getByTestId('lib-tag-chip-新标签')).toBeVisible();
    await dialog.getByTestId('library-create-save').click();

    // 时间敏感项最先断言：保存指示「已保存」（2s 自动隐藏）
    await expect(window.getByTestId('lib-save-indicator')).toHaveText('已保存', { timeout: 15_000 });
    await expect(dialog).toBeHidden();
    // 列表行徽标/标签刷新（PATCH 后 reloadKey 重新拉取）
    await expect(window.getByTestId(`lib-rank-${cid}`)).toHaveText('配角', { timeout: 15_000 });
    const tags = window.getByTestId(`lib-tags-${cid}`);
    await expect(tags).toContainText('新标签');
    await expect(tags).not.toContainText('青云宗');
    // 内核落库：PATCH extra 整体替换（spec §3.2）生效
    await expect
      .poll(
        async () => {
          const r = await kernelFetch(kernel, `/api/v1/projects/${pid}/characters`);
          const data = (await r.json()) as {
            items: Array<{ id: string; extra?: { role_rank?: string; groups?: string[] } }>;
          };
          return data.items.find((c) => c.id === cid)?.extra;
        },
        { timeout: 15_000 },
      )
      .toEqual({ role_rank: 'minor', groups: ['主角团', '新标签'] });
  } finally {
    await app.close();
  }
});

test('设定库：世界观树层级 + toggle 收起/展开（E2E-A3）——parent_id 预置 → 默认展开 → 收起子树隐藏', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-世界树-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const ids = await presetWorldNodes(kernel, pid, [
      { name: '九州', category: '地图' },
      { name: '中州', category: '地图', parent: '九州' },
      { name: '东荒', category: '地图', parent: '九州' },
      { name: '昆仑山', category: '秘境', parent: '中州' },
    ]);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await openWorldTabPlain(window);
    // 有子节点才渲染 toggle（九州/中州有子；东荒/昆仑山叶子无）
    await expect(window.getByTestId(`world-tree-toggle-${ids['九州']}`)).toBeVisible();
    await expect(window.getByTestId(`world-tree-toggle-${ids['中州']}`)).toBeVisible();
    await expect(window.getByTestId(`world-tree-toggle-${ids['东荒']}`)).toHaveCount(0);
    await expect(window.getByTestId(`world-tree-toggle-${ids['昆仑山']}`)).toHaveCount(0);
    // 默认展开：子节点可见
    await expect(window.getByTestId('library-list')).toContainText('中州');
    // 点 toggle 收起 → 子树整体不渲染
    await window.getByTestId(`world-tree-toggle-${ids['九州']}`).click();
    await expect(window.getByTestId('library-list')).not.toContainText('中州');
    await expect(window.getByTestId('library-list')).not.toContainText('昆仑山');
    // 再点展开 → 恢复
    await window.getByTestId(`world-tree-toggle-${ids['九州']}`).click();
    await expect(window.getByTestId('library-list')).toContainText('中州', { timeout: 15_000 });
  } finally {
    await app.close();
  }
});

test('设定库：世界观分类筛选 toggle（E2E-A4）——点 chip 仅显示该分类顶层（含子树）→ 再点恢复', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-世界筛选-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    // #389：先建分类实体（chips 来源 = world_categories），再建条目（category 匹配分类实体）
    await presetWorldCategories(kernel, pid, ['势力', '组织', '门派']);
    // #567 单例：一项目一根——根「世界观」+ 分类元素作其子孙（多根已废）
    await presetWorldNodes(kernel, pid, [
      { name: '世界观', category: '' },
      { name: '九州', category: '势力', parent: '世界观' },
      { name: '中州', category: '势力', parent: '九州' },
      { name: '宗门', category: '组织', parent: '世界观' },
      { name: '昆仑派', category: '门派', parent: '世界观' },
    ]);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await openWorldTabPlain(window);
    // #389：chips = 分类实体（无「地图」——地图归地图工作台）
    for (const cat of ['势力', '组织', '门派']) {
      await expect(window.getByTestId(`world-cat-filter-${cat}`)).toBeVisible();
    }
    await expect(window.getByTestId('world-cat-filter-地图')).toHaveCount(0);
    await expect(window.getByTestId('world-cat-filter-全部')).toHaveCount(0);
    // 默认展示所有顶层
    await expect(window.getByTestId('library-list')).toContainText('宗门');
    await expect(window.getByTestId('library-list')).toContainText('昆仑派');
    // 点「势力」→ 仅该分类顶层（含子树）显示，其余隐藏
    await window.getByTestId('world-cat-filter-势力').click();
    await expect(window.getByTestId('world-cat-filter-势力')).toHaveAttribute('aria-pressed', 'true');
    await expect(window.getByTestId('library-list')).toContainText('九州');
    await expect(window.getByTestId('library-list')).toContainText('中州');
    await expect(window.getByTestId('library-list')).not.toContainText('宗门');
    await expect(window.getByTestId('library-list')).not.toContainText('昆仑派');
    // 再点同 chip → 取消筛选全部恢复
    await window.getByTestId('world-cat-filter-势力').click();
    await expect(window.getByTestId('world-cat-filter-势力')).toHaveAttribute('aria-pressed', 'false');
    await expect(window.getByTestId('library-list')).toContainText('宗门', { timeout: 15_000 });
    await expect(window.getByTestId('library-list')).toContainText('昆仑派');
  } finally {
    await app.close();
  }
});

test('设定库：世界观行内复制到目标项目（E2E-A5）——subtree 默认 → CopyDialog 选目标 → toast 创建数 + 目标落库', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-复制-${Date.now()}`;
    const targetName = `${name}-目标`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    // 目标项目经内核 API 创建（当前项目 = UI 创建的那个；复制目标排除自身 E20）
    const targetRes = await kernelFetch(kernel, '/api/v1/projects', {
      method: 'POST',
      body: { name: targetName },
    });
    expect(targetRes.status).toBe(201);
    const targetPid = ((await targetRes.json()) as { id: string }).id;
    // #567 单例：一项目一根——根「世界观」+ 分类元素作其子孙（多根已废）
    const ids = await presetWorldNodes(kernel, pid, [
      { name: '世界观', category: '' },
      { name: '九州', category: '地图', parent: '世界观' },
      { name: '中州', category: '地图', parent: '九州' },
      { name: '宗门', category: '组织', parent: '世界观' },
    ]);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await openWorldTabPlain(window);
    // 行内复制 → CopyDialog（subtree 模式：范围 chips 可见）
    await window.getByTestId(`world-copy-${ids['九州']}`).click();
    const dialog = window.getByTestId('world-copy-dialog');
    await expect(dialog).toBeVisible({ timeout: 15_000 });
    await expect(dialog.getByTestId('world-copy-scope-subtree')).toBeVisible();
    await expect(dialog.getByTestId('world-copy-scope-self')).toBeVisible();
    // 目标项目：排除当前项目（E20）
    await dialog.getByTestId('world-copy-target').click();
    await expect(window.getByRole('option', { name: targetName })).toBeVisible();
    await expect(window.getByRole('option', { name, exact: true })).toHaveCount(0); // 当前项目不可选（E20；targetName 含 name 子串 → 必须 exact）
    await window.getByRole('option', { name: targetName }).click();
    // 确认 → POST copy → ok toast（时间敏感项先断言）+ 对话框关闭
    await dialog.getByTestId('world-copy-ok').click();
    await expect(window.getByRole('status')).toContainText(targetName, { timeout: 15_000 });
    await expect(window.getByTestId('world-copy-dialog')).toHaveCount(0);
    // 内核落库：subtree（九州+中州 2 条；宗门未选不入目标）复制到目标项目
    await expect
      .poll(
        async () => {
          const r = await kernelFetch(kernel, `/api/v1/projects/${targetPid}/world-settings`);
          const data = (await r.json()) as { total: number };
          return data.total;
        },
        { timeout: 15_000 },
      )
      .toBe(2);
  } finally {
    await app.close();
  }
});

test('设定库：大纲三级树渲染 + 层级标签 + 展开收起（E2E-A6）——overall/volume/chapter 嵌套', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-大纲树-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    const ids = await presetOutlineNodes(kernel, pid, [
      { name: '大纲整体', level: 'overall' },
      { name: '第一卷', level: 'volume', parent: '大纲整体' },
      { name: '第一章', level: 'chapter', parent: '第一卷' },
    ]);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await window.getByRole('tab', { name: '大纲' }).click();
    const tree = window.getByTestId('outline-tree');
    await expect(tree).toBeVisible({ timeout: 15_000 });
    // 三级节点嵌套（子节点 DOM 在父节点内）
    const overall = tree.getByTestId(`outline-overall-${ids['大纲整体']}`);
    await expect(overall).toBeVisible();
    const volume = overall.getByTestId(`outline-volume-${ids['第一卷']}`);
    await expect(volume).toBeVisible();
    const chapter = volume.getByTestId(`outline-chapter-${ids['第一章']}`);
    await expect(chapter).toBeVisible();
    // 层级标签（整体/卷/章）
    await expect(overall).toContainText('整体');
    await expect(volume).toContainText('卷');
    await expect(chapter).toContainText('章');
    // 各层新增按钮（＋卷/＋章/＋情节点）
    await expect(overall.getByTestId(`outline-add-volume-${ids['大纲整体']}`)).toHaveText('＋卷');
    await expect(volume.getByTestId(`outline-add-chapter-${ids['第一卷']}`)).toHaveText('＋章');
    await expect(chapter.getByTestId(`outline-add-point-${ids['第一章']}`)).toHaveText('＋情节点');
    // 展开/收起：点 overall toggle → 卷隐藏；再点恢复（toggle 本身仍在）
    await window.getByTestId(`outline-toggle-${ids['大纲整体']}`).click();
    await expect(volume).toHaveCount(0);
    await expect(window.getByTestId(`outline-toggle-${ids['大纲整体']}`)).toBeVisible();
    await window.getByTestId(`outline-toggle-${ids['大纲整体']}`).click();
    await expect(volume).toBeVisible({ timeout: 15_000 });
  } finally {
    await app.close();
  }
});

test('设定库：大纲章关联徽标（E2E-A7）——chapter_id 关联 → 📎+章节标题；未关联 → 「关联章节」按钮', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-章关联-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    // 预置写作章节（chapter_id → title 映射数据源，GET /chapters）
    const chRes = await kernelFetch(kernel, `/api/v1/projects/${pid}/chapters`, {
      method: 'POST',
      body: { title: '第3章' },
    });
    expect(chRes.status).toBe(201);
    const chId = ((await chRes.json()) as { id: string }).id;
    const ids = await presetOutlineNodes(kernel, pid, [
      { name: '第一章', level: 'chapter', chapter_id: chId },
      { name: '第二章', level: 'chapter' },
    ]);

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await window.getByRole('tab', { name: '大纲' }).click();
    await expect(window.getByTestId('outline-tree')).toBeVisible({ timeout: 15_000 });
    // 已关联 → 📎 徽标 + 章节标题 + title 提示；无「关联章节」按钮
    const badge = window.getByTestId(`outline-chapter-ref-${ids['第一章']}`);
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('📎');
    await expect(badge).toContainText('第3章');
    await expect(badge).toHaveAttribute('title', '已关联写作章节，点击可在写作页打开');
    await expect(window.getByTestId(`outline-chapter-link-${ids['第一章']}`)).toHaveCount(0);
    // 未关联 → 「关联章节」按钮（lib.chapterLink）；无 📎 徽标
    const linkBtn = window.getByTestId(`outline-chapter-link-${ids['第二章']}`);
    await expect(linkBtn).toBeVisible();
    await expect(linkBtn).toHaveText('关联章节');
    await expect(window.getByTestId(`outline-chapter-ref-${ids['第二章']}`)).toHaveCount(0);
  } finally {
    await app.close();
  }
});

test('设定库：时间线双序切换（E2E-A8）——默认叙事序 → 世界序按 time_value 升序重排 → 切回', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-时间线-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    // 可区分双序：世界序 evC(100)→evA(300)→evB(None 末尾)；叙事序 evB(1)→evC(2)→evA(3)
    const evA = await presetTimelineEvent(kernel, pid, {
      title: '甲 登基', time_value: 300, time_unit: 'year', time_display: '300 年', narrative_position: 3,
    });
    const evB = await presetTimelineEvent(kernel, pid, {
      title: '乙 失踪', time_value: null, time_display: '未知', narrative_position: 1,
    });
    const evC = await presetTimelineEvent(kernel, pid, {
      title: '丙 初现', time_value: 100, time_unit: 'year', time_display: '100 年', narrative_position: 2,
    });

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await window.getByRole('tab', { name: '时间线' }).click();
    // 工具栏 + 双序 chips（默认叙事序激活）+ 图例
    await expect(window.getByTestId('timeline-toolbar')).toBeVisible({ timeout: 15_000 });
    await expect(window.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'true');
    await expect(window.getByTestId('tl-view-world')).toHaveAttribute('aria-pressed', 'false');
    await expect(window.getByTestId('tl-legend')).toHaveText('点=叙事顺序 · 时间轴=世界内时间');
    // 默认叙事序：narrative_position 升序（T1）
    await expect.poll(async () => timelineRowIds(window), { timeout: 15_000 }).toEqual([evB, evC, evA]);
    // 切世界序：time_value 升序、None 末尾（T2；本地切换零请求由单测 T2/T3 覆盖）
    await window.getByTestId('tl-view-world').click();
    await expect.poll(async () => timelineRowIds(window), { timeout: 15_000 }).toEqual([evC, evA, evB]);
    await expect(window.getByTestId('tl-view-world')).toHaveAttribute('aria-pressed', 'true');
    await expect(window.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'false');
    // 切回叙事序（T3）
    await window.getByTestId('tl-view-narrative').click();
    await expect.poll(async () => timelineRowIds(window), { timeout: 15_000 }).toEqual([evB, evC, evA]);
    await expect(window.getByTestId('tl-view-narrative')).toHaveAttribute('aria-pressed', 'true');
  } finally {
    await app.close();
  }
});

test('设定库：时间线整体检查（E2E-A9）——tl-check-all → consistent → toast「未发现矛盾事件」', async () => {
  const { app, window, kernel } = await launchApp();
  try {
    const name = `E2E-时间线检查-${Date.now()}`;
    await createProjectViaUi(window, name);
    const pid = await findProjectId(kernel, name);
    // 叙事序 time_value 单调不减（None 跳过）→ 确定性 consistent=true
    await presetTimelineEvent(kernel, pid, {
      title: '甲 登基', time_value: 300, time_unit: 'year', time_display: '300 年', narrative_position: 3,
    });
    await presetTimelineEvent(kernel, pid, {
      title: '乙 失踪', time_value: null, time_display: '未知', narrative_position: 1,
    });
    await presetTimelineEvent(kernel, pid, {
      title: '丙 初现', time_value: 100, time_unit: 'year', time_display: '100 年', narrative_position: 2,
    });

    await gotoNav(window, '设定库');
    await expect(window.getByTestId('library-page')).toBeVisible({ timeout: 15_000 });
    await window.getByRole('tab', { name: '时间线' }).click();
    await expect(window.getByTestId('tl-check-all')).toBeVisible({ timeout: 15_000 });
    // 时间敏感项先断言：ok toast（~2s 自动消失）
    await window.getByTestId('tl-check-all').click();
    await expect(window.getByRole('status')).toContainText('未发现矛盾事件', { timeout: 15_000 });
  } finally {
    await app.close();
  }
});
