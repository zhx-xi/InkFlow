/**
 * #1376 伏笔页筛选（回收状态 · 检索）+ 优先级排序 × 服务端分页契约 —— RED 优先。
 *
 * 【设计基准】design/GUI/foreshadow/foreshadow.html（形态 A + 口径 1）/
 *   specs/f19-gui/foreshadow.md §2 表 + §3 N6-N11 + §4.3/§4.5 拍板结论。
 *
 * 【拍板口径（2026-10-01 用户确认，本契约据此）】
 *   ① 形态 A：回收状态 chip 三态 + 检索框（标题 OR 位置）+ 计数行 + 排序切换；
 *   ② 「出现章节」= 口径 1（位置文本子串）；口径 2 结构化关联本期不做（#1350 承接）；
 *   ③ 排序默认降序（优先级 高→低）；
 *   ④ 实现落点 = 服务端（状态 ?status= / 检索 ?search= / 排序 ?sort_by=&sort_desc=）
 *      —— 字段全部下沉请求，``total`` 才是筛选后口径、且跨页不漏项（#1300/#1320 已立的
 *      「筛选不得只作用于当前页」纪律；§4.3 结论：纯前端过滤会漏掉其他页的命中项）。
 *
 * 【本契约新定义的一处契约细节（§4.3 允许的两种落点之一）】
 *   单个检索框的匹配面是**并集**（标题 OR 位置），故不新增独立 ``?location=`` 参数
 *   （两个参数并存时 AND/OR 语义含混）；改为**扩展既有 ``?search=`` 的覆盖面**为
 *   title OR location（specs/f19-gui/foreshadow.md §4.3「或扩展 search 覆盖面」）。
 *   后端 RED 契约见 backend/tests/unit/infrastructure/database/test_foreshadowing_repo.py。
 *
 * 【反例守护】不选任何筛选时，请求与列表行为须与改动前一致（全量 + 原顺序 + 无额外参数）。
 *
 * RED 预期：GREEN 前无 fs-* 筛选控件、无 ?status=/?search=/?sort_* 下发 → 多条 FAIL。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn(), ensureApiReady: vi.fn().mockResolvedValue(undefined) };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '示例项目', tags: ['示例'], language: 'zh-CN', target_words: 100000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 伏笔种子（8 条；字段形状 = GET /projects/{pid}/foreshadowings 响应） */
type FsRow = {
  id: string; title: string; status: string; priority: number;
  location: string; resolved_at?: string | null;
};

const FS_ROWS: FsRow[] = [
  // 「剑」标题面命中 3 条
  { id: 'f1', title: '断剑的秘密', status: 'open', priority: 90, location: '第 11 章 · 闭关' },
  { id: 'f2', title: '残剑的来历', status: 'open', priority: 75, location: '第 13 章 · 山门' },
  // 「第 2 章」位置面命中 1 条（口径 1 正例）
  { id: 'f3', title: '旧玉佩之谜', status: 'open', priority: 60, location: '第 2 章 · 初见' },
  // 「剑」位置面命中 2 条（标题不含「剑」→ 位置面命中的可判别证据）
  { id: 'f4', title: '守陵人的来历', status: 'open', priority: 55, location: '第 10 章 · 剑冢' },
  { id: 'f5', title: '无名客的遗言', status: 'open', priority: 45, location: '开篇 · 序章梦境' },
  {
    id: 'f6', title: '藏经阁的旧穗', status: 'resolved', priority: 40,
    location: '第 8 章 · 剑阁', resolved_at: '2026-08-30T10:00:00Z',
  },
  {
    id: 'f7', title: '剑诀第九式的缺失', status: 'resolved', priority: 30,
    location: '第 6 章 · 阁楼', resolved_at: '2026-09-02T10:00:00Z',
  },
  // location 为空：口径 1 固有代价（位置面不命中），标题面照常可命中
  { id: 'f8', title: '未署名的旧信', status: 'open', priority: 20, location: '' },
];

/**
 * 修复后后端语义的 fake：status 过滤 → search（title OR location）→ 排序 → 切页，
 * total = **过滤后**总数（与 items 同条件）。缺省排序 = 降序（后端 F13 §6.3 缺省）。
 */
