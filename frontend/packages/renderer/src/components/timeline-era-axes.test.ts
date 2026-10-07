/**
 * #1353/#1410 时间线纪元轴族 —— 纯函数契约（timeline-era-axes.ts）。
 *
 * 【spec 依据】specs/f12-timeline/spec.md §2.1（三列）+ §2.8（E1/E2 承载 + E5 默认轴）
 *            + ADR-065 + specs/f19-gui/timeline.md §1.1（世界序 = 纪元轴族 + 轴选择器）。
 *
 * 【v1.4 变更（#1410）】读取来源由 `extra.era` / `extra.era_value` 切到**正式列**
 * `era` / `era_value`（DTO 顶层字段）—— 与后端同 PR，消除中间态漂移。
 *
 * 【契约（GREEN 必须提供）】
 * - `era`（轴名，非空字符串，去空白）→ 该事件属于「<轴名>」轴；
 *   空 / 缺失 / 非字符串 → 归 **默认轴**（`DEFAULT_ERA_KEY = '__none__'`，R6-4）
 * - `era_value`（数值）→ 轴内值；非数值 / 缺失 → null（轴内值未知）
 * - ⚠️ **`extra.era` / `extra.era_value` 不再被读取**（v1.4 遗留快照，§2.8 E9）
 * - `deriveEraAxes`：按**轴在事件流中首次出现的顺序**返回全部轴（**仅含有事件的轴**），
 *   默认轴与纪元轴并列（不丢事件），`count` = 轴内事件数，`isDefault` 标记默认轴
 * - `primaryEraKey`：事件数最多的轴（并列取先出现），无轴返回 null
 * - `sortByEraValue`：轴内排序——`era_value` 升序、缺失（null）排末尾、稳定（不改原数组）
 *
 * 【RED 预期（v1.4）】`eraNameOf` / `eraValueOf` 仍读 `extra` → R1/R2/R2b（正式列）FAIL。
 */
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_ERA_KEY,
  deriveEraAxes,
  eraKeyOf,
  eraNameOf,
  eraValueOf,
  groupByTime,
  primaryEraKey,
  sortByEraValue,
  timeScaleText,
} from './timeline-era-axes';
import type { TimelineEventDTO } from './TimelineView';

function ev(id: string, era?: unknown, eraValue?: unknown): TimelineEventDTO {
  return {
    id,
    title: `事件 ${id}`,
    narrative_position: Number(id.replace(/\D/g, '')) || 1,
    time_value: null,
    era: era as string | undefined,
    era_value: eraValue as number | null | undefined,
  };
}

const QY = '示例历';
const XJ = '示例仙历';

describe('#1353/#1410 eraKeyOf / eraNameOf / eraValueOf（正式列读取）', () => {
  it('R1 era 非空字符串 → 轴名（去空白）；era_value 数值 → 轴内值', () => {
    const e = ev('1', '  示例历  ', 317.5);
    expect(eraNameOf(e)).toBe('示例历');
    expect(eraKeyOf(e)).toBe(QY);
    expect(eraValueOf(e)).toBe(317.5);
  });

  it('R2 era 缺失 / 空串 / 非字符串 → 默认轴，轴内值 null', () => {
    for (const era of [undefined, null, '', '   ', 42] as const) {
      const e = ev('2', era);
      expect(eraNameOf(e)).toBeNull();
      expect(eraKeyOf(e)).toBe(DEFAULT_ERA_KEY);
    }
    expect(eraValueOf(ev('3', QY, '317'))).toBeNull();
    expect(eraValueOf(ev('4', QY))).toBeNull();
  });

  it('R2b v1.4：extra.era 不再被读取（正式列优先；正式列空不回退 extra）', () => {
    // 正式列置 Y、extra 置 X → 取 Y
    const e: TimelineEventDTO = { ...ev('5', '正式轴', 8), extra: { era: '遗留轴', era_value: 999 } };
    expect(eraNameOf(e)).toBe('正式轴');
    expect(eraValueOf(e)).toBe(8);
    // 正式列为空 → 仍是默认轴（遗留快照不参与）
    const e2: TimelineEventDTO = { ...ev('6'), extra: { era: '遗留轴', era_value: 999 } };
    expect(eraNameOf(e2)).toBeNull();
    expect(eraKeyOf(e2)).toBe(DEFAULT_ERA_KEY);
    expect(eraValueOf(e2)).toBeNull();
  });

  it('R3 默认轴哨兵键固定（GUI testid / 契约锚点）', () => {
    expect(DEFAULT_ERA_KEY).toBe('__none__');
  });
});

describe('#1353 deriveEraAxes（轴族派生，含默认轴）', () => {
  it('R4 首次出现顺序 + 计数 + isDefault；默认轴与纪元轴并列（R6-4：不丢事件）', () => {
    const axes = deriveEraAxes([
      ev('1', QY, 3),
      ev('2'),
      ev('3', XJ, 9),
      ev('4', QY, 5),
    ]);

    expect(axes.map((a) => a.key)).toEqual([QY, DEFAULT_ERA_KEY, XJ]);
    expect(axes.map((a) => a.count)).toEqual([2, 1, 1]);
    expect(axes.map((a) => a.isDefault)).toEqual([false, true, false]);
    // 纪元轴 label = 轴名；默认轴 label 由组件用 i18n 兜底（此处为空串）
    expect(axes[0].label).toBe(QY);
    expect(axes[1].label).toBe('');
  });

  it('R5 全无纪元 → 只有默认轴（== 旧的单标量时间线，一条轴）', () => {
    const axes = deriveEraAxes([ev('1'), ev('2')]);

    expect(axes).toHaveLength(1);
    expect(axes[0].key).toBe(DEFAULT_ERA_KEY);
    expect(axes[0].count).toBe(2);
  });

  it('R6 空事件集 → 空轴族（不造幽灵轴）', () => {
    expect(deriveEraAxes([])).toEqual([]);
  });
});

