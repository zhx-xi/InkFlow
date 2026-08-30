/**
 * SessionBar 契约测试（#762 左侧独立会话栏） — 对照 .hermes/plans/contract-session-rightcol.md T1 节。
 *
 * 契约 testid：
 * - session-bar（根，data-collapsed 折叠态）
 * - session-bar-toggle（折叠/展开按钮）
 * - session-time-{today|week|earlier}（时间分组容器）
 * - session-item-{conversation_id}（会话项）
 * - session-item-archived（归档徽标）
 * - session-bar-empty（空态）
 *
 * 行为：
 * - 挂载调 fetchChatConversations({ includeDeleted: true }) → 按 updated_at 分组（today/week/earlier），各桶降序。
 * - 点击会话项 → navigate('/sessions?conversation_id=X')。
 * - 折叠/展开持久化 localStorage key `session-bar.collapsed`。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { SessionBar } from './SessionBar';
import type { ChatConversationDto } from '../api/chat';
import { fetchChatConversations } from '../api/chat';
import { useThemeStore } from '../stores/theme';
import { useChapterStore } from '../stores/chapter';

vi.mock('../api/chat', () => ({
  fetchChatConversations: vi.fn(),
  createChatConversation: vi.fn(),
  saveChatMessage: vi.fn(),
}));

const fetchMock = vi.mocked(fetchChatConversations);

/** #770：会话 title 字段（GREEN api/chat.ts 为 ChatConversationDto 补 title: string；测试契约先行） */
type ChatConversationWithTitle = ChatConversationDto & { title: string };

/** 生成距今天 daysAgo 天的 ISO 时间串（分桶入 today/week/earlier） */
function iso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString();
}

function item(overrides: Partial<ChatConversationWithTitle> = {}): ChatConversationWithTitle {
  return {
    conversation_id: 'c1',
    project_id: 'p1',
    project_name: '青云志',
    title: '默认标题',
    last_message: '默认消息',
    message_count: 1,
    is_deleted: false,
    updated_at: iso(0),
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}{location.search}</div>;
}

function renderBar(props: { projectId?: string | null } = {}) {
  return render(
    <MemoryRouter initialEntries={['/writing']}>
      <SessionBar {...props} />
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: 'paper', bg: 'default', lang: 'zh' });
  fetchMock.mockReset();
  // #770：章节树复位（title 匹配章节导航依赖 useChapterStore，防跨用例泄漏）
  useChapterStore.setState({
    volumes: [],
    chapters: [],
    treeProjectId: null,
    currentChapterId: null,
    content: '',
    loading: false,
    error: null,
  });
});

describe('SessionBar — 列表按时间分组渲染（#762）', () => {
  it('today/week/earlier 三分组，每项显示 last_message + message_count', async () => {
    fetchMock.mockResolvedValue({
      items: [
        item({ conversation_id: 'c-today', last_message: '今日消息摘要', message_count: 3, updated_at: iso(0) }),
        item({ conversation_id: 'c-week', last_message: '本周消息', message_count: 8, updated_at: iso(3) }),
        item({ conversation_id: 'c-earlier', last_message: '更早消息', message_count: 12, updated_at: iso(30) }),
      ],
      total: 3,
    });
    renderBar();
    // 三组齐全
    expect(await screen.findByTestId('session-time-today')).toBeInTheDocument();
    expect(screen.getByTestId('session-time-week')).toBeInTheDocument();
    expect(screen.getByTestId('session-time-earlier')).toBeInTheDocument();
    // today 项：last_message + message_count
    const todayItem = screen.getByTestId('session-item-c-today');
    expect(todayItem).toHaveTextContent('今日消息摘要');
    expect(todayItem).toHaveTextContent('3 条');
  });

  it('挂载调 fetchChatConversations({ includeDeleted: true })', async () => {
    fetchMock.mockResolvedValue({ items: [], total: 0 });
    renderBar();
    await screen.findByTestId('session-bar-empty');
    expect(fetchMock).toHaveBeenCalledWith({ includeDeleted: true });
  });
});