function seedFsApi(rows: FsRow[] = FS_ROWS) {
  apiFetchMock.mockImplementation(async (url: string) => {
    const u = String(url);
    if (/\/maps$/.test(u)) return { items: [], total: 0 };
    if (/\/world-categories$/.test(u)) return { items: [], total: 0 };
    if (/\/character-groups$/.test(u)) return { items: [], total: 0 };
    if (/\/characters/.test(u)) {
      // N10 对照分类：给 1 条角色 → characters 走列表分支（而非通用空态），
      // 才能断言「同一页面上角色列表渲染、伏笔筛选条缺席」
      return {
        items: [{ id: 'c1', name: '角色甲', description: '', extra: { role_rank: 'minor' } }],
        total: 1,
        offset: 0,
        limit: 50,
      };
    }
    if (/\/foreshadowings/.test(u)) {
      const qs = new URL(u, 'http://x').searchParams;
      const status = qs.get('status');
      const search = qs.get('search');
      const sortDesc = qs.get('sort_desc') !== 'false';
      const offset = Number(qs.get('offset') ?? '0');
      const limit = Number(qs.get('limit') ?? '50');
      let out = rows.slice();
      if (status) out = out.filter((r) => r.status === status);
      if (search) {
        const q = search.toLowerCase();
        out = out.filter(
          (r) => r.title.toLowerCase().includes(q) || (r.location ?? '').toLowerCase().includes(q),
        );
      }
      out.sort((a, b) => (a.priority - b.priority) * (sortDesc ? -1 : 1));
      return { items: out.slice(offset, offset + limit), total: out.length, offset, limit };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
}

/** 最近一次伏笔列表请求（其他分类/地图请求被过滤掉） */
function lastFsUrl(): string {
  const calls = apiFetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes('/foreshadowings'));
  return calls[calls.length - 1] ?? '';
}

/** 「第 2 次伏笔请求挂起」的可控 fake：用于断言重拉（loading）期间的挂载形态 */
function seedFsApiDeferred() {
  let release: (() => void) | null = null;
  let fsCalls = 0;
  apiFetchMock.mockImplementation(async (url: string) => {
    const u = String(url);
    if (/\/maps$/.test(u)) return { items: [], total: 0 };
    if (/\/world-categories$/.test(u)) return { items: [], total: 0 };
    if (/\/character-groups$/.test(u)) return { items: [], total: 0 };
    if (/\/characters/.test(u)) return { items: [], total: 0, offset: 0, limit: 50 };
    if (/\/foreshadowings/.test(u)) {
      fsCalls += 1;
      const qs = new URL(u, 'http://x').searchParams;
      if (fsCalls === 1) {
        return { items: FS_ROWS, total: FS_ROWS.length, offset: 0, limit: 50 };
      }
      const status = qs.get('status');
      const filtered = status ? FS_ROWS.filter((r) => r.status === status) : FS_ROWS;
      await new Promise<void>((resolve) => {
        release = resolve;
      });
      return { items: filtered, total: filtered.length, offset: Number(qs.get('offset') ?? '0'), limit: 50 };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
  return { release: () => release?.() };
}

/** 渲染设定库页（foreshadow 分类）并等首帧数据到达 */
async function renderForeshadowPage() {
  const utils = render(
    <MemoryRouter initialEntries={['/library?cat=foreshadow']}>
      <LibraryPage />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByTestId('library-page-info')).toBeInTheDocument());
  return utils;
}

beforeEach(() => {
  vi.clearAllMocks();
  useThemeStore.setState({ lang: 'zh' });
  useProjectStore.setState({
    projects: [projectP1],
    currentProjectId: 'p1',
    loadProjects: vi.fn().mockResolvedValue(undefined),
    selectProject: vi.fn(),
  });
  useToastStore.setState({ toasts: [] });
  window.localStorage.clear();
});

describe('#1376 反例守护：不选任何筛选 = 改动前行为', () => {
  it('无筛选时请求不带 status/search/sort_*，仍带 limit/offset；列表全量按默认（降序）', async () => {
    seedFsApi();
    await renderForeshadowPage();

    const url = lastFsUrl();
    expect(url).toContain('limit=50');
    expect(url).toContain('offset=0');
    expect(url).not.toContain('status=');
    expect(url).not.toContain('search=');
    expect(url).not.toContain('sort_desc=');
    expect(url).not.toContain('sort_by=');

    // 全量 8 条 + 原顺序（优先级降序，首条 90）
    expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 8 / 共 8 条');
    const rows = screen.getAllByText(/断剑的秘密|残剑的来历|守陵人的来历|未署名的旧信/);
    expect(rows.length).toBeGreaterThanOrEqual(4);
    expect(screen.getByTestId('library-list').textContent?.indexOf('断剑的秘密')).toBeLessThan(
      screen.getByTestId('library-list').textContent?.indexOf('未署名的旧信') ?? -1,
    );
  });
});

describe('#1376 状态筛选：服务端下沉（total 跟随筛选口径）', () => {
  it('点「未回收」→ 请求带 status=open 且仍带 limit/offset；列表仅剩未回收（8→6）', async () => {
    seedFsApi();
    await renderForeshadowPage();

    await userEvent.setup().click(screen.getByTestId('fs-status-chip-open'));
    await waitFor(() => expect(lastFsUrl()).toContain('status=open'));

    const url = lastFsUrl();
    expect(url).toContain('limit=50');
    expect(url).toContain('offset=0');
    await waitFor(() => {
      const list = screen.getByTestId('library-list');
      // 已回收的两条被服务端滤掉
      expect(list).not.toHaveTextContent('藏经阁的旧穗');
      expect(list).not.toHaveTextContent('剑诀第九式的缺失');
      expect(list).toHaveTextContent('断剑的秘密');
    });
    expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 6 / 共 6 条');
  });

  it('分页 total 随筛选重算：#1320 同类语义（未回收 6 条 → 「共 6 条」，非未筛选 8）', async () => {
    seedFsApi();
    await renderForeshadowPage();
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 1 页 · 共 8 条');
    });

    const user = userEvent.setup();
    await user.click(screen.getByTestId('fs-status-chip-open'));
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 1 页 · 共 6 条');
    });

    await user.click(screen.getByTestId('fs-status-chip-resolved'));
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 1 页 · 共 2 条');
    });

    // 回到「全部」= 不传 status → 全量口径
    await user.click(screen.getByTestId('fs-status-chip-all'));
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 1 页 · 共 8 条');
    });
    expect(lastFsUrl()).not.toContain('status=');
  });

  it('切换状态筛选 → 页码归零（新数据集不沿用上一数据集页码）', async () => {
    seedFsApi();
    await renderForeshadowPage();

    await userEvent.setup().click(screen.getByTestId('fs-status-chip-open'));
    await waitFor(() => expect(lastFsUrl()).toContain('status=open'));
    expect(lastFsUrl()).toContain('offset=0');
  });
});

