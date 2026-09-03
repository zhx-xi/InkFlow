/** F57 #888-S3 Electron 主进程结构化日志（上报 /api/v1/logs，聚合进后端 loguru 同一流）。 */

export type MainLogLevel = 'debug' | 'info' | 'warn' | 'error';

export interface MainLogRecord {
  level: MainLogLevel;
  caller_type: 'frontend';
  caller_name: string;
  event: string;
  message_key: string;
  params: Record<string, unknown>;
  correlation_id: string;
  timestamp: string;
}

export interface MainLogger {
  debug(event: string, messageKey: string, params?: Record<string, unknown>): void;
  info(event: string, messageKey: string, params?: Record<string, unknown>): void;
  warn(event: string, messageKey: string, params?: Record<string, unknown>): void;
  error(event: string, messageKey: string, params?: Record<string, unknown>): void;
}

interface MainLogEndpoint {
  baseURL: string;
  token: string;
}

let currentEndpoint: MainLogEndpoint = { baseURL: '', token: '' };

export function setMainLogEndpoint(baseURL: string, token: string): void {
  currentEndpoint = { baseURL: baseURL ?? '', token: token ?? '' };
}

export function getMainLogEndpoint(): MainLogEndpoint {
  return currentEndpoint;
}

function newCorrelationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `corr-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const CONSOLE_BY_LEVEL: Record<MainLogLevel, (...args: unknown[]) => void> = {
  debug: (...a) => console.debug(...a),
  info: (...a) => console.info(...a),
  warn: (...a) => console.warn(...a),
  error: (...a) => console.error(...a),
};

export function createMainLogger(callerName: string): MainLogger {
  const emit = (
    level: MainLogLevel,
    event: string,
    messageKey: string,
    params?: Record<string, unknown>,
  ): void => {
    const record: MainLogRecord = {
      level,
      caller_type: 'frontend',
      caller_name: callerName,
      event,
      message_key: messageKey,
      params: params ?? {},
      correlation_id: newCorrelationId(),
      timestamp: new Date().toISOString(),
    };
    CONSOLE_BY_LEVEL[level](`[${callerName}] ${event}`, params ?? {});
    // 未设置 endpoint → console 兜底，不上报（非阻塞）
    if (!currentEndpoint.baseURL) {
      console.warn('[main-logger] no report endpoint set:', event);
      return;
    }
    const { baseURL, token } = currentEndpoint;
    const headers = new Headers({ 'Content-Type': 'application/json' });
    if (token) headers.set('X-InkFlow-Token', token);
    if (record.correlation_id) headers.set('X-Correlation-Id', record.correlation_id);
    // fire-and-forget：不 await，失败在 .catch 兜底（非阻塞）
    const report = fetch(`${baseURL}/api/v1/logs`, {
      method: 'POST',
      headers,
      body: JSON.stringify(record),
    });
    if (report && typeof report.then === 'function') {
      report
        .then((res) => {
          // HTTP 非 2xx：fetch 仍 resolve，显式判定后走 .catch 兜底（非阻塞）
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
          }
        })
        .catch((err) => {
          console.warn('[main-logger] report failed (non-blocking):', err);
        });
    }
  };
  return {
    debug: (e, m, p) => emit('debug', e, m, p),
    info: (e, m, p) => emit('info', e, m, p),
    warn: (e, m, p) => emit('warn', e, m, p),
    error: (e, m, p) => emit('error', e, m, p),
  };
}
