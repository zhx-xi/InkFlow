/**
 * #1541 世界序多历共存「单块刻度带」—— 纯派生函数契约。
 *
 * 【spec 依据】specs/f19-gui/timeline.md §1.1（世界序刻度带）/ §3 N15
 *            + specs/f12-timeline/spec.md §2.8 E11（`to_global = era_value / era_scale`，ADR-065）。
 *
 * 【契约（GREEN 必须提供）】
 * - 纵向口径 = 全局时间 `to_global`：纪元轴 = `era_value / era_scale`（`era_scale <= 0` / 缺失 → 按 1）；
 *   默认轴（`era` 空）= `time_value`
 * - 每历刻度 = 该历事件 g 值**去重**升序（同刻度只出现一次）
 * - 事件行按 g 升序；**同 g 顺次错开**（`slot` = 0,1,2…）
 * - 时间未知（g === null）事件归 `unknown`（不参与刻度 / 比例）
 * - `gmax` = 已知 g 最大值（无已知 g → 1）
 *
 * 【RED 预期】`./timeline-band` 尚不存在 → 模块解析失败 / 断言 FAIL。
 */
import { describe, it, expect } from 'vitest';
import {
  BAND_ROW_H,
  BAND_ROW_PAD,
  BAND_TICKS_PER_PAGE,
  BAND_UNK_MAX,
  bandGlobal,
  bandTickRows,
  buildBandLayout,
  layoutBandSpine,
} from './timeline-band';
import type { TimelineEventDTO } from './TimelineView';
import type { TimelineEraAxis } from './timeline-era-axes';

function ev(o: Partial<TimelineEventDTO> & { id: string }): TimelineEventDTO {
  return { title: `事件${o.id}`, ...o };
}

const axis = (key: string, label: string, count: number, isDefault = false): TimelineEraAxis => ({
  key,
  label,
  count,
  isDefault,
});

describe('#1541 to_global 口径（bandGlobal）', () => {
  it('T1 纪元轴 = era_value / era_scale；scale <= 0 / 缺失按 1', () => {
    expect(bandGlobal(ev({ id: 'a', era: '示例历', era_value: 100, era_scale: 1 }))).toBe(100);
    expect(bandGlobal(ev({ id: 'b', era: '示例仙历', era_value: 100, era_scale: 10 }))).toBe(10);
    expect(bandGlobal(ev({ id: 'c', era: '示例历', era_value: 100 }))).toBe(100); // 缺 scale → 1
    expect(bandGlobal(ev({ id: 'd', era: '示例历', era_value: 100, era_scale: 0 }))).toBe(100); // 非正 → 1
    expect(bandGlobal(ev({ id: 'e', era: '示例历', era_value: 100, era_scale: -3 }))).toBe(100);
  });

  it('T2 纪元轴 era_value 缺失 → null；默认轴回退 time_value；都缺 → null', () => {
    expect(bandGlobal(ev({ id: 'a', era: '示例历' }))).toBeNull();
    expect(bandGlobal(ev({ id: 'b', time_value: 50 }))).toBe(50);
    expect(bandGlobal(ev({ id: 'c', era: '', time_value: 7 }))).toBe(7);
    expect(bandGlobal(ev({ id: 'd' }))).toBeNull();
    expect(bandGlobal(ev({ id: 'e', time_value: null }))).toBeNull();
  });
});