describe('#1376 排序：默认降序 · 切换升序 · 与分页共存', () => {
  it('默认「优先级 高→低」→ 不发排序参数（= 后端缺省）；切换后请求 sort_desc=false 且顺序反转', async () => {
    seedFsApi();
    await renderForeshadowPage();

    expect(screen.getByTestId('fs-sort-label')).toHaveTextContent('优先级 高→低');
    expect(lastFsUrl()).not.toContain('sort_desc=');

    await userEvent.setup().click(screen.getByTestId('fs-sort-toggle'));
    await waitFor(() => expect(lastFsUrl()).toContain('sort_desc=false'));

    expect(lastFsUrl()).toContain('sort_by=priority');
    await waitFor(() => {
      expect(screen.getByTestId('fs-sort-label')).toHaveTextContent('优先级 低→高');
    });
    // 升序：优先级最低者（20）在前
    const text = screen.getByTestId('library-list').textContent ?? '';
    expect(text.indexOf('未署名的旧信')).toBeLessThan(text.indexOf('断剑的秘密'));

    // 再点 → 回默认降序（不再下发 sort_desc=false）
    await userEvent.setup().click(screen.getByTestId('fs-sort-toggle'));
    await waitFor(() => {
      expect(screen.getByTestId('fs-sort-label')).toHaveTextContent('优先级 高→低');
    });
    await waitFor(() => expect(lastFsUrl()).not.toContain('sort_desc=false'));
  });

  it('排序作用于全量（服务端）并与分页共存：翻页请求仍带排序参数（跨页一致）', async () => {
    // 52 条：分页必须存在第 2 页（每页 50）
    const many: FsRow[] = Array.from({ length: 52 }, (_, i) => ({
      id: `m${i}`, title: `伏笔条目${i}`, status: 'open', priority: 52 - i, location: `第 ${i} 章`,
    }));
    seedFsApi(many);
    await renderForeshadowPage();
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 2 页 · 共 52 条');
    });

    const user = userEvent.setup();
    await user.click(screen.getByTestId('fs-sort-toggle'));
    await waitFor(() => expect(lastFsUrl()).toContain('sort_desc=false'));

    await user.click(screen.getByTestId('library-page-next'));
    await waitFor(() => expect(lastFsUrl()).toContain('offset=50'));
    // 排序参数随每次分页请求下发（排序由服务端对全量生效，不是当页重排）
    expect(lastFsUrl()).toContain('sort_desc=false');
    expect(lastFsUrl()).toContain('sort_by=priority');
  });
});

