/** 项目导出对话框（#654）：范围（设定档案附录）/ 导出位置 / 文件名 → fetch 导出文本 → Electron IPC 写盘 */
import { useEffect, useState } from 'react';
import { errorMessage, getApiConfig } from '../api/client';
import { exportProjectFile } from '../api/export';
import { useI18n } from '../i18n/useI18n';
import type { Project } from '../stores/project';
import { useToastStore } from '../stores/toast';

export interface ExportDialogProps {
  project: Project;
  onClose: () => void;
}

export function ExportDialog({ project, onClose }: ExportDialogProps) {
  const { t } = useI18n();
  const pushToast = useToastStore((s) => s.pushToast);
  // 范围：默认勾选 = 设定档案附录全含
  const [includeSettings, setIncludeSettings] = useState(true);
  // 导出位置：默认 ''（mount 后由 getDefaultLocation 填充；file 未注入时保持空）
  const [location, setLocation] = useState('');
  // 文件名：默认 `${project.name}.txt`（用户可编辑；提交时原样传给 saveExport）
  const [filename, setFilename] = useState(`${project.name}.txt`);
  const [saving, setSaving] = useState(false);

  // mount：读取默认导出位置（file 可能 undefined → 可选链兜底，浏览器 dev/测试不崩）
  useEffect(() => {
    void getApiConfig()
      .file?.getDefaultLocation()
      .then((p) => {
        if (p) setLocation(p);
      })
      .catch(() => {
        /* 读取失败保持空位置，用户可手动输入/浏览 */
      });
  }, []);

  // 浏览：选择目录写入导出位置
  const handleBrowse = () => {
    void getApiConfig()
      .file?.chooseDirectory()
      .then((p) => {
        if (p) setLocation(p);
      })
      .catch(() => {
        /* 取消/失败保持原位置 */
      });
  };

  // 提交：导出文本 → saveExport 写盘（saveExport.filename = 文件名输入框当前值，非 Content-Disposition 文件名）
  const handleSubmit = async () => {
    setSaving(true);
    try {
      const { content } = await exportProjectFile(project.id, {
        includeSettings,
        fallbackBaseName: project.name,
      });
      const saved = await getApiConfig().file?.saveExport({ path: location, filename, content });
      if (!saved) throw new Error(t('export.ok'));
      pushToast('ok', '导出成功');
      onClose();
    } catch (err) {
      pushToast('err', errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('export.title')}
        data-testid="project-export-dialog"
        className="w-[480px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">{t('export.title')}</h2>
        <div className="mt-4 space-y-3 text-[13px]">
          <p>{t('export.body')}</p>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              data-testid="export-include-settings"
              checked={includeSettings}
              onChange={(e) => setIncludeSettings(e.target.checked)}
            />
            <span>{t('export.includeSettings')}</span>
          </label>
          <div className="flex flex-col gap-1.5">
            <span>{t('export.location')}</span>
            <div className="flex gap-2">
              <input
                data-testid="export-location-input"
                aria-label={t('export.location')}
                className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
              />
              <button
                type="button"
                data-testid="export-browse"
                className="shrink-0 rounded-md border border-line px-3 py-2 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
                onClick={handleBrowse}
              >
                {t('export.browse')}
              </button>
            </div>
          </div>
          <label className="flex flex-col gap-1.5">
            <span>{t('export.filename')}</span>
            <input
              data-testid="export-filename-input"
              aria-label={t('export.filename')}
              className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
            />
          </label>
        </div>
        <div className="mt-6 flex items-center justify-between">
          {saving && (
            <span data-testid="export-loading" className="text-[13px] text-ink-3">
              {t('export.loading')}
            </span>
          )}
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              data-testid="export-cancel"
              className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
              onClick={onClose}
            >
              {t('export.cancel')}
            </button>
            <button
              type="button"
              data-testid="export-submit"
              disabled={saving}
              className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => void handleSubmit()}
            >
              {t('export.submit')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
