/**
 * F2 i18n 契约测试（S3e，2026-09-02）。
 *
 * 范围（对应 S3e 前端质量补测 F2）：
 * ① key 对称：zh/en 运行时字典 key 集合一致——
 *    防「en 下漏 key 静默回退中文」（useI18n t() 缺 key 时落 `zh[key] ?? key`）。
 * ② 组件 t() 引用有效：src 内所有 `t('字面量 key')` 都必须命中字典。
 * ③ 插值健壮性：缺参 / 多余参 / {unknown} 占位符 —— 不崩，且行为确定。
 *
 * 注意：这是「守护型」契约测试——③ 断言既有稳健行为；①② 为防未来回归的护栏。
 * 若某页在某状态下漏了 key / 引用了不存在的 key，会在此先 FAIL。
 */

import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { bookEn, bookZh } from './book';
import { chatDeleteUxEn, chatDeleteUxZh } from './chat-delete-ux';
import { chatUxEn, chatUxZh } from './chat-ux';
import { en } from './en';
import { extractEn, extractZh } from './extract-keys';
import { logEn, logZh } from './log';
// #496（contract-496 §4.2）：logs-ux 域（日志页 UI 文案）并入 combo —— RED 期该模块不存在，
// 本文件收集期 module-not-found（预期【R】），GREEN 新建 logs-ux.ts（导出 logsUxZh/logsUxEn）即愈
import { logsUxEn, logsUxZh } from './logs-ux';
import { roleEnhanceEn, roleEnhanceZh } from './role-enhance';
import { sessionUxEn, sessionUxZh } from './session-ux';
import { sessionsUxEn, sessionsUxZh } from './sessions-ux';
import { useI18n } from './useI18n';
import { worldCatKindEn, worldCatKindZh } from './world-cat-kind';
import { writingUxEn, writingUxZh } from './writing-ux';
import { zh } from './zh';

type Dict = Record<string, string>;

/** 与 useI18n.ts 的 dicts 组合逻辑保持一致（测试引用同一组合语义） */
const comboZh: Dict = {
  ...zh,
  ...roleEnhanceZh,
  ...extractZh,
  ...worldCatKindZh,
  ...chatUxZh,
  ...chatDeleteUxZh,
  ...sessionsUxZh,
  ...writingUxZh,
  ...sessionUxZh,
  ...logZh,
  ...bookZh,
  // #496 §4.2：logs-ux 域（GREEN 建文件即愈）
  ...logsUxZh,
} as Dict;
const comboEn: Dict = {
  ...en,
  ...roleEnhanceEn,
  ...extractEn,
  ...worldCatKindEn,
  ...chatUxEn,
  ...chatDeleteUxEn,
  ...sessionsUxEn,
  ...writingUxEn,
  ...sessionUxEn,
  ...logEn,
  ...bookEn,
  // #496 §4.2：logs-ux 域（GREEN 建文件即愈）
  ...logsUxEn,
} as Dict;

describe('F2 i18n 契约：key 对称', () => {
  it('zh/en key 集合完全一致（0 漂移 → 防 en 漏 key 静默回退中文）', () => {
    const zhKeys = Object.keys(comboZh).sort();
    const enKeys = Object.keys(comboEn).sort();
    const zhOnly = zhKeys.filter((k) => !enKeys.includes(k));
    const enOnly = enKeys.filter((k) => !zhKeys.includes(k));
    expect({ zhOnly, enOnly }).toEqual({ zhOnly: [], enOnly: [] });
  });

  it('字典必须有实际内容（防空字典假绿）', () => {
    expect(Object.keys(comboZh).length).toBeGreaterThan(800);
    expect(Object.keys(comboEn).length).toEqual(Object.keys(comboZh).length);
  });
});

