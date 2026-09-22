/**
 * #1323 P0 时间线段（叙事序）轴与列表重复渲染 + narrative_position 被当章号 —— 组件级契约。
 * **#1374 语义升级（本文件 B2-B6 改写）**：章分组容器 → 章刻度（tl-chtick）；
 * 世界序**不再按章分组**（issue #1374 拍板「A 拆半」含世界序去章分组）。
 *
 * 【#1323 保留面（不推翻）】
 * - 保留轴形态（轴线 + 节点圆点 + 主/副标记，不删轴）
 * - **一章一个刻度**：同一 `source_chapter_id` 的事件收进同一章刻度下，
 *   刻度用**真实章节标题**（`chapterTitles` 映射），不再用 narrative_position 拼章号
 * - **同一事件只渲染一次**（轴即列表，不再「轴 + 列表」两块重复）
 * - 未归章事件（`source_chapter_id` 空）落「未分章」刻度（轴末尾）
 *
 * 【#1374 升级点】
 * - 容器 testid：tl-chgroup-<chapterId>（旧 tl-group-<chapterId>）
 * - 刻度 testid：tl-chtick-<chapterId>（旧 tl-group-title-<chapterId>）
 * - 叙事序组顺序 = **章序（章节列表顺序）** → 章内 narrative_position（合成序）；
 *   未分章落轴末尾；映射缺失的章在未分章之前、已排章之后
 * - 世界序：无 tl-chgroup-*（单一时间轴；行尾来源章胶囊 tl-src-<id>）
 *
 * 【testid 契约（GREEN 必须提供）】
 * - tl-axis                轴容器（保留：轴线本体）
 * - tl-chgroup-<chapterId> 章刻度组（一章一个；未归章 = tl-chgroup-__none__）
 * - tl-chtick-<chapterId>  章刻度文本（= 真实章节标题 / 「未分章」/「未知章节」）
 * - tl-axis-node-<id>      每个事件一个节点（**每个事件恰好一个**）
 * - tl-axis-main-<id>      主轴文本（世界内时间；叙事序降级小字）
 * - library-list           行容器（保留；行内含 tl-check-one-<id> / tl-edit-<id> / tl-delete-<id>）
 *
 * 【保留不破】timeline-toolbar / tl-view-narrative / tl-view-world / tl-check-all /
 * tl-check-one-<id> / tl-edit-<id> / tl-delete-<id> / tl-legend / library-list 行为不变。
 *
 * 【RED 预期】章刻度（tl-chgroup/tl-chtick）/ 世界序去分组 / 章序排序四类断言 FAIL；
 * 零 SyntaxError / ReferenceError / TypeError / Transform failed。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
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
 * Seed（章分组可严格区分）：
 * - 章 c11「师父闭关前夜」：evA（叙事序 1）
 * - 章 c12「夜访剑冢」：evC（叙事序 2）、evE（叙事序 3）→ **同章两个事件**
 * - 未归章（source_chapter_id 空）：evB（叙事序 4）
 */
const evA: TimelineEventDTO = {
  id: 'evA', title: '师父闭关前夜', time_value: 300, time_unit: 'year',
  time_display: '300 年', narrative_position: 1, timeline_flag: false,
  source_chapter_id: 'c11',
};
const evC: TimelineEventDTO = {
  id: 'evC', title: '夜访剑冢', time_value: 100, time_unit: 'year',
  time_display: '100 年', narrative_position: 2, timeline_flag: false,
  source_chapter_id: 'c12',
};
const evE: TimelineEventDTO = {
  id: 'evE', title: '发现异动痕迹', time_value: 200, time_unit: 'year',
  time_display: '200 年', narrative_position: 3, timeline_flag: false,
  source_chapter_id: 'c12',
};
const evB: TimelineEventDTO = {
  id: 'evB', title: '无章事件', time_value: null, time_unit: null,
  time_display: '', narrative_position: 4, timeline_flag: false,
  source_chapter_id: null,
};

