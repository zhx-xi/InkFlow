/**
 * #1378：写作页右栏布局记忆（面板比例 + 栏宽）契约。
 *
 * 模块职责 = 纯读写 + 夹值：
 * - key 按项目隔离（镜像 #964 reasoningEffort 形态）
 * - 非法/损坏/越界值一律夹到合法区间或回退默认——**不信任存储内容**
 * - 存储不可用（隐私模式等）静默降级，不崩 UI
 * - 空 projectId（尚无当前项目）→ 读回默认、写不落盘
 *
 * 术语：split = context 面板占「两面板合计高度」的比例（2:1 → 2/3）。
 *   用占比而非 px：窗口 resize 时语义自然等比缩放（#1378 需求 1）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  DEFAULT_RAIL_SPLIT,
  DEFAULT_RAIL_WIDTH,
  RAIL_LAYOUT_STORAGE_PREFIX,
  RAIL_SPLIT_MAX,
  RAIL_SPLIT_MIN,
  RAIL_WIDTH_MAX,
  RAIL_WIDTH_MIN,
  clampRailSplit,
  clampRailWidth,
  railLayoutStorageKey,
  readRailLayout,
  writeRailLayout,
} from './railLayout';

const DEFAULTS = { split: DEFAULT_RAIL_SPLIT, width: DEFAULT_RAIL_WIDTH };

beforeEach(() => {
  localStorage.clear();
});

describe('railLayout — 存储键与默认值', () => {
  it('存储键按项目隔离：inkflow.rail_layout.<projectId>', () => {
    expect(RAIL_LAYOUT_STORAGE_PREFIX).toBe('inkflow.rail_layout.');
    expect(railLayoutStorageKey('p1')).toBe('inkflow.rail_layout.p1');
  });

  it('无存储 → 默认 2:1（split = 2/3）与 240px 右栏宽', () => {
    expect(DEFAULT_RAIL_SPLIT).toBeCloseTo(2 / 3, 10);
    expect(DEFAULT_RAIL_WIDTH).toBe(240);
    expect(readRailLayout('p1')).toEqual(DEFAULTS);
  });
});

describe('railLayout — 读写往返与项目隔离', () => {
  it('写入后可读回；部分写不覆盖未写字段', () => {
    writeRailLayout('p1', { split: 0.5 });
    expect(readRailLayout('p1').split).toBeCloseTo(0.5, 10);
    // 只写 split 不得把宽度打回默认/清掉
    expect(readRailLayout('p1').width).toBe(DEFAULT_RAIL_WIDTH);

    writeRailLayout('p1', { width: 400 });
    const back = readRailLayout('p1');
    expect(back.split).toBeCloseTo(0.5, 10);
    expect(back.width).toBe(400);
  });

  it('项目隔离：p1 的调整不影响 p2', () => {
    writeRailLayout('p1', { split: RAIL_SPLIT_MAX, width: RAIL_WIDTH_MAX });
    expect(readRailLayout('p2')).toEqual(DEFAULTS);
    expect(readRailLayout('p1')).toEqual({ split: RAIL_SPLIT_MAX, width: RAIL_WIDTH_MAX });
  });
});

describe('railLayout — 夹值（不出现负高/塌陷；不越 #720 既有区间）', () => {
  it('clampRailSplit 夹到 [RAIL_SPLIT_MIN, RAIL_SPLIT_MAX]', () => {
    expect(clampRailSplit(0.5)).toBeCloseTo(0.5, 10);
    expect(clampRailSplit(0)).toBe(RAIL_SPLIT_MIN);
    expect(clampRailSplit(-3)).toBe(RAIL_SPLIT_MIN);
    expect(clampRailSplit(9)).toBe(RAIL_SPLIT_MAX);
  });

  it('clampRailSplit 对 NaN / ±Infinity 回退默认（拖拽基准不可测时不得产生坏值）', () => {
    expect(clampRailSplit(Number.NaN)).toBe(DEFAULT_RAIL_SPLIT);
    expect(clampRailSplit(Number.POSITIVE_INFINITY)).toBe(DEFAULT_RAIL_SPLIT);
    expect(clampRailSplit(Number.NEGATIVE_INFINITY)).toBe(DEFAULT_RAIL_SPLIT);
  });

  it('clampRailWidth 夹到 [90, 540]（#720 既有拖拽区间）+ NaN 回退默认', () => {
    expect(clampRailWidth(300)).toBe(300);
    expect(clampRailWidth(10)).toBe(RAIL_WIDTH_MIN);
    expect(clampRailWidth(9999)).toBe(RAIL_WIDTH_MAX);
    expect(clampRailWidth(Number.NaN)).toBe(DEFAULT_RAIL_WIDTH);
  });
});

describe('railLayout — 存储内容不可信（越界 / 垃圾 / 损坏）', () => {
  it('越界值 → 夹到合法区间；非数字字段 → 回退该项默认', () => {
    localStorage.setItem(railLayoutStorageKey('p1'), JSON.stringify({ split: 5, width: -10 }));
    expect(readRailLayout('p1')).toEqual({ split: RAIL_SPLIT_MAX, width: RAIL_WIDTH_MIN });

    localStorage.setItem(railLayoutStorageKey('p1'), JSON.stringify({ split: 'x', width: null }));
    expect(readRailLayout('p1')).toEqual(DEFAULTS);
  });

  it('JSON 损坏 → 回退默认，不抛错', () => {
    localStorage.setItem(railLayoutStorageKey('p1'), '{not-json');
    expect(readRailLayout('p1')).toEqual(DEFAULTS);
  });

  it('空 projectId（尚无当前项目）→ 读默认、写 no-op（不落盘）', () => {
    expect(readRailLayout('')).toEqual(DEFAULTS);
    writeRailLayout('', { split: 0.5, width: 400 });
    expect(localStorage.getItem(railLayoutStorageKey(''))).toBeNull();
    expect(localStorage.length).toBe(0);
  });
});

describe('railLayout — 存储不可用（隐私模式）静默降级', () => {
  it('getItem 抛错 → 读回默认，不抛给调用方', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    try {
      expect(() => readRailLayout('p1')).not.toThrow();
      expect(readRailLayout('p1')).toEqual(DEFAULTS);
    } finally {
      spy.mockRestore();
    }
  });

  it('setItem 抛错 → 写静默失败，不抛给调用方', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage denied');
    });
    try {
      expect(() => writeRailLayout('p1', { split: 0.5 })).not.toThrow();
    } finally {
      spy.mockRestore();
    }
  });
});
