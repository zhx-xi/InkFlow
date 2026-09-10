/**
 * 数据面变更订阅调度契约（F23 spec §15.5.4 / §15.6.3；§15.12.1 M7）
 *
 * ⚠️ 本文件 = 契约。GREEN 实现必须新建 src/hooks/useDataChangeSubscription.ts 并匹配：
 *
 * export const DEBOUNCE_MS = 300;
 * export function affectsCurrent(ev: DataChangeFrame, currentProjectId: string | null): boolean;
 * export type DataChangeInvalidate = (event: DataChangeFrame | null) => void;   // null = 重连兜底全量 refetch
 * export function useDataChangeSubscription(
 *   domains: readonly string[],
 *   onInvalidate: DataChangeInvalidate,
 * ): void;
 *
 * 行为契约：
 * - 全局单例订阅：多订阅者共享一条 subscribeDataChanges 连接（D15-6），不是每页面一条
 * - debounce 300ms：同一 project_id + domain 窗口内合并为一次失效；**反例**：不同 domain 不互相合并
 * - affectsCurrent（§15.6.3）：全局域（project_id 缺省）→ 生效；项目域不匹配 → 不生效
 * - self-originated：source === 'gui' → 跳过（本地写入已局部更新）
 * - 生命周期（§15.4.3）：kernelStatus !== 'ready' 不订阅；离开 ready / 无订阅者 → 断开
 * - 重连成功 → 订阅者收到 event = null（兜底全量 refetch，§15.5.4）
 * - 路由：只投递给登记了该 domain 的订阅者
 *
 * mock 方式：mock src/api/event-stream（捕获 onEvent/onReconnect 手动驱动）+ fake timers 精确控时
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { subscribeDataChanges, type DataChangeFrame } from '../api/event-stream';
import {
  DEBOUNCE_MS,
  affectsCurrent,
  useDataChangeSubscription,
  type DataChangeInvalidate,
} from './useDataChangeSubscription';
import { useKernelStore } from '../stores/kernel';
import { useProjectStore } from '../stores/project';

vi.mock('../api/event-stream', () => ({
  subscribeDataChanges: vi.fn(),
}));

const subscribeMock = vi.mocked(subscribeDataChanges);

/** 捕获被订阅的帧回调 / 重连回调（测试手动驱动）+ 记录连接被 abort 的次数 */
let emit: (ev: DataChangeFrame) => void;
let resync: () => void;
let aborts: number;

/** 事件帧构造（缺省 project_id = 全局域） */
function ev(patch: Partial<DataChangeFrame> = {}): DataChangeFrame {
  return { domain: 'map', op: 'create', resource_id: '1', source: 'cli', ...patch };
}

