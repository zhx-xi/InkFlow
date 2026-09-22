/**
 * #1301 时间线时间轴渲染 + **#1374 双序轴向语义分流** —— 组件级契约。
 *
 * 【spec 依据】
 * - specs/f19-gui/timeline.md §1.1（双序轴向定义）+ §3 N1/N5/N7/N10
 * - specs/f12-timeline/spec.md:621/702「事件时间线（世界内时间轴）」排序键 time_value
 * - specs/f43-setting-library-gui/spec.md:773「图例 tl-legend」
 *
 * 【#1374 语义升级（本文件 A2/A3/A5 改写）】
 * 旧契约（#1301/#1323）：两序共用章分组容器，主轴 = 世界内时间。
 * 现契约（issue #1374 拍板「A 拆半」+ spec §1.1）：
 * - **叙事序**：轴刻度 = **章**（章刻度 tl-chtick-<chapterId>，真实章节标题）；
 *   事件行内世界内时间**降级为小字**（ink-3 降级）
 * - **世界序**：轴刻度 = **世界内时间**（行内主轴即刻度）；**无章分组容器**；
 *   行尾 = 来源章胶囊（tl-src-<id>）
 * - 双序切换仍为本地切换显示数组（零额外请求）
 *
 * 【testid 契约（GREEN 必须提供）】
 * - tl-axis                轴容器（保留；两序各一个）
 * - tl-axis-node-<id>      每个事件一个节点（每个事件恰好一次）
 * - tl-axis-main-<id>      主轴文本（= 世界内时间；叙事序带 ink-3 降级类）
 * - tl-chtick-<chapterId>  叙事序章刻度（-__none__ = 未分章）
 * - tl-src-<id>            世界序行尾来源章胶囊
 * - tl-view-narrative / tl-view-world / tl-check-all / tl-check-one-<id> / tl-legend 保留
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
 * Seed 事件（双序可严格区分）：
 * - 世界序（time_value 升序、未知末尾）：evC(100) → evA(300) → evB(未知)
 * - 叙事序（narrative_position 升序）：evB(1) → evC(2) → evA(3)
 */
const evA: TimelineEventDTO = {
  id: 'evA', title: '甲 登基', time_value: 300, time_unit: 'year',
  time_display: '300 年', narrative_position: 3, timeline_flag: false,
  source_chapter_id: 'c11',
};
const evB: TimelineEventDTO = {
  id: 'evB', title: '乙 失踪', time_value: null, time_unit: null,
  time_display: '', narrative_position: 1, timeline_flag: false,
  source_chapter_id: null,
};
const evC: TimelineEventDTO = {
  id: 'evC', title: '丙 初现', time_value: 100, time_unit: 'year',
  time_display: '100 年', narrative_position: 2, timeline_flag: false,
  source_chapter_id: 'c12',
};

const CHAPTER_TITLES: Record<string, string> = {
  c11: '第十一章 剑心为何物',
  c12: '第十二章 夜访剑冢',
};

function renderView(props: Partial<Parameters<typeof TimelineView>[0]> = {}) {
  return render(
    <TimelineView
      projectId="p1"
      eventTimeline={[evC, evA, evB]}
      narrativeOrder={[evB, evC, evA]}
      chapterTitles={CHAPTER_TITLES}
      chapterOrder={['c11', 'c12']}
      {...props}
    />,
  );
}

beforeEach(() => {
  apiFetchMock.mockReset();
  apiFetchMock.mockImplementation(async () => ({ checked: 0, skipped: 0, consistent: true, conflicts: [] }));
  useThemeStore.setState({ lang: 'zh' });
});