describe('F2 i18n 契约：组件 t() 引用有效', () => {
  it('src 内所有 t(\'静态字面量 key\') 必须命中字典（防组件引用不存在的 key）', () => {
    const globber = import.meta.glob(
      ['../**/*.{ts,tsx}'],
      { query: '?raw', import: 'default', eager: true },
    ) as Record<string, string>;
    const missing: string[] = [];
    for (const [path, src] of Object.entries(globber)) {
      if (path.includes('.test.')) continue;
      if (path.includes('/i18n/')) continue;
      const re = /\bt\(\s*['"]([A-Za-z0-9._]+)['"]\s*[,)]/g;
      let m: RegExpExecArray | null;
      while ((m = re.exec(src)) !== null) {
        const key = m[1];
        if (!(key in comboZh) && !(key in comboEn)) {
          missing.push(`${path.replace('../', '')} → ${key}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it('状态/类型映射动态 key 必须命中字典（抽查高频 fallback 键）', () => {
    const statusLabels = [
      'sessions.status.active',
      'sessions.status.paused',
      'sessions.status.completed',
      'sessions.status.failed',
      'sessions.planner.status.drafting',
      'sessions.planner.status.completed',
      'sessions.planner.status.declined',
      'sessions.type.writing',
      'sessions.type.task',
    ];
    for (const k of statusLabels) {
      expect(k in comboZh, `${k} 应在 zh dict`).toBe(true);
      expect(k in comboEn, `${k} 应在 en dict`).toBe(true);
    }
  });
});

describe('F2 i18n 契约：插值健壮性（不崩 + 行为确定）', () => {
  it('缺参：{placeholder} 无对应参数 → 原样保留 {key}，不抛错', () => {
    const { result } = renderHook(() => useI18n());
    // write.stream.done 模板含 {words} {model} {valid}；只给 words/model → valid 缺参
    const out = result.current.t('write.stream.done', { words: 342, model: 'x' });
    expect(out).toContain('342');
    expect(out).toContain('x');
    expect(out).toContain('{valid}');
  });

  it('多余参：params 含模板未用到的 key → 忽略，输出与只给必需参数一致', () => {
    const { result } = renderHook(() => useI18n());
    const base = result.current.t('write.stream.done', { words: 1, model: 'm', valid: '通过' });
    const withExtra = result.current.t('write.stream.done', {
      words: 1,
      model: 'm',
      valid: '通过',
      extraKey: 'unused',
    });
    expect(withExtra).toBe(base);
  });

  it('额外 {unknown} 参数：不影响输出（模板只引用其占位符）', () => {
    const { result } = renderHook(() => useI18n());
    const out = result.current.t('write.stream.done', {
      words: 1,
      model: 'm',
      valid: '通过',
      unknown: 'x',
    });
    expect(out).not.toContain('x');
  });

  it('不存在的 key：回退不崩（zh 模式回退 key 本身）', () => {
    const { result } = renderHook(() => useI18n());
    const out = result.current.t('totally.nonexistent.key');
    expect(typeof out).toBe('string');
    expect(out).toBe('totally.nonexistent.key');
  });

  it('无参调用：模板含占位符但未传 params → 全部保留字面占位符，不崩', () => {
    const { result } = renderHook(() => useI18n());
    const out = result.current.t('write.stream.done');
    expect(out).toContain('{words}');
    expect(out).toContain('{model}');
    expect(out).toContain('{valid}');
  });

  it('en 模式值确实切换了语言（value 采样 ≠ zh，防 en 页静默中文化）', () => {
    // zh/en key 一致由对称测试保证；此处采样互译验证「切语言」而非「同文案」
    expect(comboEn['write.stream.done']).not.toBe(comboZh['write.stream.done']);
    expect(comboEn['pj.empty.title']).not.toBe(comboZh['pj.empty.title']);
  });
});

/**
 * F57 #888-S3：日志页 msgid（log.event.*）与后端 messages 键对齐。
 * 契约：specs/f57-logging-i18n/spec.md §2.1（前端 i18n/log.ts 与后端 messages 键对齐，
 * 同一 msgid）+ 后端 backend/src/inkflow/i18n/messages/{zh,en}.json 已定义的 log.event.* 键。
 * 这组消息键由前端 logger 上报 message_key 引用，日志页用 t(key, params) 渲染 → 键必须存在。
 */
describe('F57 i18n 契约：log 域键对称 + 后端 messages 对齐', () => {
  it('logZh/logEn key 集合完全一致（0 漂移 → 防 en 漏 key 静默回退中文）', () => {
    const zhKeys = Object.keys(logZh).sort();
    const enKeys = Object.keys(logEn).sort();
    expect(zhKeys).toEqual(enKeys);
  });

  it('log 字典有实际内容（防空字典假绿）', () => {
    expect(Object.keys(logZh).length).toBeGreaterThan(0);
  });

  it('log.event.* 键与后端 messages 的 log.event.* 键对齐（同一 msgid 命名空间）', () => {
    // 后端 messages zh.json（S1 已落盘，2026-09-03）定义的 log.event.* 键——前端 log.ts 必须包含同 msgid。
    // #496（contract-496 §4.1）：追加 kernel_* 5 键（内核生命周期事件，electron 主进程上报链路 #892 已就绪）——【R】扩 5 键
    const backendLogKeys = [
      'log.event.create_chapter',
      'log.event.update_project',
      'log.event.delete_project',
      'log.event.kernel_ready',
      'log.event.kernel_failure',
      'log.event.kernel_exit',
      'log.event.kernel_spawn_error',
      'log.event.kernel_crash',
    ];
    for (const k of backendLogKeys) {
      expect(k in logZh, `${k} 应在前端 logZh 字典（与后端 messages 对齐）`).toBe(true);
      expect(k in logEn, `${k} 应在前端 logEn 字典（与后端 messages 对齐）`).toBe(true);
    }
  });

  it('log 键全部以 log.event. / log.call. / api.error. 前缀命名（日志 msgid 命名空间），不留散键', () => {
    // #930：放开 log.call. 前缀——log.call.* 通用回退词条（log.call.generic）入字典。
    const keys = [...Object.keys(logZh), ...Object.keys(logEn)];
    for (const k of keys) {
      expect(k).toMatch(/^(log\.event\.|log\.call\.|api\.error\.)/);
    }
  });

  it('#930：log.call.generic 通用回退词条存在（zh/en），渲染卡片标题防裸 key', () => {
    expect(logZh['log.call.generic']).toContain('{caller_name}');
    expect(logEn['log.call.generic']).toContain('{caller_name}');
    expect(logZh['log.call.generic']).not.toBe(logEn['log.call.generic']);
  });
});
