/**
 * REST API client（spec §4.4）
 * - baseURL/token 注入: window.INKFLOW_API（#78 preload）→ 回退 Vite env（开发连本地 serve）
 * - 统一错误模型: ApiError{status, detail}；401 → 内核未就绪
 */

export interface ApiConfig {
  baseURL: string;
  token: string;
}

declare global {
  interface Window {
    INKFLOW_API?: ApiConfig;
  }
}

export function getApiConfig(): ApiConfig {
  if (window.INKFLOW_API) return window.INKFLOW_API;
  return {
    baseURL: import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000',
    token: import.meta.env.VITE_API_TOKEN ?? '',
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/** 401 专用错误（渲染层提示「内核未就绪」，ADR-021） */
export class KernelOfflineError extends ApiError {
  constructor(detail = 'Unauthorized') {
    super(401, detail);
    this.name = 'KernelOfflineError';
  }
}

interface ApiFetchInit extends Omit<RequestInit, 'body'> {
  body?: unknown;
}

/** fetch 封装：baseURL 拼接 + X-InkFlow-Token 头 + 错误映射（404/422/500 → ApiError） */
export async function apiFetch<T>(path: string, init: ApiFetchInit = {}): Promise<T> {
  const { baseURL, token } = getApiConfig();
  const headers = new Headers(init.headers);
  if (token) headers.set('X-InkFlow-Token', token);
  if (init.body !== undefined && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let res: Response;
  try {
    res = await fetch(`${baseURL}${path}`, {
      ...init,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    // 网络层失败（内核未启动/端口未监听）
    throw new KernelOfflineError('Kernel unreachable');
  }

  if (res.status === 401) throw new KernelOfflineError();
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** 后端错误消息统一提取（组件展示用） */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}
