import { getCorrelationId, reportLog, type FrontendLogRecord } from './api/client';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

/** F57 #888-S3 4 级前端 logger（浏览器/Electron 渲染层，caller_type=frontend） */
export interface Logger {
  debug(event: string, messageKey: string, params?: Record<string, unknown>): void;
  info(event: string, messageKey: string, params?: Record<string, unknown>): void;
  warn(event: string, messageKey: string, params?: Record<string, unknown>): void;
  error(event: string, messageKey: string, params?: Record<string, unknown>): void;
}

const CONSOLE_BY_LEVEL: Record<LogLevel, (...args: unknown[]) => void> = {
  debug: (...a) => console.debug(...a),
  info: (...a) => console.info(...a),
  warn: (...a) => console.warn(...a),
  error: (...a) => console.error(...a),
};

/** 生成 uuid（页面/操作级 correlation_id；node/browser 均有 crypto） */
export function newCorrelationId(): string {
  return crypto.randomUUID();
}

/** 创建绑定 caller_name 的 4 级 logger：每级 console 输出 + 上报后端（非阻塞 fire-and-forget） */
export function createLogger(callerName: string): Logger {
  const emit = (
    level: LogLevel,
    event: string,
    messageKey: string,
    params?: Record<string, unknown>,
  ): void => {
    const record: FrontendLogRecord = {
      level,
      caller_type: 'frontend',
      caller_name: callerName,
      event,
      message_key: messageKey,
      params: params ?? {},
      correlation_id: getCorrelationId(),
      timestamp: new Date().toISOString(),
    };
    CONSOLE_BY_LEVEL[level](`[${callerName}] ${event}`, params ?? {});
    void reportLog(record); // 非阻塞：不 await，失败在 reportLog 内部兜底
  };
  return {
    debug: (e, m, p) => emit('debug', e, m, p),
    info: (e, m, p) => emit('info', e, m, p),
    warn: (e, m, p) => emit('warn', e, m, p),
    error: (e, m, p) => emit('error', e, m, p),
  };
}
