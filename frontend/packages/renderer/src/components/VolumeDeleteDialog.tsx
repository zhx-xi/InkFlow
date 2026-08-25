/**
 * 删除卷对话框（Issue #648 卷管理 GUI CRUD）：
 * 卷下有章节（chapterCount>0）→ 必须选择处理方式：级联删章 / 移动到其他卷；
 * 空卷（chapterCount=0）→ 直接删除。
 * 关闭路径 = 取消按钮 / 遮罩点击 → onOpenChange(false)。
 */
import { useEffect, useState } from 'react';
import { useI18n } from '../i18n/useI18n';
import type { Volume } from '../stores/chapter';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

export interface VolumeDeleteDialogProps {
  open: boolean;
  volume: Volume;
  otherVolumes: Volume[];
  chapterCount: number;
  onConfirm: (options: { delete_chapters?: boolean; move_to?: string }) => void;
  onOpenChange: (open: boolean) => void;
}

type VolumeDeleteMode = 'cascade' | 'move';

export function VolumeDeleteDialog({
  open,
  volume,
  otherVolumes,
  chapterCount,
  onConfirm,
  onOpenChange,
}: VolumeDeleteDialogProps) {
  const { t } = useI18n();
  const [mode, setMode] = useState<VolumeDeleteMode | null>(null);
  const [targetVolumeId, setTargetVolumeId] = useState('');

  // 打开时重置选择，避免复用上一次的状态
  useEffect(() => {
    if (open) {
      setMode(null);
      setTargetVolumeId('');
    }
  }, [open]);

  if (!open) return null;

  const hasChapters = chapterCount > 0;
  const canConfirm =
    !hasChapters || mode === 'cascade' || (mode === 'move' && targetVolumeId !== '');

  const handleConfirm = () => {
    if (!hasChapters) {
      onConfirm({});
      return;
    }
    if (mode === 'cascade') {
      onConfirm({ delete_chapters: true });
      return;
    }
    if (mode === 'move' && targetVolumeId) {
      onConfirm({ move_to: targetVolumeId });
    }
  };

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={() => onOpenChange(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="删除卷"
        data-testid="vol-del-dialog"
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">
          删除卷：<span>{volume.title}</span>
        </h2>
        {hasChapters ? (
          <>
            <div className="mt-3 text-[13px] text-ink-2">
              该卷包含 {chapterCount} 个章节，请选择处理方式：
            </div>
            <div className="mt-4 space-y-2" role="radiogroup" aria-label="删除方式">
              <label data-testid="vol-del-cascade" className="flex items-center gap-2 text-[13px]">
                <input
                  type="radio"
                  name="vol-mode"
                  checked={mode === 'cascade'}
                  onChange={() => setMode('cascade')}
                />
                级联删章
              </label>
              <label data-testid="vol-del-move" className="flex items-center gap-2 text-[13px]">
                <input
                  type="radio"
                  name="vol-mode"
                  checked={mode === 'move'}
                  onChange={() => setMode('move')}
                />
                移动到其他卷
              </label>
            </div>
            <div className="mt-4">
              <Select
                value={targetVolumeId}
                onValueChange={setTargetVolumeId}
                disabled={mode !== 'move'}
              >
                <SelectTrigger data-testid="vol-del-target" disabled={mode !== 'move'}>
                  <SelectValue placeholder="选择目标卷" />
                </SelectTrigger>
                <SelectContent>
                  {otherVolumes.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </>
        ) : (
          <div className="mt-3 text-[13px] text-ink-2">该卷为空，删除后不可恢复。</div>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="vol-del-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('dlg.cancel')}
          </button>
          <button
            type="button"
            data-testid="vol-del-ok"
            className="rounded-md border border-err/40 px-4 py-1.5 text-sm text-err transition duration-180 hover:bg-err/10 active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canConfirm}
            onClick={handleConfirm}
          >
            删除
          </button>
        </div>
      </div>
    </div>
  );
}
