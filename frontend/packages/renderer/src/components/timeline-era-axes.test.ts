/**
 * #1353 时间线纪元轴族 —— 纯函数契约（timeline-era-axes.ts）。
 *
 * 【spec 依据】specs/f12-timeline/spec.md §2.8（承载键 E1/E2 + 默认轴 E5）
 *            + specs/f19-gui/timeline.md §1.1（世界序 = 纪元轴族 + 轴选择器）。
 *
 * 【契约（GREEN 必须提供）】
 * - `extra.era`（轴名，非空字符串，去空白）→ 该事件属于「<轴名>」轴；
 *   空 / 缺失 / 非字符串 → 归 **默认轴**（`DEFAULT_ERA_KEY = '__none__'`，R6-4）
 * - `extra.era_value`（数值）→ 轴内值；非数值 / 缺失 → null（轴内值未知）
 * - `deriveEraAxes`：按**轴在事件流中首次出现的顺序**返回全部轴（**仅含有事件的轴**），
 *   默认轴与纪元轴并列（不丢事件），`count` = 轴内事件数，`isDefault` 标记默认轴
 * - `primaryEraKey`：事件数最多的轴（并列取先出现）—— 代「主角所在轴」的启发式
 *   （事件无角色关联字段；主角↔纪元映射归后续里程碑），无轴返回 null
 * - `sortByEraValue`：轴内排序——`era_value` 升序、缺失（null）排末尾、稳定（不改原数组）
 *
 * 【RED 预期】模块不存在 → 收集期 module-not-found（预期 RED 形态）；
 * GREEN 后逐条断言全绿。
 */
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_ERA_KEY,
  deriveEraAxes,
  eraKeyOf,
  eraNameOf,
  eraValueOf,
  primaryEraKey,
  sortByEraValue,
} from './timeline-era-axes';
import type { TimelineEventDTO } from './TimelineView';

function ev(id: string, extra?: Record<string, unknown> | null): TimelineEventDTO {
  return {
    id,
    title: `事件 ${id}`,
    narrative_position: Number(id.replace(/\D/g, '')) || 1,
    time_value: null,
    extra,
  };
}

const QY = '青元历';
const XJ = '仙历';

describe('#1353 eraKeyOf / eraNameOf / eraValueOf（承载键读取）', () => {
  it('R1 era 非空字符串 → 轴名（去空白）；era_value 数值 → 轴内值', () => {
    const e = ev('1', { era: '  青元历  ', era_value: 317.5 });
    expect(eraNameOf(e)).toBe('青元历');
    expect(eraKeyOf(e)).toBe(QY);
    expect(eraValueOf(e)).toBe(317.5);
  });

  it('R2 无 extra / era 缺失 / era 为空串或非字符串 → 默认轴，轴内值 null', () => {
    for (const extra of [undefined, null, {}, { era: '' }, { era: '   ' }, { era: 42 }] as const) {
      const e = ev('2', extra);
      expect(eraNameOf(e)).toBeNull();
      expect(eraKeyOf(e)).toBe(DEFAULT_ERA_KEY);
    }
    expect(eraValueOf(ev('3', { era: QY, era_value: '317' }))).toBeNull();
    expect(eraValueOf(ev('4', { era: QY }))).toBeNull();
  });

  it('R3 默认轴哨兵键固定（GUI testid / 0.16.0 契约锚点）', () => {
    expect(DEFAULT_ERA_KEY).toBe('__none__');
  });
});

describe('#1353 deriveEraAxes（轴族派生，含默认轴）', () => {
  it('R4 首次出现顺序 + 计数 + isDefault；默认轴与纪元轴并列（R6-4：不丢事件）', () => {
    const axes = deriveEraAxes([
      ev('1', { era: QY, era_value: 3 }),
      ev('2'),
      ev('3', { era: XJ, era_value: 9 }),
      ev('4', { era: QY, era_value: 5 }),
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
    const axes = deriveEraAxes([
      ev('1'),
      ev('2', { era: QY }),
      ev('3', { era: QY }),
    ]);

    expect(primaryEraKey(axes)).toBe(QY);
    expect(primaryEraKey([])).toBeNull();
  });

  it('R8 无纪元数据 → 默认轴即主力轴', () => {
    expect(primaryEraKey(deriveEraAxes([ev('1'), ev('2')]))).toBe(DEFAULT_ERA_KEY);
  });
});

describe('#1353 sortByEraValue（轴内排序）', () => {
  it('R9 era_value 升序、缺失排末尾、稳定且不改原数组', () => {
    const a = ev('1', { era: QY, era_value: 30 });
    const b = ev('2', { era: QY, era_value: 10 });
    const c = ev('3', { era: QY });
    const d = ev('4', { era: QY, era_value: null });
    const input = [a, b, c, d];

    const sorted = sortByEraValue(input);

    expect(sorted.map((e) => e.id)).toEqual(['2', '1', '3', '4']);
    expect(input.map((e) => e.id)).toEqual(['1', '2', '3', '4']);
  });
});
