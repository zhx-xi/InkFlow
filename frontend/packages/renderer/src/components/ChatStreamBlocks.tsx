/**
 * #964：ChatPanel 折叠块展示层抽取（#727 思考过程 + 工具调用/结果）。
 * 纯展示组件：无 state / 无 effect；testid / aria-expanded / 点击行为与拆分前完全一致。
 */
import { useI18n } from '../i18n/useI18n';

export interface ChatStreamBlocksProps {
  reasoningEntries: { seq: number; text: string }[];
  toolEntries: { id: string; name: string; args: Record<string, unknown>; result: string | null }[];
  expandedBlocks: Record<string, boolean>;
  onToggle: (key: string) => void;
}

export function ChatStreamBlocks({
  reasoningEntries,
  toolEntries,
  expandedBlocks,
  onToggle,
}: ChatStreamBlocksProps) {
  const { t } = useI18n();

  return (
    <>
      {/* #727：思考过程折叠块 */}
      {reasoningEntries.map((entry, index) => {
        const blockKey = `reasoning-${index}`;
        const open = !!expandedBlocks[blockKey];
        return (
          <div
            key={blockKey}
            data-testid={`chat-reasoning-${index}`}
            aria-expanded={open}
            className="rounded-md border border-line bg-surface px-3 py-2 text-[12px]"
            onClick={() => onToggle(blockKey)}
          >
            <button
              type="button"
              data-testid={`chat-reasoning-toggle-${index}`}
              aria-expanded={open}
              className="flex w-full items-center gap-1.5 text-left"
              onClick={(e) => {
                e.stopPropagation();
                onToggle(blockKey);
              }}
            >
              <span className="inline-block w-3 shrink-0 text-ink-3">{open ? '▾' : '›'}</span>
              <span className="text-ink">🧠</span>
              <span className="font-medium text-ink">{t('write.chat.thinking')}</span>
              <span className="ml-auto text-[11px] text-ink-3">{t('write.chat.thinking')}</span>
            </button>
            {open && (
              <div className="mt-1 whitespace-pre-wrap border-t border-line pt-1 text-ink-2">
                {entry.text}
              </div>
            )}
          </div>
        );
      })}
      {/* #727：工具调用/结果折叠块（#597 旧 testid 兼容） */}
      {toolEntries.map((entry, index) => (
        <div
          key={`tool-${entry.id}-${index}`}
          data-testid={`chat-tool-${index}`}
          aria-expanded={!!expandedBlocks[`tool-${index}`]}
          className="rounded-md border border-line bg-surface px-3 py-2 text-[12px]"
          onClick={() => onToggle(`tool-${index}`)}
        >
          <button
            type="button"
            data-testid={`chat-tool-toggle-${index}`}
            aria-expanded={!!expandedBlocks[`tool-${index}`]}
            className="flex w-full items-center gap-1.5 text-left"
            onClick={(e) => {
              e.stopPropagation();
              onToggle(`tool-${index}`);
            }}
          >
            <span className="inline-block w-3 shrink-0 text-ink-3">
              {expandedBlocks[`tool-${index}`] ? '▾' : '›'}
            </span>
            <span className="text-ink">🔧</span>
            <span className="font-medium text-ink" data-testid={`chat-tool-call-${index}`} data-name={entry.name}>
              {entry.name}
            </span>
            <span className="ml-auto text-[11px] text-ink-3">{t('write.chat.toolCall')}</span>
          </button>
          {expandedBlocks[`tool-${index}`] && (
            <div className="mt-1 space-y-1 border-t border-line pt-1">
              <div className="text-ink-2">参数: {JSON.stringify(entry.args)}</div>
            </div>
          )}
          {/* #597 兼容：result testid 常驻 DOM */}
          {entry.result !== null && (
            <div data-testid={`chat-tool-result-${index}`} className="text-ink-2">
              {expandedBlocks[`tool-${index}`] && (
                <>
                  <span className={entry.result.includes('"ok": false') ? 'text-err' : 'text-ink'}>
                    {entry.result.includes('"ok": false') ? '❌ ' : '✅ '}
                  </span>
                  <span className="whitespace-pre-wrap">{entry.result}</span>
                </>
              )}
            </div>
          )}
        </div>
      ))}
    </>
  );
}