describe('#1541 刻度带布局（buildBandLayout）', () => {
  const A = '示例历';
  const B = '示例仙历';

  it('T3 每历刻度去重升序（同刻度只出现一次）；刻度 value = 本地值、g = 全局值', () => {
    const events = [
      ev({ id: '1', era: A, era_value: 17, era_scale: 1, time_unit: '年' }),
      ev({ id: '2', era: A, era_value: 217, era_scale: 1, time_unit: '年' }),
      ev({ id: '3', era: A, era_value: 217, era_scale: 1, time_unit: '年' }), // 同刻度 → 只 1 个
      ev({ id: '4', era: B, era_value: 1024, era_scale: 10, time_unit: '年' }),
    ];
    const layout = buildBandLayout(events, [axis(A, A, 3), axis(B, B, 1)]);
    const a = layout.axes.find((x) => x.key === A)!;
    expect(a.ticks.map((t) => t.value)).toEqual([17, 217]);
    expect(a.ticks.map((t) => t.g)).toEqual([17, 217]);
    const b = layout.axes.find((x) => x.key === B)!;
    expect(b.ticks.map((t) => t.value)).toEqual([1024]);
    expect(b.ticks[0].g).toBeCloseTo(102.4, 5);
  });

  it('T4 流速不同 ⇒ 同一 era_value 的两个历落在不同 g（刻度隔断疏密不同）', () => {
    const events = [
      ev({ id: '1', era: A, era_value: 100, era_scale: 1 }),
      ev({ id: '2', era: B, era_value: 100, era_scale: 10 }),
    ];
    const layout = buildBandLayout(events, [axis(A, A, 1), axis(B, B, 1)]);
    const ta = layout.axes.find((x) => x.key === A)!.ticks[0];
    const tb = layout.axes.find((x) => x.key === B)!.ticks[0];
    expect(ta.value).toBe(100); // 本地值相同
    expect(tb.value).toBe(100);
    expect(ta.g).toBe(100); // 全局值不同（流速 1 vs 10）
    expect(tb.g).toBe(10);
    expect(tb.g).toBeLessThan(ta.g);
  });

  it('T5 事件行按 g 升序；同 g 顺次错开 slot；每事件恰一次', () => {
    const events = [
      ev({ id: '1', era: A, era_value: 300, era_scale: 1 }),
      ev({ id: '2', era: A, era_value: 100, era_scale: 1 }),
      ev({ id: '3', era: A, era_value: 100, era_scale: 1 }),
    ];
    const layout = buildBandLayout(events, [axis(A, A, 3)]);
    expect(layout.rows.map((r) => r.ev.id)).toEqual(['2', '3', '1']);
    expect(layout.rows.map((r) => r.slot)).toEqual([0, 1, 0]);
    expect(layout.rows.map((r) => r.g)).toEqual([100, 100, 300]);
    expect(new Set(layout.rows.map((r) => r.ev.id)).size).toBe(3);
  });

  it('T6 时间未知事件归 unknown（不参与刻度 / 比例 / rows）', () => {
    const events = [
      ev({ id: '1', era: A, era_value: 100, era_scale: 1 }),
      ev({ id: '2' }), // 无任何时间
      ev({ id: '3', era: A }), // 有历无轴内值
    ];
    const layout = buildBandLayout(events, [axis(A, A, 1), axis('__none__', '', 2, true)]);
    expect(layout.unknown.map((e) => e.id)).toEqual(['2', '3']);
    expect(layout.rows.map((r) => r.ev.id)).toEqual(['1']);
    expect(layout.gmax).toBe(100);
  });

  it('T7 gmax = 已知 g 最大值；无已知 g → 1；rows 带 axisKey', () => {
    const events = [ev({ id: '1', era: A, era_value: 17, era_scale: 1 }), ev({ id: '2', era: B, era_value: 4096, era_scale: 10 })];
    const layout = buildBandLayout(events, [axis(A, A, 1), axis(B, B, 1)]);
    expect(layout.gmax).toBeCloseTo(409.6, 5);
    expect(layout.rows.map((r) => r.axisKey)).toEqual([A, B]);
    expect(buildBandLayout([ev({ id: '9' })], [axis('__none__', '', 1, true)]).gmax).toBe(1);
  });
});
/* ══════════════ #1564 世界序刻度带 v2：不定高 + 按刻度分页 + 时间主轴 + 离群免疫 ══════════════
   【spec 依据】specs/f19-gui/timeline.md §1.1（世界序刻度带 v2）/ §2（刻度带 + 分页 + 未知区行）/ §3 N16。

   契约：
   - `bandTickRows(layout)`：主轴刻度行 = layout.rows 按 `g` 去重升序；`count` = 跨选中历事件数；
     `perAxis[axisKey]` = 该历在本刻度的本地刻度；`label` = 轴族顺序里首个有本刻度的历。
   - `layoutBandSpine(rows, unknownCount, { page })`：
     · 不定高：`height = BAND_ROW_PAD * 2 + 该刻度事件数 * BAND_ROW_H`
     · 分页单位 = 刻度：`pageCount = ceil(totalTicks / BAND_TICKS_PER_PAGE)`
     · unknown 只计一次：未知区高度上限 `BAND_UNK_MAX`（截到整行），画布高度不随未知数线性增长
     · 离群免疫：纵向位置 = 刻度序号（等距），加入极大值不改动其它行的 `top` */

