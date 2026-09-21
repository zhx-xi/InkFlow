/**
 * #1323 P0 时间线段（叙事序）轴与列表重复渲染 + narrative_position 被当章号 —— 组件级契约。
 *
 * 【现象（用户观察，父侧已实证）】
 * 1. 同一批事件在页面上**渲染两遍**：`tl-axis`（:186-232 逐事件轴节点）与
 *    `library-list`（:234-278 列表）渲染的是**同一个 `displayed` 数组** → 「上下两块」重复。
 * 2. 轴的「主轴」文本用 `narrative_position` 拼成「第 N 章」（`timeline-axis-labels.ts:27-33`），
 *    而 `narrative_position` 是**单一线性序号**（`domain/models/timeline.py:158`，
 *    `specs/f12-timeline/spec.md:91` 明确「不携带章节语义」）→ DB 实测 215 条只有 34 个不同
 *    位置值，1/6/7 各对应 10 条 → 同一「第 7 章」重复 10 次。
 * 3. 事件→章节映射**后端早就返回**（`timeline_events.source_chapter_id` 214/215 非空，
 *    `api/routers/timeline.py:207` 的 `model_dump(mode="json")` 会带出），但前端 DTO
 *    未声明该字段 → 没有真实章节标题可显示。
 *
 * 【本批契约（#1323 R6-3 拍板：保留轴形态，改为「章分组容器」）】
 * - 保留轴形态（轴线 + 节点圆点 + 主/副标记 testid 不变，不删轴 —— #1301 的视觉收益保留）
 * - **一章一个分组 header**：同一 `source_chapter_id` 的事件收进同一个分组，
 *   分组 header 用**真实章节标题**（`chapterTitles` 映射），不再用 narrative_position 拼章号
 * - **同一事件只渲染一次**（去重 —— 轴即列表，不再「轴 + 列表」两块重复）
 * - 未归章事件（`source_chapter_id` 空）落「未分章」分组
 *
 * 【testid 契约（GREEN 必须提供）】
 * - tl-axis                章分组容器（保留：轴线本体）
 * - tl-group-<chapterId>   章分组（一章一个；未归章 = tl-group-__none__）
 * - tl-group-title-<chapterId>  分组 header 文本（= 真实章节标题 / 「未分章」）
 * - tl-axis-node-<id>      每个事件一个节点（保留；**每个事件恰好一个**）
 * - tl-axis-main-<id>      主轴文本（保留：时间/章内序等）
 * - tl-axis-sub-<id>       副标记文本（保留；可为空）
 * - library-list           行容器（保留；行内含 tl-check-one-<id> / tl-edit-<id> / tl-delete-<id>）
 *
 * 【保留不破】timeline-toolbar / tl-view-narrative / tl-view-world / tl-check-all /
 * tl-check-one-<id> / tl-edit-<id> / tl-delete-<id> / tl-legend / library-list 行为不变。
 *
 * 【RED 预期】去重 / 章分组 / 真实章名 / 未分章 四类断言 FAIL；
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

function renderView() {
  return render(
    <TimelineView
      projectId="p1"
      eventTimeline={[evC, evE, evA, evB]}
      narrativeOrder={[evA, evC, evE, evB]}
      chapterTitles={CHAPTER_TITLES}
    />,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ lang: 'zh' });
});

describe('#1323 P0 时间线章分组容器（去重 + 真实章名 + 未分章）', () => {
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

  it('B2 章分组：同 source_chapter_id 的事件落在同一分组，一章一个 header（同章 2 事件只 1 个 header）', async () => {
    renderView();
    // 分组容器存在（c11 / c12 / 未分章 = 3 组）
    expect(screen.getByTestId('tl-group-c11')).toBeInTheDocument();
    expect(screen.getByTestId('tl-group-c12')).toBeInTheDocument();
    expect(screen.getByTestId('tl-group-__none__')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^tl-group-(?!title)/)).toHaveLength(3);
    // c12 组内恰好 2 个事件节点（evC + evE）—— 同章合并，不再「每事件一个章头」
    const g12 = screen.getByTestId('tl-group-c12');
    expect(within(g12).getAllByTestId(/^tl-axis-node-/)).toHaveLength(2);
    const g11 = screen.getByTestId('tl-group-c11');
    expect(within(g11).getAllByTestId(/^tl-axis-node-/)).toHaveLength(1);
  });

  it('B3 章号正确：header 用**真实章节标题**（反向断言：header 不含「第{n}章」拼接形式的错误章号）', async () => {
    renderView();
    // 真实章节标题（来自 chapterTitles 映射）
    expect(screen.getByTestId('tl-group-title-c11')).toHaveTextContent('第十一章 剑心为何物');
    expect(screen.getByTestId('tl-group-title-c12')).toHaveTextContent('第十二章 夜访剑冢');
    // 反向断言：header 绝不出现「第{n}章」这种由 narrative_position 拼出的伪章号
    // （narrative_position 只用于排序，spec f12:91 明确它不携带章节语义）
    const titles = screen
      .getAllByTestId(/^tl-group-title-/)
      .map((el) => el.textContent ?? '')
      .join('|');
    expect(titles).not.toMatch(/第\s*[0-9]+\s*章/);
    // 反向断言：轴主轴（tl-axis-main）也不再承载 narrative_position 拼出的章号
    const mains = screen.getAllByTestId(/^tl-axis-main-/).map((el) => el.textContent ?? '').join('|');
    expect(mains).not.toMatch(/第\s*[0-9]+\s*章/);
  });

  it('B4 未归章：source_chapter_id 为空的事件落「未分章」分组，不消失', async () => {
    renderView();
    const none = screen.getByTestId('tl-group-__none__');
    expect(within(none).getByTestId('tl-axis-node-evB')).toBeInTheDocument();
    expect(screen.getByTestId('tl-group-title-__none__')).toHaveTextContent('未分章');
    // 归章事件不得落进未分章组
    expect(within(none).queryByTestId('tl-axis-node-evA')).not.toBeInTheDocument();
  });

  it('B5 既有行为不破：双序 chips / tl-check-all / tl-check-one / tl-edit / tl-delete / tl-legend 仍存在可用', async () => {
    renderView();
    expect(screen.getByTestId('timeline-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-narrative')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-world')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-all')).toBeInTheDocument();
    expect(screen.getByTestId('tl-legend')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-one-evA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-edit-evA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-delete-evA')).toBeInTheDocument();
    // 世界序切换后仍按章分组（分组由 source_chapter_id 决定，与序无关）
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => {
      const g12w = screen.getByTestId('tl-group-c12');
      expect(within(g12w).getAllByTestId(/^tl-axis-node-/)).toHaveLength(2);
    });
  });

  it('B6 无 chapterTitles（映射缺失）时退化为「未分章」占位，不崩溃、事件不消失', async () => {
    render(
      <TimelineView
        projectId="p1"
        eventTimeline={[evC, evA]}
        narrativeOrder={[evA, evC]}
        chapterTitles={{}}
      />,
    );
    // 有 source_chapter_id 但映射缺失 → 分组标题回退占位（i18n lib.tlChapterUnknown）
    expect(screen.getByTestId('tl-group-title-c11')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^tl-axis-node-/)).toHaveLength(2);
  });
});
