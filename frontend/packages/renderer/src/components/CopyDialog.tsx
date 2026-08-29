/** 世界观复制对话框（F43 P1，specs/f43-setting-library-gui/spec.md v1.1 §5.5，F37 消费）：
 * 行内复制（subtree：范围 chips「本体+全部子级[默认]/仅本体」）+ 顶部整体复制（all：范围固定，chips 隐藏）。
 * 目标项目 Select 排除当前项目（E20，父级过滤后传入）；确认 disabled 直到目标已选；
 * #195：遮罩点击不关闭；Esc 关闭；失败 → err toast + 保持打开可重试（E24，toast 由父级处理）。 */
import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import { cn } from '../lib/cn';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

export interface CopyTargetOption {
  id: string;
  name: string;
}

export interface CopyDialogProps {
  open: boolean;
  /** 'subtree' = 行内复制（范围可选）；'all' = 顶部整体复制（范围固定，chips 隐藏） */
  mode: 'subtree' | 'all';
  /** 目标项目（已排除当前项目，E20；空数组 → 确认 disabled） */
  targetOptions: Array<CopyTargetOption>;
  /** 确认回调（targetId + selfOnly；成功/失败 toast 与关框由父级负责） */
  onCopy: (targetId: string, selfOnly: boolean) => Promise<void>;
  onOpenChange: (open: boolean) => void;
}

export function CopyDialog({
  open,
  mode,
  targetOptions,
  onCopy,
  onOpenChange,
}: CopyDialogProps) {
  const { t } = useI18n();
  const [selfOnly, setSelfOnly] = useState(false);
  const [targetId, setTargetId] = useState('');
  const [copying, setCopying] = useState(false);

  // 打开时重置表单（每次打开从默认范围 + 空目标开始，避免上次选择残留）
  useEffect(() => {
    if (!open) return;
    setSelfOnly(false);
    setTargetId('');
    setCopying(false);
  }, [open, mode]);

  // Esc 关闭（document 级监听覆盖框内任意焦点；尊重 Radix Select 已 preventDefault 的 Escape）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  const handleConfirm = async () => {
    if (!targetId || copying) return;
    setCopying(true);
    try {
      await onCopy(targetId, selfOnly);
      // 成功后由父级关闭对话框；失败保持打开可重试（E24）
    } catch {
      // toast 由父级 onCopy 处理
    } finally {
      setCopying(false);
    }
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('lib.copy.title')}
        data-testid="world-copy-dialog"
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('lib.copy.title')}</h2>

        <div className="mt-4 space-y-4 text-[13px]">
          {/* 范围 chips（仅行内 subtree 模式；整体 all 模式固定「全部」隐藏，R12 契约） */}
          {mode === 'subtree' && (
            <div className="flex flex-col gap-1.5">
              <span>{t('lib.copy.scope')}</span>
              <div className="flex gap-2">
                <button
                  type="button"
                  data-testid="world-copy-scope-subtree"
                  aria-pressed={!selfOnly}
                  className={cn(
                    'rounded-full border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    !selfOnly
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-line text-ink-2 hover:border-accent hover:text-accent',
                  )}
                  onClick={() => setSelfOnly(false)}
                >
                  {t('lib.copy.scope.subtree')}
                </button>
                <button
                  type="button"
                  data-testid="world-copy-scope-self"
                  aria-pressed={selfOnly}
                  className={cn(
                    'rounded-full border px-3 py-1 text-[12px] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    selfOnly
                      ? 'border-accent bg-accent/10 text-accent'
                      : 'border-line text-ink-2 hover:border-accent hover:text-accent',
                  )}
                  onClick={() => setSelfOnly(true)}
                >
                  {t('lib.copy.scope.self')}
                </button>
              </div>
            </div>
          )}

          <label className="flex flex-col gap-1.5">
            <span>{t('lib.copy.target')}</span>
            <Select
              value={targetId}
              onValueChange={(v) => setTargetId(v)}
            >
              <SelectTrigger data-testid="world-copy-target" aria-label={t('lib.copy.target')}>
                <SelectValue placeholder={t('lib.copy.target')} />
              </SelectTrigger>
              <SelectContent>
                {targetOptions.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="world-copy-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="world-copy-ok"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!targetId || copying}
            onClick={() => void handleConfirm()}
          >
            {t('lib.copy.ok')}
          </button>
        </div>
      </div>
    </div>
  );
}
