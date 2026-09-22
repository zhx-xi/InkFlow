/**
 * #1374 时间线筛选（按章 / 按事件类型）—— 组件级契约。
 *
 * 【spec 依据】specs/f19-gui/timeline.md §2（筛选行）+ §3 N9：
 * - 按章筛选：全部章节 / 各章 / 未分章（✅ 数据面 source_chapter_id + 章节列表）
 * - 按事件类型（正叙/倒叙/插叙）：✅ timeline_flag 自由文本，包含式匹配
 *   （#1323 G6 词表：flashback/倒叙/回忆 → 倒叙；flashforward/插叙/预叙 → 插叙；
 *   其余（含空串/未标记自由文本如「梦境」）→ 正叙）
 * - 筛选对**两序共用**（切序不丢筛选）；重置 = 「全部」
 * - #1320 教训：筛选后 total/页数一致 —— 本列表非分页（一次全量获取），
 *   客户端筛选不引入分页器 → 无 total 语义问题（节点数 == 过滤后事件数）
 *
 * 【testid 契约（GREEN 必须提供）】
 * - tl-filter-chapter / tl-filter-panel / tl-fp-item-<all|chapterId|__none__>
 * - tl-filter-type / tl-filter-type-panel / tl-tp-item-<all|normal|flashback|flashforward>
 * - 按钮文案：「章：<label>」/「类型：<label>」（label = 全部 / 章节标题 / 未分章 / 正叙…）
 *
 * 【RED 预期】筛选按钮/面板/过滤行为全类 FAIL（当前实现无筛选）；
 * 零 SyntaxError / ReferenceError / TypeError。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimelineView, type TimelineEventDTO } from './TimelineView';
import { apiFetch } from '../api/client';
import { useThemeStore } from '../stores/theme';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);

/**
 * Seed（章 × 类型可正交区分）：
 * - evA：章 c11 · 正叙（'' 未标记）· 世界序 10 · 叙事序 1
 * - evC：章 c12 · 倒叙（'倒叙'）· 世界序 20 · 叙事序 2
 * - evD：章 c12 · 插叙（'插叙'）· 世界序 30 · 叙事序 3
 * - evB：未分章 · 正叙（'梦境' 未标记自由文本）· 未知时间 · 叙事序 4
 */
const evA: TimelineEventDTO = {
  id: 'evA', title: '甲事件', time_value: 10, time_unit: '年', time_display: '青元历 10 年',
  narrative_position: 1, timeline_flag: '', source_chapter_id: 'c11',
};
const evC: TimelineEventDTO = {
  id: 'evC', title: '乙事件（倒叙）', time_value: 20, time_unit: '年', time_display: '青元历 20 年',
  narrative_position: 2, timeline_flag: '倒叙', source_chapter_id: 'c12',
};
const evD: TimelineEventDTO = {
  id: 'evD', title: '丙事件（插叙）', time_value: 30, time_unit: '年', time_display: '青元历 30 年',
  narrative_position: 3, timeline_flag: '插叙', source_chapter_id: 'c12',
};
const evB: TimelineEventDTO = {
  id: 'evB', title: '丁事件（未分章）', time_value: null, time_unit: null, time_display: '',
  narrative_position: 4, timeline_flag: '梦境', source_chapter_id: null,
};

const CHAPTER_TITLES: Record<string, string> = {
  c11: '第十一章 剑心为何物',
  c12: '第十二章 夜访剑冢',
};

function renderView() {
  return render(
    <TimelineView
      projectId="p1"
      eventTimeline={[evA, evC, evD, evB]}
      narrativeOrder={[evA, evC, evD, evB]}
      chapterTitles={CHAPTER_TITLES}
      chapterOrder={['c11', 'c12']}
    />,
  );
}

function nodeIds(): string[] {
  return screen
    .getAllByTestId(/^tl-axis-node-/)
    .map((el) => el.getAttribute('data-testid')!.replace('tl-axis-node-', ''));
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ lang: 'zh' });
});

