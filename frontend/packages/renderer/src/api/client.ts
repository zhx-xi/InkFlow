/**
 * REST API client（spec §4.4）
 * - baseURL/token 注入: window.INKFLOW_API（#78 preload）→ 回退 Vite env（开发连本地 serve）
 * - 统一错误模型: ApiError{status, detail}；401 → 内核未就绪
 */

/** #106 用户拍板：自绘窗口控制按钮（preload 暴露的 IPC 通道） */
export interface WindowControls {
  minimize: () => void;
  toggleMaximize: () => void;
  close: () => void;
  /** #106：最大化状态订阅（图标切换）。返回取消函数；回调在窗口最大化状态变化时触发 */
  onMaximizedChange?: (callback: (maximized: boolean) => void) => () => void;
}

/** #167 F31 托盘常驻：关闭窗口行为（'tray' 最小化到系统托盘 | 'quit' 直接退出）；F32 起由后端持久化 */
export type CloseBehavior = 'tray' | 'quit';

/** F32 设置持久化（#152）：全量设置对象，字段 snake_case 对齐后端 JSON（spec §2.1/§3.2） */
export interface AppSettings {
  theme: 'paper' | 'night' | 'ink';
  bg: 'default' | 'parchment' | 'navy' | 'ochre';
  lang: 'zh' | 'en';
  font: 'serif' | 'sans' | 'mono';
  close_behavior: CloseBehavior;
  tray_hint_dismissed: boolean;
  /** #189：全局默认目标字数（无项目时保存 / 新建项目初始化用；默认 800000 后端补齐） */
  default_words: number;
  /** #479：知识图谱定时提取开关（spec §5.5.2，默认 false） */
  kg_extract_enabled: boolean;
  /** #479：知识图谱定时提取频率（小时；默认 24，spec §5.5.2） */
  kg_extract_interval_hours: number;
  /** #479：知识图谱提取方式（rule=仅规则 / ai=仅 AI / both=规则+AI，spec §5.5.2） */
  kg_extract_method: 'rule' | 'ai' | 'both';
}

/** F32（#152）：PATCH /settings 请求体——部分更新，只发用户改动字段（响应恒为合并后全量） */
export type AppSettingsUpdate = Partial<AppSettings>;

/** #167 F31：preload settings 命名空间（B1/B2 已暴露 IPC 通道；F32 类型补全 dismissTrayHint） */
export interface SettingsApi {
  getCloseBehavior: () => Promise<CloseBehavior>;
  setCloseBehavior: (value: CloseBehavior) => Promise<void>;
  /** #167 F31 首次托盘提示「不再提示」（preload 运行时已有该通道，F32 补全类型） */
  dismissTrayHint: () => Promise<void>;
}

export interface ApiConfig {
  baseURL: string;
  token: string;
  /** 浏览器环境/未注入时 undefined，组件侧可选链安全调用 */
  windowControls?: WindowControls;
  /** #167 F31：关闭窗口行为设置（renderer 只经 IPC 读写，不持久化） */
  settings?: SettingsApi;
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

/**
 * Electron 环境探测（#98 修复）：navigator.userAgent 含 'Electron'（大小写不敏感）。
 * 渲染层据此区分 Electron（需等待 preload 注入）与浏览器 dev（无注入源，不等待）。
 */
export function isElectronEnv(): boolean {
  return typeof navigator !== 'undefined' && /electron/i.test(navigator.userAgent);
}

/**
 * 等待 API 注入就绪（#98 修复：Electron 生产 401 时序竞态）：
 * - window.INKFLOW_API 已就绪 → 立即 resolve；
 * - 非 Electron 环境 → 立即 resolve（浏览器 dev 无注入源，错误态由页面处理）；
 * - Electron + 未就绪 → 监听 'inkflow:api-ready'（preload expose 后 dispatch）→ resolve，
 *   timeoutMs 兜底 resolve（不挂起；事件在超时后到达不抛错）。
 * 幂等：就绪判断在入口，已就绪后再次调用立即 resolve；多次调用各自监听互不干扰。
 */
export function ensureApiReady(timeoutMs = 15000): Promise<void> {
  if (window.INKFLOW_API) return Promise.resolve();
  if (!isElectronEnv()) return Promise.resolve();

  return new Promise<void>((resolve) => {
    const onReady = (): void => {
      window.removeEventListener('inkflow:api-ready', onReady);
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(() => {
      window.removeEventListener('inkflow:api-ready', onReady);
      resolve();
    }, timeoutMs);
    window.addEventListener('inkflow:api-ready', onReady, { once: true });
  });
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
  // #522 P2 测试 mock 契约：SkillList RED 测试把 body 收窄为 { content?: string }，
  // 既有测试又传 body?: unknown，两者互斥，仅 any 可同时满足逆变检查
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- 上述原因
  body?: any;
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
      body:
        init.body === undefined
          ? undefined
          : init.body instanceof FormData
            ? init.body
            : JSON.stringify(init.body),
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
  // 204 No Content（DELETE 等）无响应体：跳过 JSON 解析（res.json() 对空 body 抛 SyntaxError）
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

/** 后端错误消息统一提取（组件展示用） */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail;
  if (err instanceof Error) return err.message;
  return String(err);
}

/** F32（#152）：GET /api/v1/settings——全量设置（缺失键后端默认值补齐，spec §3.2） */
export async function fetchSettings(): Promise<AppSettings> {
  return apiFetch<AppSettings>('/api/v1/settings');
}

/** F32（#152）：PATCH /api/v1/settings——部分更新；响应 = 合并后全量对象（免二次 GET，spec §3.3） */
export async function patchSettings(patch: AppSettingsUpdate): Promise<AppSettings> {
  return apiFetch<AppSettings>('/api/v1/settings', { method: 'PATCH', body: patch });
}

/** #266：数据目录信息（GET /api/v1/settings/data-dir 响应；restart_required 仅写响应含） */
export interface DataDirInfo {
  data_dir: string;
  instance_env_path: string;
  restart_required?: boolean;
}

/** #266：GET /api/v1/settings/data-dir——当前生效数据目录 + instance.env 锚点 */
export async function fetchDataDir(): Promise<DataDirInfo> {
  return apiFetch<DataDirInfo>('/api/v1/settings/data-dir');
}

/** #266：PUT /api/v1/settings/data-dir——持久化数据目录到 instance.env（重启后生效） */
export async function updateDataDir(body: { data_dir: string }): Promise<DataDirInfo> {
  return apiFetch<DataDirInfo>('/api/v1/settings/data-dir', { method: 'PUT', body });
}

/** F50（#563）：MCP 自发现信息（GET /api/v1/mcp/info 响应，spec f50 §3.2） */
export interface McpInfo {
  client_path: string;
  version: string;
  config_template: {
    claude: { mcpServers: { inkflow: { command: string } } };
    cursor: { mcpServers: { inkflow: { command: string } } };
    hermes: { mcpServers: { inkflow: { command: string } } };
  };
}

/** F50（#563）：GET /api/v1/mcp/info——MCP 客户端路径 + 版本 + 三宿主配置模板 */
export async function fetchMcpInfo(): Promise<McpInfo> {
  return apiFetch<McpInfo>('/api/v1/mcp/info');
}