describe('SessionBar — 归档徽标（#762 is_deleted）', () => {
  it('is_deleted=true 会话显示「已归档」徽标', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-arch', is_deleted: true, last_message: '已归档消息' })],
      total: 1,
    });
    renderBar();
    const arch = await screen.findByTestId('session-item-c-arch');
    expect(within(arch).getByTestId('session-item-archived')).toBeInTheDocument();
  });
});

describe('SessionBar — 折叠/展开持久化（#762 localStorage）', () => {
  it('默认展开；点折叠 → data-collapsed=true + localStorage true；再点展开恢复', async () => {
    fetchMock.mockResolvedValue({ items: [item({ conversation_id: 'c1' })], total: 1 });
    const user = userEvent.setup();
    renderBar();
    const bar = screen.getByTestId('session-bar');
    // 默认展开
    expect(bar).not.toHaveAttribute('data-collapsed');
    // 折叠
    await user.click(screen.getByTestId('session-bar-toggle'));
    expect(screen.getByTestId('session-bar')).toHaveAttribute('data-collapsed', 'true');
    expect(localStorage.getItem('session-bar.collapsed')).toBe('true');
    // 展开恢复
    await user.click(screen.getByTestId('session-bar-toggle'));
    expect(screen.getByTestId('session-bar')).not.toHaveAttribute('data-collapsed');
    expect(localStorage.getItem('session-bar.collapsed')).toBe('false');
  });
});

describe('SessionBar — 点击会话项跳转 + 空态（#762/#770）', () => {
  it('#770：点击会话项 → title 匹配不到章节（无章节数据）→ /writing?conversation_id=X（全局 chat 页）', async () => {
    fetchMock.mockResolvedValue({ items: [item({ conversation_id: 'c-jump' })], total: 1 });
    const user = userEvent.setup();
    renderBar();
    await user.click(await screen.findByTestId('session-item-c-jump'));
    // RED：当前实现跳 /sessions?conversation_id=c-jump → FAIL
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing?conversation_id=c-jump');
  });

  it('无会话 → 空态占位 session-bar-empty', async () => {
    fetchMock.mockResolvedValue({ items: [], total: 0 });
    renderBar();
    expect(await screen.findByTestId('session-bar-empty')).toBeInTheDocument();
  });
});

/* ============================== #770 SessionBar 增量（title 展示 / title 匹配导航） ============================== */

describe('SessionBar — #770 会话 title 展示（空回退 last_message）', () => {
  it('会话项展示 title（非空）', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-title', title: '第十二章 剑心蒙尘', last_message: '最后消息' })],
      total: 1,
    });
    renderBar();
    const entry = await screen.findByTestId('session-item-c-title');
    // RED：当前实现展示 last_message（'最后消息'）→ FAIL
    expect(entry).toHaveTextContent('第十二章 剑心蒙尘');
  });

  it('title 为空 → 回退展示 last_message（守护用例，当前实现天然通过）', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-fallback', title: '', last_message: '最后消息' })],
      total: 1,
    });
    renderBar();
    const entry = await screen.findByTestId('session-item-c-fallback');
    expect(entry).toHaveTextContent('最后消息');
  });
});