describe('#1374 时间线筛选（按章 / 按事件类型，两序共用）', () => {
  it('F1 默认「全部」：章/类型按钮显示「章：全部」「类型：全部」，四条事件全显示', async () => {
    renderView();
    expect(screen.getByTestId('tl-filter-chapter')).toHaveTextContent('章：全部');
    expect(screen.getByTestId('tl-filter-type')).toHaveTextContent('类型：全部');
    expect(nodeIds()).toEqual(['evA', 'evC', 'evD', 'evB']);
  });

  it('F2 章筛选面板：点按钮 → 面板展开（全部章节 + 各章 + 未分章）；选某章 → 只显示该章事件（反向：其他章不出现）', async () => {
    renderView();
    const user = userEvent.setup();
    // 面板初始不渲染
    expect(screen.queryByTestId('tl-filter-panel')).not.toBeInTheDocument();
    await user.click(screen.getByTestId('tl-filter-chapter'));
    // 面板项：全部章节 / c11 / c12 / 未分章
    expect(screen.getByTestId('tl-fp-item-all')).toBeInTheDocument();
    expect(screen.getByTestId('tl-fp-item-c11')).toBeInTheDocument();
    expect(screen.getByTestId('tl-fp-item-c12')).toBeInTheDocument();
    expect(screen.getByTestId('tl-fp-item-__none__')).toBeInTheDocument();
    // 选 c12 → 只显示 c12 的两条（evC / evD）
    await user.click(screen.getByTestId('tl-fp-item-c12'));
    await waitFor(() => expect(nodeIds()).toEqual(['evC', 'evD']));
    // 反向断言：其他章（c11）与未分章（evB）事件不出现
    expect(screen.queryByTestId('tl-axis-node-evA')).not.toBeInTheDocument();
    expect(screen.queryByTestId('tl-axis-node-evB')).not.toBeInTheDocument();
    // 按钮标签回显
    expect(screen.getByTestId('tl-filter-chapter')).toHaveTextContent('第十二章 夜访剑冢');
  });

  it('F3 章筛选「未分章」：只显示 source_chapter_id 空的事件', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-filter-chapter'));
    await user.click(screen.getByTestId('tl-fp-item-__none__'));
    await waitFor(() => expect(nodeIds()).toEqual(['evB']));
    expect(screen.queryByTestId('tl-axis-node-evA')).not.toBeInTheDocument();
  });

  it('F4 类型筛选：正叙/倒叙/插叙三类（包含式匹配；未标记自由文本「梦境」归正叙）', async () => {
    renderView();
    const user = userEvent.setup();
    // 倒叙 → 只显示 flag 含「倒叙」的事件（evC）
    await user.click(screen.getByTestId('tl-filter-type'));
    expect(screen.getByTestId('tl-tp-item-all')).toBeInTheDocument();
    await user.click(screen.getByTestId('tl-tp-item-flashback'));
    await waitFor(() => expect(nodeIds()).toEqual(['evC']));
    // 插叙 → evD
    await user.click(screen.getByTestId('tl-filter-type'));
    await user.click(screen.getByTestId('tl-tp-item-flashforward'));
    await waitFor(() => expect(nodeIds()).toEqual(['evD']));
    // 正叙 → evA（''）+ evB（'梦境' 未标记）—— 反向：倒叙/插叙不出现
    await user.click(screen.getByTestId('tl-filter-type'));
    await user.click(screen.getByTestId('tl-tp-item-normal'));
    await waitFor(() => expect(nodeIds()).toEqual(['evA', 'evB']));
    expect(screen.queryByTestId('tl-axis-node-evC')).not.toBeInTheDocument();
  });

  it('F5 筛选对两序共用：章筛选 c12 后切世界序 → 仍只显示 c12 事件', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-filter-chapter'));
    await user.click(screen.getByTestId('tl-fp-item-c12'));
    await waitFor(() => expect(nodeIds()).toEqual(['evC', 'evD']));
    // 切世界序：筛选保持（世界序无章分组，但过滤生效）
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => expect(nodeIds()).toEqual(['evC', 'evD']));
    expect(screen.queryAllByTestId(/^tl-chgroup-/)).toHaveLength(0);
    // 切回叙事序：筛选仍在
    await user.click(screen.getByTestId('tl-view-narrative'));
    await waitFor(() => expect(nodeIds()).toEqual(['evC', 'evD']));
  });

  it('F6 章 × 类型可叠加：选 c12 + 倒叙 → 仅 evC', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-filter-chapter'));
    await user.click(screen.getByTestId('tl-fp-item-c12'));
    await user.click(screen.getByTestId('tl-filter-type'));
    await user.click(screen.getByTestId('tl-tp-item-flashback'));
    await waitFor(() => expect(nodeIds()).toEqual(['evC']));
  });

  it('F7 重置「全部」：选 c12 后点「全部章节」→ 恢复全量；类型同理', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-filter-chapter'));
    await user.click(screen.getByTestId('tl-fp-item-c12'));
    await waitFor(() => expect(nodeIds()).toHaveLength(2));
    await user.click(screen.getByTestId('tl-filter-chapter'));
    await user.click(screen.getByTestId('tl-fp-item-all'));
    await waitFor(() => expect(nodeIds()).toEqual(['evA', 'evC', 'evD', 'evB']));
    expect(screen.getByTestId('tl-filter-chapter')).toHaveTextContent('章：全部');
    // 类型重置
    await user.click(screen.getByTestId('tl-filter-type'));
    await user.click(screen.getByTestId('tl-tp-item-normal'));
    await waitFor(() => expect(nodeIds()).toHaveLength(2));
    await user.click(screen.getByTestId('tl-filter-type'));
    await user.click(screen.getByTestId('tl-tp-item-all'));
    await waitFor(() => expect(nodeIds()).toEqual(['evA', 'evC', 'evD', 'evB']));
  });

  it('F8 筛选无匹配：不渲染轴节点（不崩溃、不落空容器）', async () => {
    renderView();
    const user = userEvent.setup();
    // c11 只有 evA（正叙）→ 叠加「插叙」后无匹配
    await user.click(screen.getByTestId('tl-filter-chapter'));
    await user.click(screen.getByTestId('tl-fp-item-c11'));
    await user.click(screen.getByTestId('tl-filter-type'));
    await user.click(screen.getByTestId('tl-tp-item-flashforward'));
    await waitFor(() => expect(screen.queryAllByTestId(/^tl-axis-node-/)).toHaveLength(0));
  });
});
