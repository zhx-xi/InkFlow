/**
 * 数据面变更订阅调度（F23 spec §15.5.4 / §15.6.3 / D15-6）
 *
 * - **全局单例订阅**：全应用仅一条 SSE 连接（模块级注册表持有），不是每页面各订阅；
 *   页面只注册「我关心哪些 domain」+ 失效回调，路由/过滤/防抖统一在本模块（避免 N 页面 N 连接）
 * - **self-originated 过滤**：source === 'gui' 跳过（本地写入已有局部更新，§15.5.3 E1）
 * - **项目域过滤**：affectsCurrent —— project_id 缺省（全局域）总是生效；项目域仅当前项目（§15.6.3）
 * - **防抖 300ms**：同一 project_id + domain 在窗口内合并为一次失效（吸收 burst）
 * - **生命周期对齐**：kernelStatus === 'ready' 且 await ensureApiReady() 后才发起订阅（§15.4.3）
 * - **重连兜底**：底层客户端指数退避重连；重连成功视为「可能错过事件」→ 订阅者收到
 *   event = null（兜底全量 refetch，§15.5.4）
 */

import { useEffect, useRef } from 'react';
import { subscribeDataChanges, type DataChangeFrame } from '../api/event-stream';
import { ensureApiReady } from '../api/client';
import { useKernelStore } from '../stores/kernel';
import { useProjectStore } from '../stores/project';

/** debounce 窗口（spec §15.5.4：同一 project_id + domain 合并为一次 reload） */
export const DEBOUNCE_MS = 300;

/** 全局域事件在防抖键中的占位（project_id 缺省；避免与真实 UUID 冲突用 '#' 前缀） */
const GLOBAL_SCOPE = '#global';

/**
 * 事件是否对当前上下文生效（spec §15.6.3）。
 * - 全局域（project_id 缺省）→ 总是生效（即使当前无选中项目）
 * - 项目域 → 仅当前项目
 * - 安全偏向：项目域事件未带 project_id（§15.3.2 已知例外）→ 视为生效（多刷一次，不漏刷）
 */
export function affectsCurrent(ev: DataChangeFrame, currentProjectId: string | null): boolean {
  if (ev.project_id == null) return true;
  return ev.project_id === currentProjectId;
}

/** 页面失效回调：event = null 表示重连后的兜底全量 refetch（忽略 domain/project 过滤） */
export type DataChangeInvalidate = (event: DataChangeFrame | null) => void;

interface Subscriber {
  domains: Set<string>;
  onInvalidate: DataChangeInvalidate;
}

/** 已注册订阅者（页面级；同一域可多订阅者） */
const subscribers = new Set<Subscriber>();
/** 待 flush 的防抖计时器：key = project_id|domain → 最近一次事件对应的计时器 */
const pendingFlush = new Map<string, ReturnType<typeof setTimeout>>();

/** 全局单例连接句柄（D15-6：一条 SSE 连接，跨页面复用） */
let connectionAbort: (() => void) | null = null;
let connecting = false;
/** 是否需要连接（内核未就绪 / 全部订阅者卸载 → false） */
let wanted = false;
/** 启动代次：连接建立期间被要求停止 → 丢弃迟到的句柄（竞态保护） */
let generation = 0;
/** 存活的 hook 实例数：最后一个卸载 → 断开单例连接（无泄漏） */
let instances = 0;

function handleError(message: string): void {
  console.warn('[data-change] 变更订阅流中断:', message);
}

function deliver(frame: DataChangeFrame): void {
  for (const subscriber of [...subscribers]) {
    if (subscriber.domains.has(frame.domain)) subscriber.onInvalidate(frame);
  }
}

/** 重连成功 → 各订阅者兜底全量 refetch（§15.5.4：收敛断线期间的陈旧） */
function handleReconnect(): void {
  for (const subscriber of [...subscribers]) subscriber.onInvalidate(null);
}