describe('#1376 检索（口径 1）：标题 OR 位置 文本子串', () => {
  it('输入「剑」→ 请求带 search=剑；命中 = 标题 3 条 + 位置 2 条（并集 5），计数与列表同步', async () => {
    seedFsApi();
    await renderForeshadowPage();

    await userEvent.setup().type(screen.getByTestId('fs-search-input'), '剑');
    await waitFor(() => expect(lastFsUrl()).toContain('search='));

    // 服务端收到的检索词与输入一致（编码后解码等值）
    const qs = new URL(lastFsUrl(), 'http://x').searchParams;
    expect(qs.get('search')).toBe('剑');
    // 检索仍走服务端分页（不退回一次性全量）
    expect(qs.get('limit')).toBe('50');

    await waitFor(() => {
      const list = screen.getByTestId('library-list');
      // 标题面命中
      expect(list).toHaveTextContent('断剑的秘密');
      expect(list).toHaveTextContent('剑诀第九式的缺失');
      // 位置面命中（标题不含「剑」→ 仅可能由 location 文本命中）
      expect(list).toHaveTextContent('守陵人的来历');
      expect(list).toHaveTextContent('藏经阁的旧穗');
      // 未命中的条目缺席（位置空 / 无子串）
      expect(list).not.toHaveTextContent('未署名的旧信');
      expect(list).not.toHaveTextContent('无名客的遗言');
    });
    expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 5 / 共 5 条');
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('共 5 条');
    });
  });

  it('位置面可判别：查询「第 2 章」命中 1 条（该条仅位置含查询串）', async () => {
    seedFsApi();
    await renderForeshadowPage();

    await userEvent.setup().type(screen.getByTestId('fs-search-input'), '第 2 章');
    await waitFor(() => {
      expect(new URL(lastFsUrl(), 'http://x').searchParams.get('search')).toBe('第 2 章');
    });
    await waitFor(() => {
      const list = screen.getByTestId('library-list');
      expect(list).toHaveTextContent('旧玉佩之谜');
      expect(list).not.toHaveTextContent('断剑的秘密');
    });
    expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 1 / 共 1 条');
  });

  it('清空检索框 → 请求不再带 search（恢复全量）', async () => {
    seedFsApi();
    await renderForeshadowPage();

    const user = userEvent.setup();
    const input = screen.getByTestId('fs-search-input');
    await user.type(input, '剑');
    await waitFor(() => expect(lastFsUrl()).toContain('search='));

    await user.clear(input);
    await waitFor(() => expect(lastFsUrl()).not.toContain('search='));
    await waitFor(() => expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 8 / 共 8 条'));
  });
});

