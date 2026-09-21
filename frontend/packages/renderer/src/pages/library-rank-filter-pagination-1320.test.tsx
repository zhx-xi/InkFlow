/**
 * #1320 角色等级筛选 × 服务端分页契约（RED 优先）。
 *
 * 【缺陷】rank 筛选此前只作用于**已取回的一页**（LibraryItemList visibleItems 过滤当前页 50 条），
 * 而分页条 total 吃的是服务端**未筛选**总数 → 切「主角」（3 人）仍显示 2 页，
 * 且主角若分布在第 2 页则看不到（跨页漏项）。
 *
 * 【修复契约】
 * - 等级筛选上提为**受控 prop**（rank/onRankChange），页面据此向服务端下沉 ?role_rank=
 *   → total 与 items 均为筛选后口径。
 * - 后端 role_rank 存 extra JSON → 过滤须走 JSON 路径提取（user_version>=39 → json_extract，
 *   更早 → LIKE ESCAPE 双模式），count 与 items 同条件。
 * - 切等级筛选 → 页码重置回第 1 页（setPage(0)）。
 * - 筛选请求**仍带 limit/offset**（受控 prop 不得把分页退回一次性全量拉取）。
 *
 * RED 预期：现无 role_rank prop / 请求不带 role_rank → 用例 1/2/3/4 FAIL。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LibraryPage } from './library';
import { LibraryItemList } from '../components/LibraryItemList';
import { apiFetch } from '../api/client';
import { useProjectStore } from '../stores/project';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import type { LibraryItemDTO } from '../components/LibraryCreateDialog';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn(), ensureApiReady: vi.fn().mockResolvedValue(undefined) };
});

const apiFetchMock = vi.mocked(apiFetch);

const projectP1 = {
  id: 'p1', name: '青云志', tags: ['玄幻'], language: 'zh-CN', target_words: 800000, config: {},
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-05T10:00:00Z',
};

/** 角色种子：52 人（3 主角跨页分布 + 49 其他），模拟「主角只剩几个但总量 52」的真实场景 */
function seededCharacters(): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = [];
  for (let i = 0; i < 52; i += 1) {
    rows.push({ id: `c${i}`, name: `角色${i}`, description: '', extra: { role_rank: 'minor' } });
  }
  // 主角：1 个在第 1 页（第 0 位）、2 个在第 2 页（第 51、50 位）→ 跨页
  rows[0].extra = { role_rank: 'protagonist' };
  rows[50].extra = { role_rank: 'protagonist' };
  rows[51].extra = { role_rank: 'protagonist' };
  return rows;
}

/**
 * 服务端分页 + role_rank 过滤的 fake（口径 = 修复后后端）：
 * 按 role_rank 过滤 → 再切页 → total = 过滤后总数。
 */
function seedFilterAwareApi(options: { supportRoleRank: boolean }) {
  const all = seededCharacters();
  const filters: string[] = [];
  apiFetchMock.mockImplementation(async (url: string) => {
    const u = String(url);
    if (/\/maps$/.test(u)) return { items: [] };
    if (/\/world-categories$/.test(u)) return { items: [] };
    if (/\/character-groups$/.test(u)) return { items: [] };
    if (/\/characters/.test(u)) {
      const rank = new URL(u, 'http://x').searchParams.get('role_rank');
      if (rank) filters.push(rank);
      const offset = Number(new URL(u, 'http://x').searchParams.get('offset') ?? '0');
      const limit = Number(new URL(u, 'http://x').searchParams.get('limit') ?? '50');
      // 修复前后端：无 role_rank 过滤能力 → 恒全量；修复后：同条件过滤 + 同条件 count
      const filtered = options.supportRoleRank && rank
        ? all.filter((c) => (c.extra as Record<string, unknown>).role_rank === rank)
        : all;
      return { items: filtered.slice(offset, offset + limit), total: filtered.length, offset, limit };
    }
    return { items: [], total: 0, offset: 0, limit: 50 };
  });
  return { filters, all };
}

function renderLibrary() {
  return render(
    <MemoryRouter initialEntries={['/library?cat=characters']}>
      <LibraryPage />
    </MemoryRouter>,
  );
}