function handleFrame(frame: DataChangeFrame): void {
  if (frame.source === 'gui') return; // self-originated：本地写入已局部更新
  if (!affectsCurrent(frame, useProjectStore.getState().currentProjectId)) return;
  if (![...subscribers].some((s) => s.domains.has(frame.domain))) return; // 无人关心

  const key = `${frame.project_id ?? GLOBAL_SCOPE}|${frame.domain}`;
  const timer = pendingFlush.get(key);
  if (timer !== undefined) clearTimeout(timer); // 窗口内合并：重置计时
  pendingFlush.set(
    key,
    setTimeout(() => {
      pendingFlush.delete(key);
      deliver(frame);
    }, DEBOUNCE_MS),
  );
}

/** 发起单例订阅（幂等：已连接 / 连接中 → 无操作） */
function startSubscription(): void {
  wanted = true;
  if (connectionAbort !== null || connecting) return;
  connecting = true;
  const gen = (generation += 1);
  void subscribeDataChanges(handleFrame, handleError, handleReconnect).then(
    (abort) => {
      connecting = false;
      if (!wanted || gen !== generation) {
        abort(); // 建立期间已被要求停止 → 立即断开，不泄漏连接
        return;
      }
      connectionAbort = abort;
    },
    () => {
      connecting = false;
    },
  );
}

/** 内核已就绪时的单例连接保活（覆盖「首个订阅者挂载 / 全部卸载后重新挂载」） */
function ensureSubscription(): void {
  void ensureApiReady().then(() => {
    // 等待 preload 注入期间内核可能已退出 ready → 不再发起（§15.4.3）
    if (useKernelStore.getState().status === 'ready') startSubscription();
  });
}

/** 断开单例订阅 + 丢弃待 flush 的防抖（幂等） */
function stopSubscription(): void {
  wanted = false;
  generation += 1;
  connecting = false;
  if (connectionAbort !== null) {
    connectionAbort();
    connectionAbort = null;
  }
  for (const timer of pendingFlush.values()) clearTimeout(timer);
  pendingFlush.clear();
}

/**
 * 注册「我关心这些 domain」并接入全局单例订阅。
 *
 * @param domains 关心的变更域（页面按 §15.6.2 失效矩阵登记；空数组 = 只保活连接）
 * @param onInvalidate 失效回调（事件 → 调既有 loadXxx / invalidate；event = null → 兜底全量 refetch）
 */
export function useDataChangeSubscription(
  domains: readonly string[],
  onInvalidate: DataChangeInvalidate,
): void {
  const kernelStatus = useKernelStore((s) => s.status);
  const handlerRef = useRef(onInvalidate);
  // domain 集合稳定化（内联数组字面量不应导致重注册）
  const domainsKey = domains.join('\u0000');

  useEffect(() => {
    handlerRef.current = onInvalidate;
  }, [onInvalidate]);

  // 全局单例连接的生命周期 = 存活的订阅者实例（不是每页面一条连接，D15-6）
  useEffect(() => {
    instances += 1;
    return () => {
      instances -= 1;
      if (instances === 0) stopSubscription();
    };
  }, []);

  // 注册订阅者：domain 集合变化只换路由表，不重建连接
  useEffect(() => {
    const subscriber: Subscriber = {
      domains: new Set(domainsKey === '' ? [] : domainsKey.split('\u0000')),
      onInvalidate: (event) => handlerRef.current(event),
    };
    subscribers.add(subscriber);
    if (useKernelStore.getState().status === 'ready') ensureSubscription();
    return () => {
      subscribers.delete(subscriber);
    };
  }, [domainsKey]);

  // 与内核生命周期对齐（§15.4.3）：ready + preload 注入就绪后才订阅
  useEffect(() => {
    if (kernelStatus !== 'ready') {
      stopSubscription();
      return;
    }
    ensureSubscription();
  }, [kernelStatus]);
}
