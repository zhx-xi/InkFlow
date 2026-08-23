/**
 * F50 #563：设置页「MCP 接入」面板（specs/f50-mcp-guidance/spec.md §5.2，方案 A）。
 *
 * - 挂载拉取 GET /api/v1/mcp/info（ensureApiReady 后），显示当前客户端 exe 路径（动态）
 * - 一键复制：客户端路径 + Claude Desktop / Cursor / Hermes 三宿主配置 JSON
 *   （navigator.clipboard.writeText；成功/失败 → toast）
 * - 端点失败 → 面板降级「暂不可用」，不抛错阻断设置页
 * - 明确不写外部宿主配置文件（方案 B 下版评估）
 *
 * 注：面板在数据到位后才渲染（同 RagStatusCard 模式），findByTestId 等待数据避免竞态。
 */
import { useEffect, useState } from 'react';
import { ensureApiReady, fetchMcpInfo, type McpInfo } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';

export function McpSettingsCard() {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  const [info, setInfo] = useState<McpInfo | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await ensureApiReady();
      try {
        const data = await fetchMcpInfo();
        if (!cancelled) setInfo(data);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /** 一键复制：成功 → ok toast；失败（clipboard 权限等）→ err toast */
  const copyText = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      pushToast('ok', t('set.mcp.copied'));
    } catch {
      pushToast('err', t('set.mcp.copyFailed'));
    }
  };

  if (failed) {
    return (
      <section
        data-testid="mcp-settings-panel"
        className="space-y-5 rounded-lg border border-line bg-surface p-6 shadow-card"
      >
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] text-ink-2">{t('set.mcp.title')}</span>
          <span data-testid="mcp-unavailable" className="text-[12px] text-ink-3">
            {t('set.mcp.unavailable')}
          </span>
        </div>
      </section>
    );
  }
  if (!info) return null;

  return (
    <section
      data-testid="mcp-settings-panel"
      className="space-y-5 rounded-lg border border-line bg-surface p-6 shadow-card"
    >
      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] text-ink-2">{t('set.mcp.title')}</span>
        <div className="flex items-center gap-2">
          <span
            data-testid="mcp-client-path"
            className="min-w-0 flex-1 truncate rounded-md border border-line bg-surface-2 px-3 py-2 font-mono text-[12px] text-ink"
          >
            {info.client_path}
          </span>
          <button
            type="button"
            data-testid="mcp-copy-path"
            onClick={() => void copyText(info.client_path)}
            className="shrink-0 rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('set.mcp.copyPath')}
          </button>
        </div>
        <div className="mt-1 flex flex-wrap gap-2">
          <button
            type="button"
            data-testid="mcp-copy-claude"
            onClick={() => void copyText(JSON.stringify(info.config_template.claude, null, 2))}
            className="rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('set.mcp.copyClaude')}
          </button>
          <button
            type="button"
            data-testid="mcp-copy-cursor"
            onClick={() => void copyText(JSON.stringify(info.config_template.cursor, null, 2))}
            className="rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('set.mcp.copyCursor')}
          </button>
          <button
            type="button"
            data-testid="mcp-copy-hermes"
            onClick={() => void copyText(JSON.stringify(info.config_template.hermes, null, 2))}
            className="rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('set.mcp.copyHermes')}
          </button>
        </div>
      </div>
    </section>
  );
}
