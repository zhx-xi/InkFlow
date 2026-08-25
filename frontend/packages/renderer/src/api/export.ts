/**
 * 项目导出 API（#654）：GET /api/v1/projects/{id}/export?format=txt[&include_settings=true]
 * 响应为 text/plain（非 JSON）——用全局 fetch 直读 res.text()（不走 apiFetch 的 res.json() 路径）
 */
import { ApiError, getApiConfig, KernelOfflineError } from './client';

export interface ExportFileOptions {
  includeSettings: boolean;
  fallbackBaseName: string;
}

export interface ExportFileResult {
  filename: string;
  content: string;
}

/** 解析 Content-Disposition 文件名：优先 RFC 5987 filename*（UTF-8 百分号解码），兼容 filename="..." */
function parseFilename(contentDisposition: string | null): string | null {
  if (!contentDisposition) return null;
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(contentDisposition);
  if (star) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch {
      return null;
    }
  }
  const plain = /filename="([^"]+)"/i.exec(contentDisposition);
  if (plain) {
    try {
      return decodeURIComponent(plain[1]);
    } catch {
      return null;
    }
  }
  return null;
}

/** 导出项目为 txt：fetch 取文本 → filename 来自 Content-Disposition（缺失回退 `${fallbackBaseName}-txt.txt`） */
export async function exportProjectFile(
  projectId: string,
  opts: ExportFileOptions,
): Promise<ExportFileResult> {
  const { baseURL, token } = getApiConfig();
  const url = `${baseURL}/api/v1/projects/${projectId}/export?format=txt${opts.includeSettings ? '&include_settings=true' : ''}`;
  const headers = new Headers();
  if (token) headers.set('X-InkFlow-Token', token);
  const res = await fetch(url, { headers });

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
  const content = await res.text();
  const filename =
    parseFilename(res.headers.get('Content-Disposition')) ?? `${opts.fallbackBaseName}-txt.txt`;
  return { filename, content };
}
