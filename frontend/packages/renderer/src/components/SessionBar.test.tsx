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

vi.mock('../api/chat', () => ({
  fetchChatConversations: vi.fn(),
  createChatConversation: vi.fn(),
  saveChatMessage: vi.fn(),
}));

const fetchMock = vi.mocked(fetchChatConversations);

/** 生成距今天 daysAgo 天的 ISO 时间串（分桶入 today/week/earlier） */
function iso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return d.toISOString();
}

function item(overrides: Partial<ChatConversationDto> = {}): ChatConversationDto {
  return {
    conversation_id: 'c1',
    project_id: 'p1',
    project_name: '青云志',
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

describe('SessionBar — 点击会话项跳转 + 空态（#762）', () => {
  it('点击会话项 → /sessions?conversation_id=X', async () => {
    fetchMock.mockResolvedValue({ items: [item({ conversation_id: 'c-jump' })], total: 1 });
    const user = userEvent.setup();
    renderBar();
    await user.click(await screen.findByTestId('session-item-c-jump'));
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/sessions?conversation_id=c-jump');
  });

  it('无会话 → 空态占位 session-bar-empty', async () => {
    fetchMock.mockResolvedValue({ items: [], total: 0 });
    renderBar();
    expect(await screen.findByTestId('session-bar-empty')).toBeInTheDocument();
  });
});