const CHAPTER_TITLES: Record<string, string> = {
  c11: '第十一章 剑心为何物',
  c12: '第十二章 夜访剑冢',
};

interface ViewProps {
  chapterTitles?: Record<string, string>;
  chapterOrder?: string[];
}

function renderView(props: ViewProps = {}) {
  return render(
    <TimelineView
      projectId="p1"
      eventTimeline={[evC, evE, evA, evB]}
      narrativeOrder={[evA, evC, evE, evB]}
      chapterTitles={props.chapterTitles ?? CHAPTER_TITLES}
      chapterOrder={props.chapterOrder ?? ['c11', 'c12']}
    />,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ lang: 'zh' });
});

describe('#1323 + #1374 时间线章刻度（去重 + 真实章名 + 未分章 + 章序）', () => {
  it('B1 不重复渲染：每个事件**恰好渲染一次**（反向断言：节点总数 == displayed 长度，且无第二个同 id 容器）', async () => {
    renderView();
    // 4 个事件 → 轴节点恰好 4 个（旧实现另有 library-list 里 4 行 = 8 个事件载体）
    const nodes = screen.getAllByTestId(/^tl-axis-node-/);
    expect(nodes).toHaveLength(4);
    const ids = nodes.map((el) => el.getAttribute('data-testid')!.replace('tl-axis-node-', ''));
    expect(new Set(ids).size).toBe(4);
    // 反向断言：事件标题文本在整页只出现一次（旧实现在轴 + 列表各渲染一次 → 2 次）
    for (const t of ['师父闭关前夜', '夜访剑冢', '发现异动痕迹', '无章事件']) {
      expect(screen.getAllByText(t)).toHaveLength(1);
    }
    expect(screen.getByTestId('library-list')).toBeInTheDocument();
  });

  it('B2 章刻度：同 source_chapter_id 的事件落在同一刻度下，一章一个刻度（同章 2 事件只 1 个刻度）', async () => {
    renderView();
    // 刻度组存在（c11 / c12 / 未分章 = 3 组）
    expect(screen.getByTestId('tl-chgroup-c11')).toBeInTheDocument();
    expect(screen.getByTestId('tl-chgroup-c12')).toBeInTheDocument();
    expect(screen.getByTestId('tl-chgroup-__none__')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^tl-chgroup-(?!title)/)).toHaveLength(3);
    // c12 刻度下恰好 2 个事件节点（evC + evE）—— 同章合并，不再「每事件一个章头」
    const g12 = screen.getByTestId('tl-chgroup-c12');
    expect(within(g12).getAllByTestId(/^tl-axis-node-/)).toHaveLength(2);
    const g11 = screen.getByTestId('tl-chgroup-c11');
    expect(within(g11).getAllByTestId(/^tl-axis-node-/)).toHaveLength(1);
  });

  it('B3 章号正确：刻度用**真实章节标题**（反向断言：刻度不含「第{n}章」拼接形式的错误章号）', async () => {
    renderView();
    // 真实章节标题（来自 chapterTitles 映射）
    expect(screen.getByTestId('tl-chtick-c11')).toHaveTextContent('第十一章 剑心为何物');
    expect(screen.getByTestId('tl-chtick-c12')).toHaveTextContent('第十二章 夜访剑冢');
    // 反向断言：刻度与主轴绝不出现「第{n}章」这种由 narrative_position 拼出的伪章号
    // （narrative_position 只用于排序，spec f12:91 明确它不携带章节语义）
    const ticks = screen
      .getAllByTestId(/^tl-chtick-/)
      .map((el) => el.textContent ?? '')
      .join('|');
    const mains = screen.getAllByTestId(/^tl-axis-main-/).map((el) => el.textContent ?? '').join('|');
    // 注：真实章节标题本身形如「第十一章 …」（#999 归一化产物），此处仅排除「第 N 章」空拼接
    expect(ticks).toContain('剑心为何物');
    expect(mains).not.toMatch(/第\s*[0-9]+\s*章/);
  });

  it('B4 未归章：source_chapter_id 为空的事件落「未分章」刻度（轴末尾），不消失', async () => {
    renderView();
    const none = screen.getByTestId('tl-chgroup-__none__');
    expect(within(none).getByTestId('tl-axis-node-evB')).toBeInTheDocument();
    expect(screen.getByTestId('tl-chtick-__none__')).toHaveTextContent('未分章');
    // 归章事件不得落进未分章刻度
    expect(within(none).queryByTestId('tl-axis-node-evA')).not.toBeInTheDocument();
    // 反向断言：未分章刻度在轴末尾（最后一个刻度）
    const tickKeys = screen
      .getAllByTestId(/^tl-chgroup-/)
      .map((el) => el.getAttribute('data-testid')!.replace('tl-chgroup-', ''));
    expect(tickKeys[tickKeys.length - 1]).toBe('__none__');
  });

  it('B5 既有行为不破：双序 chips / tl-check-all / tl-check-one / tl-edit / tl-delete / tl-legend 仍存在可用；**世界序无章分组**（#1374 语义升级）', async () => {
    renderView();
    expect(screen.getByTestId('timeline-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-narrative')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-world')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-all')).toBeInTheDocument();
    expect(screen.getByTestId('tl-legend')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-one-evA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-edit-evA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-delete-evA')).toBeInTheDocument();
    // #1374：切世界序 → 无章分组容器（不再「分组由 source_chapter_id 决定，与序无关」），
    // 事件全部平铺在单一时间轴上，行尾 = 来源章胶囊
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => {
      expect(screen.queryAllByTestId(/^tl-chgroup-/)).toHaveLength(0);
      expect(screen.getAllByTestId(/^tl-axis-node-/)).toHaveLength(4);
    });
    expect(screen.getByTestId('tl-src-evA')).toHaveTextContent('第十一章 剑心为何物');
  });

  it('B6 无 chapterTitles（映射缺失）时刻度退化为「未知章节」占位，不崩溃、事件不消失', async () => {
    renderView({ chapterTitles: {} });
    // 有 source_chapter_id 但映射缺失 → 刻度回退占位（i18n lib.tlChapterUnknown）
    expect(screen.getByTestId('tl-chtick-c11')).toHaveTextContent('未知章节');
    expect(screen.getAllByTestId(/^tl-axis-node-/)).toHaveLength(4);
  });

  it('B8 刻度计数（原型一致性）：章刻度含「N 个事件」计数，随该刻度下事件数', async () => {
    renderView();
    // c12 两事件 / c11 一事件 / 未分章一事件（原型：tl-chcount 形态）
    expect(screen.getByTestId('tl-chtick-c12')).toHaveTextContent('2 个事件');
    expect(screen.getByTestId('tl-chtick-c11')).toHaveTextContent('1 个事件');
    expect(screen.getByTestId('tl-chtick-__none__')).toHaveTextContent('1 个事件');
  });

  it('B7 章序（#1374 新增）：叙事序组顺序 = chapterOrder（章节列表顺序），未分章落末尾', async () => {
    // chapterOrder 与叙事序首次出现序相反 → 断言确实以 chapterOrder 为准
    renderView({ chapterOrder: ['c12', 'c11'] });
    const tickKeys = screen
      .getAllByTestId(/^tl-chgroup-/)
      .map((el) => el.getAttribute('data-testid')!.replace('tl-chgroup-', ''));
    expect(tickKeys).toEqual(['c12', 'c11', '__none__']);
    // 组内顺序仍按 narrative_position（合成序）：c12 组内 evC(narr 2) → evE(narr 3)
    const g12 = screen.getByTestId('tl-chgroup-c12');
    const ids = within(g12)
      .getAllByTestId(/^tl-axis-node-/)
      .map((el) => el.getAttribute('data-testid')!.replace('tl-axis-node-', ''));
    expect(ids).toEqual(['evC', 'evE']);
  });
});
