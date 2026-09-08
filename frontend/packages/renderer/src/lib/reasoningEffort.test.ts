/**
 * F59-M3 (#964) RED 契约 A — lib/reasoningEffort 纯函数契约。
 *
 * 契约源：plan.md §四 lib/reasoningEffort.ts（逐字为准）：
 *  - REASONING_EFFORTS = ['none','minimal','low','medium','high','xhigh','default']（声明顺序）
 *  - DEFAULT_REASONING_EFFORT === 'default'
 *  - reasoningEffortStorageKey(projectId) = 'inkflow.reasoning_effort.' + projectId
 *  - readReasoningEffort(projectId)：缺失/非法 → 'default'
 *  - writeReasoningEffort(projectId, value)：非七档 → no-op
 *
 * RED 形态：src/lib/reasoningEffort.ts 故意不存在 → import 失败（文件级 collection error）。
 */
import { describe, it, expect, beforeEach } from 'vitest';

import {
  REASONING_EFFORTS,
  DEFAULT_REASONING_EFFORT,
  reasoningEffortStorageKey,
  readReasoningEffort,
  writeReasoningEffort,
} from './reasoningEffort';

beforeEach(() => {
  localStorage.clear();
});

describe('reasoningEffort — 常量导出契约（#964）', () => {
  it('REASONING_EFFORTS 逐字等于七档（顺序即声明顺序）', () => {
    expect(REASONING_EFFORTS).toEqual(['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'default']);
  });

  it('DEFAULT_REASONING_EFFORT === default', () => {
    expect(DEFAULT_REASONING_EFFORT).toBe('default');
  });
});

describe('reasoningEffort — storage key 组装（#964）', () => {
  it('reasoningEffortStorageKey("p1") = 前缀 + projectId', () => {
    expect(reasoningEffortStorageKey('p1')).toBe('inkflow.reasoning_effort.p1');
  });
});

describe('reasoningEffort — read（#964）', () => {
  it('localStorage 空 → 返回 default', () => {
    expect(readReasoningEffort('p1')).toBe('default');
  });

  it('写入 high → 返回 high', () => {
    localStorage.setItem(reasoningEffortStorageKey('p1'), 'high');
    expect(readReasoningEffort('p1')).toBe('high');
  });

  it('非法值 bogus → 返回 default（不抛错）', () => {
    localStorage.setItem(reasoningEffortStorageKey('p1'), 'bogus');
    expect(() => readReasoningEffort('p1')).not.toThrow();
    expect(readReasoningEffort('p1')).toBe('default');
  });
});

describe('reasoningEffort — write（#964）', () => {
  it('write medium → localStorage 该键 = medium', () => {
    writeReasoningEffort('p1', 'medium');
    expect(localStorage.getItem(reasoningEffortStorageKey('p1'))).toBe('medium');
  });

  it('write bogus → 不写入（原本缺失 → 仍缺失）', () => {
    writeReasoningEffort('p1', 'bogus');
    expect(localStorage.getItem(reasoningEffortStorageKey('p1'))).toBeNull();
  });

  it('write bogus → 不覆盖已存在的原值', () => {
    localStorage.setItem(reasoningEffortStorageKey('p1'), 'high');
    writeReasoningEffort('p1', 'bogus');
    expect(localStorage.getItem(reasoningEffortStorageKey('p1'))).toBe('high');
  });

  it('跨 project 隔离：写 p1 不影响 p2', () => {
    writeReasoningEffort('p1', 'high');
    expect(localStorage.getItem(reasoningEffortStorageKey('p1'))).toBe('high');
    expect(localStorage.getItem(reasoningEffortStorageKey('p2'))).toBeNull();
  });
});