describe('#1301 + #1374 时间线双序轴向渲染', () => {
  it('A1 轴容器存在：tl-axis + 每个事件一个 tl-axis-node-<id>', async () => {
    renderView();
    expect(screen.getByTestId('tl-axis')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-evA')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-evB')).toBeInTheDocument();
    expect(screen.getByTestId('tl-axis-node-evC')).toBeInTheDocument();
  });

  it('A2 世界序：主轴 = 世界内时间（非降级）；叙事序：时间降为行内小字（#1374 分流）', async () => {
    renderView();
    // 叙事序（默认）：主轴 = 世界内时间 + ink-3 降级类（行内小字）
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('100 年'));
    expect(screen.getByTestId('tl-axis-main-evC').className).toContain('text-ink-3');
    // 世界序：主轴 = 世界内时间（刻度态，非降级）
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => expect(screen.getByTestId('tl-axis-main-evC')).toHaveTextContent('100 年'));
    expect(screen.getByTestId('tl-axis-main-evC').className).not.toContain('text-ink-3');
  });

  it('A3 叙事序：轴刻度 = 章（tl-chtick-<chapterId> = 真实章节标题）；主轴不含伪章号', async () => {
    renderView();
    // 章刻度存在且用真实章节标题（来自 chapterTitles 映射）
    expect(screen.getByTestId('tl-chtick-c11')).toHaveTextContent('第十一章 剑心为何物');
    expect(screen.getByTestId('tl-chtick-c12')).toHaveTextContent('第十二章 夜访剑冢');
    // 反向断言：主轴（tl-axis-main）绝不承载 narrative_position 拼出的「第 N 章」
    const mains = screen.getAllByTestId(/^tl-axis-main-/).map((el) => el.textContent ?? '').join('|');
    expect(mains).not.toMatch(/第\s*[0-9]+\s*章/);
  });

  it('A4 时间未知事件（time_value=null）在轴上用「未知」占位，不消失', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    const node = await screen.findByTestId('tl-axis-node-evB');
    expect(node).toBeInTheDocument();
    // 主轴无 time_display → 回退未知占位（i18n lib.tlTimeUnknown）
    expect(screen.getByTestId('tl-axis-main-evB')).toHaveTextContent('未知');
  });

  it('A5 既有行为不破：双序 chips / tl-check-all / tl-check-one / tl-legend 仍存在可用', async () => {
    renderView();
    expect(screen.getByTestId('timeline-toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-narrative')).toBeInTheDocument();
    expect(screen.getByTestId('tl-view-world')).toBeInTheDocument();
    expect(screen.getByTestId('tl-check-all')).toBeInTheDocument();
    // 图例随序切换（#1374：拆两 key —— 叙事序「轴=章…」/ 世界序「轴=世界内时间…」）
    expect(screen.getByTestId('tl-legend')).toHaveTextContent('轴=章');
    expect(screen.getByTestId('tl-check-one-evA')).toBeInTheDocument();
    expect(screen.getByTestId('library-list')).toBeInTheDocument();
    // #1323：每事件恰好一个节点（单一容器，不再重复渲染）
    expect(screen.getAllByTestId(/^tl-axis-node-/)).toHaveLength(3);
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    // 轴节点顺序随序切换（世界序：evC → evA → evB）
    await waitFor(() => {
      const ids = screen
        .getAllByTestId(/^tl-axis-node-/)
        .map((el) => el.getAttribute('data-testid')!.replace('tl-axis-node-', ''));
      expect(ids).toEqual(['evC', 'evA', 'evB']);
    });
    expect(screen.getByTestId('tl-legend')).toHaveTextContent('轴=世界内时间');
  });

  it('A6 世界序：无章分组容器（反向断言 tl-chgroup 不存在）；行尾 = 来源章胶囊 tl-src-<id>', async () => {
    renderView();
    const user = userEvent.setup();
    await user.click(screen.getByTestId('tl-view-world'));
    await waitFor(() => expect(screen.getByTestId('tl-axis-node-evC')).toBeInTheDocument());
    // 反向断言：世界序不再按章分组（#1374 拍板「含世界序去章分组」）
    expect(screen.queryAllByTestId(/^tl-chgroup-/)).toHaveLength(0);
    // 行尾来源章胶囊：已归章 = 章节标题；未归章 = 「未分章」
    expect(screen.getByTestId('tl-src-evC')).toHaveTextContent('第十二章 夜访剑冢');
    expect(screen.getByTestId('tl-src-evA')).toHaveTextContent('第十一章 剑心为何物');
    expect(screen.getByTestId('tl-src-evB')).toHaveTextContent('未分章');
  });
});
