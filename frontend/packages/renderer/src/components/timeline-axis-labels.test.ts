/**
 * #1374 时间线双序轴向语义 —— 轴标签派生纯函数契约（timeline-axis-labels.ts）。
 *
 * 【问题（rc5 用户实测 + 源码实证）】
 * `axisLabels` 里 `void view;` —— view（叙事序/世界序）被**显式忽略**，
 * 两序轴完全相同（都返回「主=世界内时间，副=空」）→ 与用户预期「叙事序以章为轴 /
 * 世界序以世界时间为轴」不符（#1374 正文）。
 *
 * 【本批契约（issue #1374 拍板：A 拆半 + spec §1.1）】
 * - 叙事序：轴刻度 = 章（章刻度/tl-chtick 承载真实章节标题）；
 *   世界内时间**降级为行内小字**（ink-3 降级，`dim: true`）
 * - 世界序：轴刻度 = 世界内时间（行内主轴本身即刻度，`dim: false`）
 * - 两序 main 文本均为世界内时间（回退链：time_display → time_value+time_unit → 「未知」）
 * - 副标记槽保留但不承载章号（#1323 G2：narrative_position 不是章号；
 *   章信息由章刻度（叙事序）/ 来源章胶囊（世界序）承载）
 *
 * 【RED 预期】L1 因 `void view` 返回两序同形（dim 不存在）FAIL；
 * L2/L3/L4 为保留行为守护。零 SyntaxError / ReferenceError / TypeError。
 */
import { describe, it, expect } from 'vitest';
import { axisLabels } from './timeline-axis-labels';
import { timeScaleText } from './timeline-era-axes';
import type { TimelineEventDTO } from './TimelineView';

/** t() 桩：只关心 lib.tlTimeUnknown 的渲染值（其余原样回键） */
const t = (key: string) => (key === 'lib.tlTimeUnknown' ? '未知' : key);

const ev: TimelineEventDTO = {
  id: 'ev1', title: '事件甲',
  time_value: 217, time_unit: '年', time_display: '示例历 217 年',
  narrative_position: 2, source_chapter_id: 'c12',
};

describe('#1374 axisLabels 双序分流（叙事序降级小字 / 世界序主轴刻度）', () => {
  it('L1 双序分流：同一事件两序标签不同（dim 分流；反向断言 view 不可被忽略）', () => {
    const narrative = axisLabels(ev, 'narrative', t);
    const world = axisLabels(ev, 'world', t);
    // 反向断言：旧实现 `void view` 两序同形 → 此断言 FAIL
    expect(narrative).not.toEqual(world);
    // 叙事序：时间降为行内小字（降级态）；世界序：时间即轴刻度（非降级）
    expect(narrative.dim).toBe(true);
    expect(world.dim).toBe(false);
  });

  it('L2 两序 main 均为世界内时间（time_display 原样优先 —— 纪年式）', () => {
    expect(axisLabels(ev, 'narrative', t).main).toBe('示例历 217 年');
    expect(axisLabels(ev, 'world', t).main).toBe('示例历 217 年');
  });

  it('L3 回退链：time_display 空 → time_value+time_unit；两者皆空 → 「未知」占位', () => {
    const noDisplay: TimelineEventDTO = { ...ev, id: 'ev2', time_display: '' };
    expect(axisLabels(noDisplay, 'world', t).main).toBe('217年');
    expect(axisLabels(noDisplay, 'narrative', t).main).toBe('217年');
    const none: TimelineEventDTO = {
      ...ev, id: 'ev3', time_display: null, time_value: null, time_unit: null,
    };
    expect(axisLabels(none, 'world', t).main).toBe('未知');
    expect(axisLabels(none, 'narrative', t).main).toBe('未知');
  });

  it('L4 副标记槽保留但不承载章号（章信息由章刻度 / 来源章胶囊承载）', () => {
    // 反向断言：sub 绝不出现「第 N 章」形式的伪章号（narrative_position 不携带章节语义）
    for (const view of ['narrative', 'world'] as const) {
      expect(axisLabels(ev, view, t).sub).toBe('');
    }
  });
});

/**
 * #1526 世界序「原文而非未知」兜底（方案 C）。
 *
 * 背景：rc1 实测 `time_display` 空 182/183 → 世界序满屏「未知」。修好提取侧（方案 A）
 * 之外，前端取值链必须**优先消费 `time_display`（原文表达）**：`time_display` 非空时
 * 即便 `time_value` 为空也显示原文；只有**两者都空**才落「未知」占位（守住真实未知）。
 *
 * 覆盖两条独立的取值链：
 * - `axisLabels`：事件行主轴（叙事序行内小字 / 世界序轴刻度）
 * - `timeScaleText`：世界序**纪元泳道内的时间刻度**（`tl-timenode` 节点）
 */
describe('#1526 time_display 原文兜底（显示原文而非「未知」）', () => {
  const c1: TimelineEventDTO = {
    ...ev, id: 'evC1', time_display: '三月初二', time_value: null, time_unit: null,
  };
  const bothEmpty: TimelineEventDTO = {
    ...ev, id: 'evC2', time_display: null, time_value: null, time_unit: null,
  };

  it('C1 time_display 非空 + time_value=null → 原文表达（两序均如此）', () => {
    expect(axisLabels(c1, 'world', t).main).toBe('三月初二');
    expect(axisLabels(c1, 'narrative', t).main).toBe('三月初二');
  });

  it('C2 time_display 与 time_value 都空 → 「未知」（守住真实未知）', () => {
    expect(axisLabels(bothEmpty, 'world', t).main).toBe('未知');
    expect(axisLabels(bothEmpty, 'narrative', t).main).toBe('未知');
  });

  it('C3 纪元泳道刻度 timeScaleText 走同一条回退链', () => {
    expect(timeScaleText(c1)).toBe('三月初二');
    expect(timeScaleText(bothEmpty)).toBeNull();
  });
});