describe('#1353 primaryEraKey（默认只显示主力轴）', () => {
  it('R7 事件数最多的轴（并列取先出现）；空轴族 → null', () => {
    const axes = deriveEraAxes([ev('1'), ev('2', QY), ev('3', QY)]);

    expect(primaryEraKey(axes)).toBe(QY);
    expect(primaryEraKey([])).toBeNull();
  });

  it('R8 无纪元数据 → 默认轴即主力轴', () => {
    expect(primaryEraKey(deriveEraAxes([ev('1'), ev('2')]))).toBe(DEFAULT_ERA_KEY);
  });
});

describe('#1353 sortByEraValue（轴内排序）', () => {
  it('R9 era_value 升序、缺失排末尾、稳定且不改原数组', () => {
    const a = ev('1', QY, 30);
    const b = ev('2', QY, 10);
    const c = ev('3', QY);
    const d = ev('4', QY, null);
    const input = [a, b, c, d];

    const sorted = sortByEraValue(input);

    expect(sorted.map((e) => e.id)).toEqual(['2', '1', '3', '4']);
    expect(input.map((e) => e.id)).toEqual(['1', '2', '3', '4']);
  });
});

/**
 * #1467 组内时间刻度（specs/f19-gui/timeline.md §1.1 世界序·纪元轴族 + §3 N12/N14）。
 *
 * 【契约（GREEN 必须提供）】
 * - `timeScaleText`：`time_display`（trim 非空）原样 → 「`era_value` + `time_unit`」→ 「`time_value` + `time_unit`」→ null
 * - **轴名绝不进入刻度文案**（#1353 的「轴名 + 轴内值」回退已废除 —— 轴名只出现在组头）
 * - `groupByTime`：同刻度合并为一个时间节点，保持传入顺序，不改原数组
 * - **负例（#1467 硬边界）**：`era_scale`（流速比）不参与任何渲染计算 —— 同 `era_value`、不同 `era_scale`
 *   的事件必须落**同一**时间节点（不做跨轴换算，换算归 #1411）
 *
 * 【RED 预期】`timeScaleText` / `groupByTime` 未导出 → import undefined → G1-G4 全 FAIL。
 */
describe('#1467 组内时间刻度（timeScaleText / groupByTime）', () => {
  const tick = (
    id: string,
    era: string,
    eraValue: number | null,
    over: Partial<TimelineEventDTO> = {},
  ): TimelineEventDTO => ({ ...ev(id, era, eraValue), ...over });

  it('G1 刻度回退链：time_display 原样 → 「轴内值 + 单位」→ 「时间值 + 单位」→ null', () => {
    expect(timeScaleText(tick('1', QY, 17, { time_display: '示例历 17 年', time_unit: '年', time_value: 17 })))
      .toBe('示例历 17 年');
    expect(timeScaleText(tick('2', QY, 1024, { time_display: '', time_unit: '年', time_value: 1024 })))
      .toBe('1024年');
    expect(timeScaleText(tick('3', QY, 88, { time_display: '   ', time_unit: '年', time_value: 7 })))
      .toBe('88年');
    expect(timeScaleText(tick('4', QY, null, { time_display: null, time_unit: '年', time_value: 7 })))
      .toBe('7年');
    expect(timeScaleText(tick('5', QY, null, { time_display: null, time_unit: null, time_value: null })))
      .toBeNull();
  });

  it('G2 轴名绝不进入刻度文案（反向断言：#1467 前是「轴名 + 轴内值」）', () => {
    const e = tick('6', '示例界 · 示例历', 1024, { time_display: '', time_unit: '年' });

    expect(timeScaleText(e)).toBe('1024年');
    expect(String(timeScaleText(e))).not.toContain('示例界');
  });

  it('G3 同刻度合并 + 保持顺序；同 era_value、不同 era_scale 不分叉（负例：不做流速换算）', () => {
    const g1 = tick('1', QY, 17, { time_display: '示例历 17 年' });
    const g2 = tick('2', QY, 217, { time_display: '示例历 217 年', era_scale: 1 });
    const g3 = tick('3', QY, 217, { time_display: '示例历 217 年', era_scale: 12 });
    const g4 = tick('4', QY, 217, { time_display: '示例历 217 年', era_scale: 0.5 });

    const groups = groupByTime([g1, g2, g3, g4]);

    expect(groups.map((x) => x.key)).toEqual(['示例历 17 年', '示例历 217 年']);
    expect(groups[1].events.map((x) => x.id)).toEqual(['2', '3', '4']);
  });

  it('G4 空输入 → 空分组；刻度缺失的事件归入同一 null 组（组件用 lib.tlTimeUnknown 兜底）', () => {
    expect(groupByTime([])).toEqual([]);

    const u1 = tick('1', QY, null, { time_display: null, time_unit: null, time_value: null });
    const u2 = tick('2', QY, null, { time_display: '', time_unit: null, time_value: null });
    const groups = groupByTime([u1, u2]);

    expect(groups).toHaveLength(1);
    expect(groups[0].key).toBeNull();
    expect(groups[0].events.map((x) => x.id)).toEqual(['1', '2']);
  });
});
