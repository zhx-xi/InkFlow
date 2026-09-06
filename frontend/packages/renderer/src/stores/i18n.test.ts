/**
 * ⚠️ 契约文件（#957 F58 §4.3 远端 i18n 目录消费）。
 *
 * GREEN 新建 src/stores/i18n.ts，必须匹配：
 * - `useI18nMessagesStore`：{ messages: Record<string,string>; loadedLang: string | null; load(lang) }
 *   - load 单飞：loadedLang===lang 或同 lang 在途 → 直接 return；否则 fetchLogMessages(lang) → set({messages, loadedLang})。
 *   - 失败静默：messages/loadedLang 不变，tScope 走本地回退。
 * - `useTScope(): (key: string) => string`：远端目录命中 > 本地 t()（含 zh 回退链）。
 * - 依赖方向：stores/i18n → api/logs（fetchLogMessages）→ api/client，无环。
 *
 * RED 预期：./i18n 模块不存在 → 文件级 collection error（合法 RED 信号，非逐用例）。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { fetchLogMessages } from '../api/logs';
import { useI18nMessagesStore, useTScope } from './i18n';

vi.mock('../api/logs', () => ({ fetchLogMessages: vi.fn() }));

const fetchLogMessagesMock = vi.mocked(fetchLogMessages);

beforeEach(() => {
  fetchLogMessagesMock.mockReset();
  useI18nMessagesStore.setState({ messages: {}, loadedLang: null });
});

describe('useI18nMessagesStore — load 单飞（§4.3）', () => {
  it('两次同 lang 只 fetch 一次（loadedLang 命中直接 return）', async () => {
    fetchLogMessagesMock.mockResolvedValue({ 'agent.scope.read': '读' });
    const p1 = useI18nMessagesStore.getState().load('zh');
    const p2 = useI18nMessagesStore.getState().load('zh');
    await Promise.all([p1, p2]);
    expect(fetchLogMessagesMock).toHaveBeenCalledTimes(1);
    expect(fetchLogMessagesMock).toHaveBeenCalledWith('zh');
    expect(useI18nMessagesStore.getState().loadedLang).toBe('zh');
  });

  it('首次 load 后再次同 lang 不重复拉取（loadedLang 缓存）', async () => {
    fetchLogMessagesMock.mockResolvedValue({});
    await useI18nMessagesStore.getState().load('zh');
    await useI18nMessagesStore.getState().load('zh');
    expect(fetchLogMessagesMock).toHaveBeenCalledTimes(1);
  });

  it('不同 lang 各自拉取（每次新 lang）', async () => {
    fetchLogMessagesMock.mockResolvedValue({});
    await useI18nMessagesStore.getState().load('zh');
    await useI18nMessagesStore.getState().load('en');
    expect(fetchLogMessagesMock).toHaveBeenCalledTimes(2);
    expect(fetchLogMessagesMock).toHaveBeenCalledWith('en');
  });
});

describe('useI18nMessagesStore — 失败静默（§4.3）', () => {
  it('load 失败：messages/loadedLang 不变，不 rethrow（tScope 走本地回退）', async () => {
    useI18nMessagesStore.setState({ messages: { 'x': '1' }, loadedLang: 'zh' });
    fetchLogMessagesMock.mockRejectedValue(new Error('network'));
    await expect(useI18nMessagesStore.getState().load('en')).resolves.toBeUndefined();
    expect(useI18nMessagesStore.getState().messages).toEqual({ 'x': '1' });
    expect(useI18nMessagesStore.getState().loadedLang).toBe('zh');
  });
});

describe('useTScope — 双层取词（§4.3）', () => {
  it('远端目录命中优先于本地 t()', () => {
    useI18nMessagesStore.setState({ messages: { 'agent.scope.read': '远端读' }, loadedLang: 'zh' });
    const tScope = useTScope();
    expect(tScope('agent.scope.read')).toBe('远端读');
  });

  it('远端未命中 → 回退本地 t()（zh 词条）', () => {
    useI18nMessagesStore.setState({ messages: { 'unrelated.key': 'x' }, loadedLang: 'zh' });
    const tScope = useTScope();
    expect(tScope('agent.scope.domain.outline')).toBe('大纲');
  });

  it('远端目录为空且本地亦无该键 → 回退 key 本身（不崩）', () => {
    useI18nMessagesStore.setState({ messages: {}, loadedLang: 'zh' });
    const tScope = useTScope();
    expect(tScope('totally.missing.key')).toBe('totally.missing.key');
  });
});
