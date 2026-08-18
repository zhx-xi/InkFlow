/**
 * 通用轮询工具（#472 R0 前置重构）：立即执行 + setTimeout 递归 + 终态停止 + cancel 清理
 * - 调用后立即执行一次 pollFn；非终态 → intervalMs（默认 1000）后再次执行
 * - 每轮 resolve 后先调 onValue（含终态轮）再判终态；终态 → 停止
 * - pollFn reject → 停止轮询且错误不外抛（try/catch 吞掉）
 * - cancel() → 置 cancelled + 清除已排程 timer；pollFn 在途时 resolve 后检查 cancelled 不再调度
 */
export interface PollHandle {
  cancel: () => void;
}

export interface StartPollingOptions<T> {
  /** 轮询间隔毫秒，默认 1000 */
  intervalMs?: number;
  /** 每轮 pollFn resolve 后回调（含终态轮） */
  onValue?: (value: T) => void;
}

export function startPolling<T>(
  pollFn: () => Promise<T>,
  isTerminal: (value: T) => boolean,
  options?: StartPollingOptions<T>,
): PollHandle {
  const intervalMs = options?.intervalMs ?? 1000;
  const onValue = options?.onValue;
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const run = async (): Promise<void> => {
    if (cancelled) return;
    let value: T;
    try {
      value = await pollFn();
    } catch {
      // pollFn reject → 停止轮询（不无限重试、错误不外抛）
      return;
    }
    if (cancelled) return; // pollFn 在途时被 cancel → 不再调度
    onValue?.(value);
    if (isTerminal(value)) return;
    timer = setTimeout(() => {
      void run();
    }, intervalMs);
  };

  void run();

  return {
    cancel: () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    },
  };
}