describe('#1376 空结果态（N9）：不复用「还没有伏笔」空态', () => {
  it('筛选后 0 条 → fs-noresult（文案 + 清除筛选），library-tab-empty 不参与', async () => {
    seedFsApi();
    await renderForeshadowPage();

    const user = userEvent.setup();
    await user.click(screen.getByTestId('fs-status-chip-resolved'));
    await waitFor(() => expect(lastFsUrl()).toContain('status=resolved'));
    await user.type(screen.getByTestId('fs-search-input'), '第 2 章');
    await waitFor(() => {
      expect(new URL(lastFsUrl(), 'http://x').searchParams.get('search')).toBe('第 2 章');
    });

    await waitFor(() => {
      expect(screen.getByTestId('fs-noresult')).toBeInTheDocument();
    });
    expect(screen.getByTestId('fs-noresult')).toHaveTextContent('当前筛选条件下没有匹配的伏笔');
    expect(screen.queryByTestId('library-tab-empty')).not.toBeInTheDocument();
    expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 0 / 共 0 条');
    // 筛选条仍在（用户可改条件 / 清除）
    expect(screen.getByTestId('foreshadow-filters')).toBeInTheDocument();
  });

  it('点「清除筛选」→ status/检索清空、恢复全量；不改变排序方向', async () => {
    seedFsApi();
    await renderForeshadowPage();

    const user = userEvent.setup();
    await user.click(screen.getByTestId('fs-sort-toggle'));
    await waitFor(() => expect(lastFsUrl()).toContain('sort_desc=false'));

    await user.click(screen.getByTestId('fs-status-chip-resolved'));
    await user.type(screen.getByTestId('fs-search-input'), '第 2 章');
    await waitFor(() => expect(screen.getByTestId('fs-noresult')).toBeInTheDocument());

    await user.click(screen.getByTestId('fs-clear-filters'));
    await waitFor(() => expect(screen.queryByTestId('fs-noresult')).not.toBeInTheDocument());

    await waitFor(() => {
      const url = lastFsUrl();
      expect(url).not.toContain('status=');
      expect(url).not.toContain('search=');
    });
    const url = lastFsUrl();
    // 排序方向不被清除（N9 边界：清除筛选不改变排序方向）
    expect(url).toContain('sort_desc=false');
    expect(screen.getByTestId('fs-sort-label')).toHaveTextContent('优先级 低→高');
    expect(screen.getByTestId('fs-status-chip-all')).toHaveAttribute('aria-pressed', 'true');
    expect((screen.getByTestId('fs-search-input') as HTMLInputElement).value).toBe('');
    await waitFor(() => expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 8 / 共 8 条'));
  });
});

describe('#1376 重拉期间筛选条保持挂载（输入框不失焦、不吞键）', () => {
  it('逐字输入跨越防抖窗口（每键 400ms > 250ms）→ 输入累积不丢字、检索词完整下发', async () => {
    seedFsApi();
    await renderForeshadowPage();

    // 每键间隔 > 防抖窗口 → 每字都会触发一次重拉；若重拉期骨架卸载整卡，第二字将落进已卸载的输入框
    const user = userEvent.setup({ delay: 400 });
    await user.type(screen.getByTestId('fs-search-input'), '断剑');

    expect((screen.getByTestId('fs-search-input') as HTMLInputElement).value).toBe('断剑');
    await waitFor(() => {
      expect(new URL(lastFsUrl(), 'http://x').searchParams.get('search')).toBe('断剑');
    });
  });

  it('重拉期间（响应未返回）筛选条与列表卡保持挂载（不出现整卡骨架替换）', async () => {
    const { release } = seedFsApiDeferred();
    await renderForeshadowPage();
    const before = apiFetchMock.mock.calls.length;

    await userEvent.setup().click(screen.getByTestId('fs-status-chip-open'));
    // 第 2 次请求已发出但挂起 → loading 态
    await waitFor(() => expect(apiFetchMock.mock.calls.length).toBeGreaterThan(before));

    // 🔴 loading 期间整卡不得被骨架替换：文本输入框必须仍在（否则重拉即失焦 / IME 组合中断）
    expect(screen.getByTestId('fs-search-input')).toBeInTheDocument();
    expect(screen.getByTestId('foreshadow-filters')).toBeInTheDocument();

    release();
    await waitFor(() => expect(screen.getByTestId('fs-count')).toHaveTextContent('显示 6 / 共 6 条'));
    expect(screen.getByTestId('fs-search-input')).toBeInTheDocument();
  });
});

describe('#1376 作用域（N10）：筛选条仅 foreshadow 分类渲染', () => {
  it('切到 characters 分类 → 不渲染 foreshadow-filters / fs-count', async () => {
    seedFsApi();
    await renderForeshadowPage();
    expect(screen.getByTestId('foreshadow-filters')).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('tab', { name: '角色' }));
    await waitFor(() => expect(screen.getByTestId('character-rank-tabs')).toBeInTheDocument());
    expect(screen.queryByTestId('foreshadow-filters')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fs-count')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fs-sort-toggle')).not.toBeInTheDocument();
  });
});