describe('#1320 角色等级筛选 × 分页 total 一致性', () => {
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

  it('筛选下沉服务端：切「主角」→ 请求带 role_rank=protagonist，且仍带 limit/offset', async () => {
    const { filters } = seedFilterAwareApi({ supportRoleRank: true });
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-page-info')).toBeInTheDocument());
    const tab = screen.getByTestId('character-rank-tab-protagonist');
    expect(tab).toHaveAttribute('aria-pressed', 'false');
    await userEvent.setup().click(tab);
    await waitFor(() => expect(filters).toContain('protagonist'));
    const call = apiFetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes('role_rank=')).pop();
    expect(call).toContain('limit=50');
    expect(call).toContain('offset=0');
  });

  it('筛选后 total 与页码正确：主角 3 人 → 「第 1 / 1 页 · 共 3 条」（非 52 / 2 页）', async () => {
    seedFilterAwareApi({ supportRoleRank: true });
    renderLibrary();
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 2 页 · 共 52 条');
    });
    await userEvent.setup().click(screen.getByTestId('character-rank-tab-protagonist'));
    await waitFor(() => {
      expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 1 页 · 共 3 条');
    });
  });

  it('跨页不漏项：主角分布跨页时，切「主角」能全部取到（3 个名字都在）', async () => {
    seedFilterAwareApi({ supportRoleRank: true });
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-page-info')).toBeInTheDocument());
    await userEvent.setup().click(screen.getByTestId('character-rank-tab-protagonist'));
    await waitFor(() => {
      const list = screen.getByTestId('library-list');
      expect(list).toHaveTextContent('角色0');
      // 第 2 页的两名主角若不随筛选重取 → 不可达（跨页漏项）
      expect(list).toHaveTextContent('角色50');
      expect(list).toHaveTextContent('角色51');
    });
  });

  it('切筛选重置页码：先翻到第 2 页，再切「主角」→ 请求 offset 回到 0', async () => {
    seedFilterAwareApi({ supportRoleRank: true });
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-page-info')).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByTestId('library-page-next'));
    await waitFor(() => {
      expect(apiFetchMock.mock.calls.map(([u]) => String(u)).some((u) => u.includes('offset=50'))).toBe(true);
    });
    await user.click(screen.getByTestId('character-rank-tab-protagonist'));
    await waitFor(() => {
      const last = apiFetchMock.mock.calls.map(([u]) => String(u)).filter((u) => u.includes('role_rank=')).pop();
      expect(last).toContain('offset=0');
    });
  });

  /**
   * 可证伪自证：把「筛选下沉服务端」去掉（supportRoleRank=false ≈ 修复前后端语义），
   * 断言 1/2 必须 FAIL —— 证明用例真的在测这条修复，而非恒真。
   */
  it('可证伪自证：服务端不按 role_rank 过滤时，total/页码断言必然失败（旧行为被捕获）', async () => {
    seedFilterAwareApi({ supportRoleRank: false });
    renderLibrary();
    await waitFor(() => expect(screen.getByTestId('library-page-info')).toBeInTheDocument());
    await userEvent.setup().click(screen.getByTestId('character-rank-tab-protagonist'));
    await waitFor(() => expect(screen.getByTestId('library-list')).toHaveTextContent('角色0'));
    // 旧口径：total 仍是 52、页码仍是 2 页 —— 与正确断言不符（证明断言的判别力）
    expect(screen.getByTestId('library-page-info')).toHaveTextContent('第 1 / 2 页 · 共 52 条');
    expect(screen.getByTestId('library-page-info')).not.toHaveTextContent('共 3 条');
  });

  it('等级选项卡受控：外部 rank/onRankChange 生效，且缺省仍为非受控（既有用例零改动）', async () => {
    const items = [
      { id: 'a', name: '甲', extra: { role_rank: 'protagonist' } },
      { id: 'b', name: '乙', extra: { role_rank: 'minor' } },
    ] as LibraryItemDTO[];
    const onRankChange = vi.fn();
    render(
      <LibraryItemList
        items={items}
        withCharacterExtras
        rank="protagonist"
        onRankChange={onRankChange}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onOpenDetail={vi.fn()}
      />,
    );
    // 受控值生效：对应 chip 为激活态（受控模式下**组件不自行过滤**——filtered 由服务端负责）
    expect(screen.getByTestId('character-rank-tab-protagonist')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('character-rank-tab-all')).toHaveAttribute('aria-pressed', 'false');
    // 受控模式：items 原样渲染（不二次窄化，否则跨页项被误剪）
    expect(screen.getByText('甲')).toBeInTheDocument();
    expect(screen.getByText('乙')).toBeInTheDocument();
    // 点击上抛（受控值不变，等待外部回填）
    await userEvent.setup().click(screen.getByTestId('character-rank-tab-minor'));
    expect(onRankChange).toHaveBeenCalledWith('minor');
  });
});
