/**
 * ⚠️ 契约文件（Issue #105，spec §6.2① / §7.6 stores/toast.ts；Q3=B 队列堆叠拍板）
 *
 * GREEN 新建 src/stores/toast.ts，必须匹配：
 *
 * 导出：
 * - useToastStore：Zustand store（create<ToastState>）
 * - ToastType = 'ok' | 'err' | 'warn'（三态，spec §6.2①）
 * - Toast = { id: string; type: ToastType; message: string }
 * - ToastState = {
 *     toasts: Toast[];
 *     pushToast: (type: ToastType, message: string) => void;
 *     dismissToast: (id: string) => void;
 *   }
 *
 * 行为（spec §6.2① 三态/2s 自动消失；Q3=B 拍板）：
 * - pushToast(type, message) 追加 toasts 尾部；id 唯一非空（实现自定：crypto.randomUUID/计数器）
 * - 每条 toast 2s 后自动消失（setTimeout 2000ms）
 * - 队列堆叠上限 3：push 第 4 条时丢弃最早一条（Q3=B「超出丢弃最早」，防刷屏）
 * - dismissToast(id) 手动移除；对不存在 id 幂等 no-op（2s 定时器触发时同样安全）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useToastStore } from './toast';

beforeEach(() => {
  vi.useFakeTimers();
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('toast store — 契约面', () => {
  it('初始 toasts 为空；pushToast/dismissToast 为函数', () => {
    expect(useToastStore.getState().toasts).toEqual([]);
    expect(typeof useToastStore.getState().pushToast).toBe('function');
    expect(typeof useToastStore.getState().dismissToast).toBe('function');
  });

  it('pushToast 追加单条：type/message 正确，id 唯一非空', () => {
    useToastStore.getState().pushToast('ok', '已保存');
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].type).toBe('ok');
    expect(toasts[0].message).toBe('已保存');
    expect(toasts[0].id).toBeTruthy();

    useToastStore.getState().pushToast('err', '保存失败');
    const second = useToastStore.getState().toasts[1];
    expect(second.id).not.toBe(toasts[0].id);
  });

  it('三态：ok / err / warn 各按其型入队', () => {
    useToastStore.getState().pushToast('ok', 'A');
    useToastStore.getState().pushToast('err', 'B');
    useToastStore.getState().pushToast('warn', 'C');
    expect(useToastStore.getState().toasts.map((t) => t.type)).toEqual(['ok', 'err', 'warn']);
  });
});

describe('toast store — 2s 自动消失（spec §6.2①）', () => {
  it('push 后 1999ms 仍在，2000ms 消失', () => {
    useToastStore.getState().pushToast('ok', '已保存');
    expect(useToastStore.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(1999);
    expect(useToastStore.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

describe('toast store — 队列堆叠上限 3（Q3=B：超出丢弃最早）', () => {
  it('连续 push 4 条 → 保留 3 条且丢弃最早；2s 后全部清空（被弃条定时器 no-op）', () => {
    useToastStore.getState().pushToast('ok', '第一条');
    useToastStore.getState().pushToast('warn', '第二条');
    useToastStore.getState().pushToast('err', '第三条');
    useToastStore.getState().pushToast('ok', '第四条');

    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(3);
    expect(toasts.map((t) => t.message)).toEqual(['第二条', '第三条', '第四条']);

    vi.advanceTimersByTime(2000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

describe('toast store — dismissToast', () => {
  it('手动移除指定 id；重复 dismiss 幂等 no-op', () => {
    useToastStore.getState().pushToast('ok', '第一条');
    useToastStore.getState().pushToast('err', '第二条');
    const firstId = useToastStore.getState().toasts[0].id;

    useToastStore.getState().dismissToast(firstId);
    expect(useToastStore.getState().toasts.map((t) => t.message)).toEqual(['第二条']);

    // 幂等：已移除 id 再 dismiss 不报错、状态不变
    useToastStore.getState().dismissToast(firstId);
    expect(useToastStore.getState().toasts).toHaveLength(1);
  });
});

describe('toast store — id 兜底（无 crypto.randomUUID 环境，L27-29 fallback 分支）', () => {
  it('crypto 缺失/无 randomUUID → fallback id 仍唯一非空（toast-时间戳-计数器）', () => {
    vi.stubGlobal('crypto', {});

    useToastStore.getState().pushToast('ok', 'A');
    useToastStore.getState().pushToast('warn', 'B');

    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(2);
    expect(toasts[0].id).toMatch(/^toast-\d+-\d+$/);
    expect(toasts[1].id).toMatch(/^toast-\d+-\d+$/);
    expect(toasts[0].id).not.toBe(toasts[1].id);
  });
});