describe('#1564 时间主轴刻度行（bandTickRows）', () => {
  const A = '示例历';
  const B = '示例仙历';

  it('T8 按 g 去重升序；count = 跨历事件数；perAxis 本地刻度；label 取轴族首个有本刻度的历', () => {
    const events = [
      ev({ id: '1', era: A, era_value: 17, era_scale: 1, time_unit: '年' }),
      ev({ id: '2', era: A, era_value: 217, era_scale: 1, time_unit: '年' }),
      ev({ id: '3', era: A, era_value: 217, era_scale: 1, time_unit: '年' }),
      ev({ id: '4', era: B, era_value: 1024, era_scale: 10, time_unit: '年' }),
    ];
    const rows = bandTickRows(buildBandLayout(events, [axis(A, A, 3), axis(B, B, 1)]));

    expect(rows.map((r) => r.g)).toEqual([17, 102.4, 217]);
    expect(rows.map((r) => r.count)).toEqual([1, 1, 2]);
    expect(rows[2].perAxis[A]).toEqual({ value: 217, unit: '年', label: '217 年' });
    expect(rows[1].perAxis[B].value).toBe(1024);
    expect(rows[1].perAxis[B].label).toBe('1024 年');
    expect(rows[0].label).toBe('17 年');
    expect(rows[2].events.map((r) => r.slot)).toEqual([0, 1]);
  });
});

describe('#1564 刻度带几何（layoutBandSpine）', () => {
  const A = '示例历';

  /** 12 刻度：首刻度 3 个事件，其余各 1 */
  function twelveTicks(): TimelineEventDTO[] {
    const events = [
      ev({ id: 'a1', era: A, era_value: 1 }),
      ev({ id: 'a2', era: A, era_value: 1 }),
      ev({ id: 'a3', era: A, era_value: 1 }),
    ];
    for (let i = 2; i <= 12; i += 1) events.push(ev({ id: `b${i}`, era: A, era_value: i }));
    return events;
  }

  it('T9a 不定高：行高 = BAND_ROW_PAD*2 + 该刻度事件数 * BAND_ROW_H（同轴内不同刻度高度不同）', () => {
    const rows = bandTickRows(buildBandLayout(twelveTicks(), [axis(A, A, 14)]));
    const g = layoutBandSpine(rows, 0, { page: 0 });

    expect(rows).toHaveLength(12);
    expect(g.placed[0].height).toBe(BAND_ROW_PAD * 2 + 3 * BAND_ROW_H);
    expect(g.placed[1].height).toBe(BAND_ROW_PAD * 2 + BAND_ROW_H);
    expect(g.placed[0].height).toBeGreaterThan(g.placed[1].height);
  });

  it('T9b 分页单位 = 刻度：pageCount = ceil(12 / BAND_TICKS_PER_PAGE)；翻页后刻度集合变化', () => {
    const rows = bandTickRows(buildBandLayout(twelveTicks(), [axis(A, A, 14)]));
    const p0 = layoutBandSpine(rows, 0, { page: 0 });
    const p1 = layoutBandSpine(rows, 0, { page: 1 });

    expect(BAND_TICKS_PER_PAGE).toBe(8);
    expect(p0.pageCount).toBe(2);
    expect(p0.totalTicks).toBe(12);
    expect(p0.placed).toHaveLength(8);
    expect(p1.placed).toHaveLength(4);
    expect(p1.placed[0].row.g).not.toBe(p0.placed[0].row.g);
    expect(layoutBandSpine(rows, 0, { page: 99 }).page).toBe(1);
  });

  it('T9c unknown 只计一次：未知区限高 BAND_UNK_MAX，画布不随未知事件数线性增长', () => {
    const rows = bandTickRows(buildBandLayout(twelveTicks(), [axis(A, A, 14)]));
    const none = layoutBandSpine(rows, 0, { page: 0 });
    const few = layoutBandSpine(rows, 3, { page: 0 });
    const many = layoutBandSpine(rows, 240, { page: 0 });

    expect(none.unknownHeight).toBe(0);
    expect(many.unknownHeight).toBe(few.unknownHeight);
    expect(many.unknownHeight).toBeLessThanOrEqual(BAND_UNK_MAX + 64);
    expect(many.height - none.height).toBe(few.height - none.height);
    expect(many.height).toBeLessThan(900);
  });

  it('T10 离群值不压扁其余刻度：加入 1 个极大值后，其它行的 top 逐行不变', () => {
    const base = [10, 20, 30, 40, 50].map((v, i) => ev({ id: `n${i}`, era: A, era_value: v, era_scale: 1 }));
    const withOutlier = [...base, ev({ id: 'big', era: A, era_value: 1000000, era_scale: 1 })];
    const geom = (events: TimelineEventDTO[]) =>
      layoutBandSpine(bandTickRows(buildBandLayout(events, [axis(A, A, events.length)])), 0, { page: 0 });

    const normal = geom(base);
    const outlier = geom(withOutlier);

    expect(outlier.placed).toHaveLength(6);
    expect(outlier.placed.slice(0, 5).map((p) => p.top)).toEqual(normal.placed.map((p) => p.top));
    expect(outlier.placed[5].top).toBeGreaterThan(normal.placed[4].top);
  });
});