/** 冲刷微任务链（effect → ensureApiReady → startSubscription） */
async function settle(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

/** 推进防抖窗口 */
async function advance(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function mount(
  domains: readonly string[],
  onInvalidate: DataChangeInvalidate,
): Promise<ReturnType<typeof renderHook>> {
  const view = renderHook(() => useDataChangeSubscription(domains, onInvalidate));
  await settle();
  return view;
}

beforeEach(() => {
  vi.useFakeTimers();
  aborts = 0;
  emit = () => {};
  resync = () => {};
  subscribeMock.mockReset();
  subscribeMock.mockImplementation(async (onEvent, _onError, onReconnect) => {
    emit = onEvent;
    resync = onReconnect ?? (() => {});
    return () => {
      aborts += 1;
    };
  });
  useKernelStore.setState({ status: 'ready', booted: true, healthFailures: 0 });
  useProjectStore.setState({ currentProjectId: 'p1' });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('affectsCurrent — 全局域 / 项目域过滤（§15.6.3）', () => {
  it('project_id 缺省 → true（全局域总是生效，含当前无选中项目）', () => {
    expect(affectsCurrent(ev(), null)).toBe(true);
    expect(affectsCurrent(ev(), 'p1')).toBe(true);
  });

  it('project_id 显式 null → true（全局域；帧最简化时省略键，两者等价）', () => {
    expect(affectsCurrent(ev({ project_id: null }), 'p1')).toBe(true);
  });

  it('项目域：匹配当前项目 → true；不匹配 / 当前无项目 → false', () => {
    expect(affectsCurrent(ev({ project_id: 'p1' }), 'p1')).toBe(true);
    expect(affectsCurrent(ev({ project_id: 'p2' }), 'p1')).toBe(false);
    expect(affectsCurrent(ev({ project_id: 'p1' }), null)).toBe(false);
  });
});

describe('useDataChangeSubscription — 订阅生命周期（§15.4.3 / D15-6）', () => {
  it('全局单例：多个订阅者共享一条连接（subscribeDataChanges 仅 1 次）', async () => {
    const a = vi.fn();
    const b = vi.fn();
    renderHook(() => {
      useDataChangeSubscription(['map'], a);
      useDataChangeSubscription(['character'], b);
    });
    await settle();

    expect(subscribeMock).toHaveBeenCalledTimes(1);
  });

  it('只投递给登记了该 domain 的订阅者（无人关心 → 不触发）', async () => {
    const a = vi.fn();
    const b = vi.fn();
    await mount(['map'], a);
    const view = renderHook(() => useDataChangeSubscription(['character'], b));
    await settle();

    act(() => {
      emit(ev({ domain: 'map' }));
    });
    await advance(DEBOUNCE_MS);

    expect(a).toHaveBeenCalledTimes(1);
    expect(b).not.toHaveBeenCalled();
    view.unmount();
  });

  it('内核未就绪（booting）不发起订阅；ready 后订阅', async () => {
    useKernelStore.setState({ status: 'booting', booted: false, healthFailures: 0 });
    const handler = vi.fn();
    renderHook(() => useDataChangeSubscription(['map'], handler));
    await settle();
    expect(subscribeMock).not.toHaveBeenCalled();

    act(() => {
      useKernelStore.setState({ status: 'ready', booted: true });
    });
    await settle();
    expect(subscribeMock).toHaveBeenCalledTimes(1);
  });

  it('内核离开 ready → 断开订阅（单例句柄 abort）', async () => {
    await mount(['map'], vi.fn());
    expect(aborts).toBe(0);

    act(() => {
      useKernelStore.setState({ status: 'failed' });
    });
    expect(aborts).toBe(1);
  });

  it('最后一个订阅者卸载 → 断开连接（无泄漏）', async () => {
    const view = await mount(['map'], vi.fn());
    expect(aborts).toBe(0);

    view.unmount();
    expect(aborts).toBe(1);
  });

  it('domain 集合变化 → 只换路由表，不重建连接', async () => {
    const handler = vi.fn();
    const view = renderHook(
      ({ domains }: { domains: readonly string[] }) =>
        useDataChangeSubscription(domains, handler),
      { initialProps: { domains: ['map'] as readonly string[] } },
    );
    await settle();
    expect(subscribeMock).toHaveBeenCalledTimes(1);

    view.rerender({ domains: ['map', 'character'] });
    await settle();

    expect(subscribeMock).toHaveBeenCalledTimes(1);
    expect(aborts).toBe(0);
  });

  it('全部卸载后重新挂载（内核仍 ready）→ 重建单例连接', async () => {
    const first = await mount(['map'], vi.fn());
    expect(subscribeMock).toHaveBeenCalledTimes(1);
    first.unmount();
    expect(aborts).toBe(1);

    await mount(['map'], vi.fn());
    expect(subscribeMock).toHaveBeenCalledTimes(2);
    expect(aborts).toBe(1); // 新连接未被断开
  });
});

describe('useDataChangeSubscription — debounce 300ms 合并（§15.5.4）', () => {
  it('同一 project_id + domain 窗口内合并为一次失效（取最后一次事件）', async () => {
    const handler = vi.fn();
    await mount(['map'], handler);

    act(() => {
      emit(ev({ op: 'create', resource_id: '1', project_id: 'p1' }));
    });
    await advance(200);
    act(() => {
      emit(ev({ op: 'update', resource_id: '1', project_id: 'p1' }));
      emit(ev({ op: 'update', resource_id: '2', project_id: 'p1' }));
    });
    expect(handler).not.toHaveBeenCalled(); // 窗口内不触发（含重置计时）
    await advance(DEBOUNCE_MS - 1);
    expect(handler).not.toHaveBeenCalled();
    await advance(1);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0]).toMatchObject({ op: 'update', resource_id: '2' });
  });

  it('反例：不同 domain 的事件不互相合并（各自一次失效）', async () => {
    const handler = vi.fn();
    await mount(['map', 'character'], handler);

    act(() => {
      emit(ev({ domain: 'map', project_id: 'p1' }));
      emit(ev({ domain: 'character', resource_id: '9', project_id: 'p1' }));
    });
    await advance(DEBOUNCE_MS);

    expect(handler).toHaveBeenCalledTimes(2);
    const domains = (handler.mock.calls as Array<[DataChangeFrame]>)
      .map((call) => call[0].domain)
      .sort();
    expect(domains).toEqual(['character', 'map']);
  });

  it('不同 project_id 的事件不互相合并（各自的窗口）', async () => {
    const handler = vi.fn();
    await mount(['map'], handler);

    act(() => {
      emit(ev({ project_id: 'p1', resource_id: '1' }));
      emit(ev({ project_id: null, resource_id: '2' })); // 全局域（另一防抖键）
    });
    await advance(DEBOUNCE_MS);

    expect(handler).toHaveBeenCalledTimes(2);
  });
});

describe('useDataChangeSubscription — 过滤（self-originated / 项目域）', () => {
  it('self-originated（source=gui）跳过；source=cli 生效', async () => {
    const handler = vi.fn();
    await mount(['map'], handler);

    act(() => {
      emit(ev({ source: 'gui', project_id: 'p1' }));
    });
    await advance(DEBOUNCE_MS);
    expect(handler).not.toHaveBeenCalled();

    act(() => {
      emit(ev({ source: 'cli', resource_id: '2', project_id: 'p1' }));
    });
    await advance(DEBOUNCE_MS);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it('全局域事件（project_id 缺省）对当前项目生效；项目域不匹配则跳过', async () => {
    const handler = vi.fn();
    await mount(['agent_template', 'map'], handler);

    act(() => {
      emit(ev({ domain: 'agent_template', resource_id: '2' })); // 全局域
      emit(ev({ domain: 'map', resource_id: '7', project_id: 'other' })); // 项目域不匹配
    });
    await advance(DEBOUNCE_MS);

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0]).toMatchObject({ domain: 'agent_template' });
  });

  it('当前无选中项目时全局域事件仍生效（设置类页面可在无项目时打开）', async () => {
    useProjectStore.setState({ currentProjectId: null });
    const handler = vi.fn();
    await mount(['settings'], handler);

    act(() => {
      emit(ev({ domain: 'settings', resource_id: 'app' }));
    });
    await advance(DEBOUNCE_MS);

    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe('useDataChangeSubscription — 重连兜底（§15.5.4）', () => {
  it('重连成功 → 订阅者收到 event = null（兜底全量 refetch，无 domain 过滤）', async () => {
    const handler = vi.fn();
    await mount(['map'], handler);

    act(() => {
      resync();
    });

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith(null);
  });

  it('重连兜底不经过防抖（立即生效，不等待 300ms）', async () => {
    const handler = vi.fn();
    await mount(['map'], handler);

    act(() => {
      resync();
    });

    expect(handler).toHaveBeenCalledTimes(1);
    await advance(DEBOUNCE_MS);
    expect(handler).toHaveBeenCalledTimes(1); // 不重复触发
  });
});
