/**
 * F59-M3 (#964) RED 契约 A — i18n reasoning.* 域词条契约。
 *
 * 契约源：plan.md §四 i18n（zh / en）reasoning.* 键，逐字为准。
 * 只 import useI18n + useThemeStore（不 import 未建模块）→ 保证逐用例 FAIL 而非 collection error。
 * RED 形态：zh/en 尚无 reasoning.* 键 → t(key) 回退 key 本身 → 断言 FAIL。
 */
import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';

import { useI18n } from './useI18n';
import { useThemeStore } from '../stores/theme';

/** 七档 level（与 plan §四 一致） */
const LEVEL_KEYS = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'default'] as const;

/**
 * 全键清单（共 9 键，plan §四 逐字）：
 * reasoning.chat.label / reasoning.chat.disabledTooltip + reasoning.level.{7 档}
 * （任务书写「10 个键」，但 plan §四 枚举 9 键；以 plan 为准 → 9，见报告偏差说明）
 */
const ALL_KEYS = [
  'reasoning.chat.label',
  'reasoning.chat.disabledTooltip',
  ...LEVEL_KEYS.map((l) => `reasoning.level.${l}`),
];

const LEVEL_ZH: Record<string, string> = {
  none: '关闭思考',
  minimal: '最低',
  low: '低',
  medium: '中',
  high: '高',
  xhigh: '极高',
  default: '跟随模型默认',
};

const LEVEL_EN: Record<string, string> = {
  none: 'Off',
  minimal: 'Minimal',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  xhigh: 'Extra high',
  default: 'Model default',
};

/** 切语言 + 渲染 useI18n 并返回 t()（与 i18n.contract.test.ts 同形态） */
function getI18n(lang: 'zh' | 'en') {
  useThemeStore.setState({ lang });
  return renderHook(() => useI18n()).result.current;
}

describe('F59-M3 — reasoning.* i18n 契约（#964）', () => {
  it('zh 下全键 t(key) !== key（无裸 key 回退）', () => {
    const zh = getI18n('zh');
    for (const k of ALL_KEYS) {
      expect(zh.t(k), `${k} 缺中文词条`).not.toBe(k);
    }
  });

  it('en 下全键 t(key) !== key（无裸 key 回退）', () => {
    const en = getI18n('en');
    for (const k of ALL_KEYS) {
      expect(en.t(k), `${k} 缺英文词条`).not.toBe(k);
    }
  });

  it('zh/en 值互不相同（防 en 静默中文）', () => {
    const zh = getI18n('zh');
    const en = getI18n('en');
    for (const k of ALL_KEYS) {
      expect(zh.t(k), `${k} zh/en 值相同`).not.toBe(en.t(k));
    }
  });
});

describe('F59-M3 — reasoning.level.* 七档逐字（#964）', () => {
  it('zh 七档逐字（码点级）', () => {
    const zh = getI18n('zh');
    for (const [l, v] of Object.entries(LEVEL_ZH)) {
      expect(zh.t(`reasoning.level.${l}`), `zh reasoning.level.${l}`).toBe(v);
    }
  });

  it('en 七档逐字（码点级）', () => {
    const en = getI18n('en');
    for (const [l, v] of Object.entries(LEVEL_EN)) {
      expect(en.t(`reasoning.level.${l}`), `en reasoning.level.${l}`).toBe(v);
    }
  });
});