describe('SessionBar — #770 点击导航（title 匹配章节 → /writing?chapter_id；否则 → /writing?conversation_id）', () => {
  it('title 与当前项目章节标题同名 → /writing?chapter_id=<章ID>', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-match', title: '第十二章 剑心蒙尘' })],
      total: 1,
    });
    // 播种当前项目章节（GREEN 读 useChapterStore；测试契约同步播种）
    useChapterStore.setState({
      chapters: [{ id: 'ch1', title: '第十二章 剑心蒙尘', volume_id: null, order_index: 0, word_count: 0 }],
      treeProjectId: 'p1',
    });
    const user = userEvent.setup();
    renderBar({ projectId: 'p1' });
    await user.click(await screen.findByTestId('session-item-c-match'));
    // RED：当前实现跳 /sessions?conversation_id=c-match → FAIL
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing?chapter_id=ch1');
  });

  it('title 匹配不到章节（改名 / 全局会话）→ /writing?conversation_id=<会话ID>（全局 chat 页）', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-nomatch', title: '改名后的会话' })],
      total: 1,
    });
    useChapterStore.setState({
      chapters: [{ id: 'ch1', title: '第十二章 剑心蒙尘', volume_id: null, order_index: 0, word_count: 0 }],
      treeProjectId: 'p1',
    });
    const user = userEvent.setup();
    renderBar({ projectId: 'p1' });
    await user.click(await screen.findByTestId('session-item-c-nomatch'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/writing?conversation_id=c-nomatch');
  });
});
/* ============================== #825 会话列表不显示 + title 布局 + 折叠按钮位置（UI 元素必须出现） ============================== */

describe('SessionBar — #825 会话列表显示 + 按项目过滤（UI 元素必须出现）', () => {
  it('mock 返回会话 → 标题文案出现（非「暂无数据」），会话条目 testid 存在', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-p1', title: '蜀山，我是掌门', last_message: '帮我看看第12章氛围', project_id: 'p1' })],
      total: 1,
    });
    renderBar({ projectId: 'p1' });
    expect(await screen.findByText('蜀山，我是掌门')).toBeInTheDocument();
    expect(screen.getByTestId('session-item-c-p1')).toBeInTheDocument();
    expect(screen.queryByTestId('session-bar-empty')).not.toBeInTheDocument();
  });

  it('按项目过滤：projectId=p1 仅显示 p1 会话，p2 会话不出现（本地过滤，后端不收 project_id）', async () => {
    fetchMock.mockResolvedValue({
      items: [
        item({ conversation_id: 'c-p1', title: '蜀山，我是掌门', project_id: 'p1' }),
        item({ conversation_id: 'c-p2', title: '第一章', project_id: 'p2' }),
      ],
      total: 2,
    });
    renderBar({ projectId: 'p1' });
    expect(await screen.findByText('蜀山，我是掌门')).toBeInTheDocument();
    expect(screen.queryByText('第一章')).not.toBeInTheDocument();
    expect(screen.queryByTestId('session-item-c-p2')).not.toBeInTheDocument();
  });
});

describe('SessionBar — #825 title 布局（一次一个清晰标题，无冗余重复）', () => {
  it('title 与 last_message 相同 → 只显示一个标题（不重复展示），无冗余底部小 title', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-dup', title: '蜀山，我是掌门', last_message: '蜀山，我是掌门', project_id: 'p1' })],
      total: 1,
    });
    renderBar({ projectId: 'p1' });
    const entry = await screen.findByTestId('session-item-c-dup');
    expect(within(entry).getByText('蜀山，我是掌门')).toBeInTheDocument();
    expect(within(entry).queryAllByText('蜀山，我是掌门').length).toBe(1);
  });

  it('title 与 last_message 不同 → last_message 作为副行保留（#762 契约）', async () => {
    fetchMock.mockResolvedValue({
      items: [item({ conversation_id: 'c-diff', title: '蜀山，我是掌门', last_message: '帮我看看第12章氛围', project_id: 'p1' })],
      total: 1,
    });
    renderBar({ projectId: 'p1' });
    const entry = await screen.findByTestId('session-item-c-diff');
    expect(within(entry).getByText('帮我看看第12章氛围')).toBeInTheDocument();
  });
});

describe('SessionBar — #825 折叠按钮位置（「会话」标题行最右）', () => {
  it('session-bar-toggle 位于 session-bar-header（justify-between）内', async () => {
    fetchMock.mockResolvedValue({ items: [item({ conversation_id: 'c-b' })], total: 1 });
    renderBar();
    const header = await screen.findByTestId('session-bar-header');
    expect(header.className).toContain('justify-between');
    expect(header.contains(screen.getByTestId('session-bar-toggle'))).toBe(true);
  });
});
