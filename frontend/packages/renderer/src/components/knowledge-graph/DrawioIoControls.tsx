/** #1360：知识图谱工具栏的 drawio 导入/导出动作（spec §5.7 / ADR-061）。
 *
 * - 导出：GET mxGraph XML → 经 Electron file IPC 写盘（默认目录 + 服务端文件名）→ 状态行
 * - 导入：弹层选文件 + 选 merge|replace（replace 需二次确认）→ 回报 imported/skipped/failed
 *   → 成功后 onImported()（父侧 bump reloadKey 触发图谱重拉）
 */
import { useState, type ChangeEvent } from 'react';
import { Download, Upload } from 'lucide-react';

import { errorMessage, getApiConfig } from '../../api/client';
import {
  exportKnowledgeGraphFile,
  importKnowledgeGraphFile,
  type KnowledgeGraphImportMode,
  type KnowledgeGraphImportResult,
} from '../../api/knowledge-graph';
import { useI18n } from '../../i18n/useI18n';

export interface DrawioIoControlsProps {
  /** 当前项目 id（缺省 → 两个按钮禁用） */
  projectId?: string;
  /** 导入成功后回调（父侧 bump reloadKey 触发图谱重拉） */
  onImported?: () => void;
}

const BTN_CLS =
  'inline-flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 transition duration-150 hover:border-accent hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50';

/** 读取选取文件为文本（浏览器走 Blob.text()；jsdom 无该 API 时回退 FileReader） */
function readFileText(file: File): Promise<string> {
  if (typeof file.text === 'function') return file.text();
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
    reader.onerror = () => reject(reader.error ?? new Error('文件读取失败'));
    reader.readAsText(file);
  });
}

export function DrawioIoControls({ projectId, onImported }: DrawioIoControlsProps) {
  const { t } = useI18n();
  const [exportStatus, setExportStatus] = useState('');
  const [exportError, setExportError] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [xml, setXml] = useState('');
  const [mode, setMode] = useState<KnowledgeGraphImportMode>('merge');
  const [replaceAck, setReplaceAck] = useState(false);
  const [pending, setPending] = useState(false);
  const [importError, setImportError] = useState('');
  const [result, setResult] = useState<KnowledgeGraphImportResult | null>(null);

  const handleExport = async (): Promise<void> => {
    if (!projectId) return;
    setExportStatus('');
    setExportError('');
    try {
      const { filename, content } = await exportKnowledgeGraphFile(projectId);
      const file = getApiConfig().file;
      if (!file) throw new Error(t('lib.knowledge.drawio.saveUnavailable'));
      const location = await file.getDefaultLocation();
      const saved = await file.saveExport({ path: location ?? '', filename, content });
      if (!saved) throw new Error(t('lib.knowledge.drawio.saveUnavailable'));
      setExportStatus(t('lib.knowledge.drawio.exported', { filename }));
    } catch (err) {
      setExportError(errorMessage(err));
    }
  };

  const openDialog = (): void => {
    setXml('');
    setMode('merge');
    setReplaceAck(false);
    setPending(false);
    setImportError('');
    setResult(null);
    setDialogOpen(true);
  };

  const closeDialog = (): void => {
    setDialogOpen(false);
    setXml('');
    setMode('merge');
    setReplaceAck(false);
    setPending(false);
    setImportError('');
    setResult(null);
  };

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    if (!file) return;
    setXml(await readFileText(file));
  };

  const submitDisabled = pending || xml === '' || (mode === 'replace' && !replaceAck);

  const handleSubmit = async (): Promise<void> => {
    if (!projectId || submitDisabled) return;
    setImportError('');
    setResult(null);
    setPending(true);
    try {
      const res = await importKnowledgeGraphFile(projectId, xml, mode);
      setResult(res);
      onImported?.();
    } catch (err) {
      setImportError(errorMessage(err));
    } finally {
      setPending(false);
    }
  };

  return (
    <>
      <button
        type="button"
        data-testid="library-kg-export-drawio"
        className={BTN_CLS}
        onClick={handleExport}
        disabled={!projectId}
      >
        <Download className="h-3.5 w-3.5" aria-hidden="true" />
        {t('lib.knowledge.drawio.export')}
      </button>
      <button
        type="button"
        data-testid="library-kg-import-drawio"
        className={BTN_CLS}
        onClick={openDialog}
        disabled={!projectId}
      >
        <Upload className="h-3.5 w-3.5" aria-hidden="true" />
        {t('lib.knowledge.drawio.import')}
      </button>
      {exportStatus !== '' && (
        <span data-testid="library-kg-drawio-status" className="text-[12px] text-ink-2">
          {exportStatus}
        </span>
      )}
      {exportError !== '' && (
        <span data-testid="library-kg-drawio-error" className="text-[12px] text-err">
          {exportError}
        </span>
      )}
      {dialogOpen && (
        <div
          role="presentation"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
          onClick={closeDialog}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={t('lib.knowledge.drawio.importTitle')}
            data-testid="library-kg-import-dialog"
            className="w-[460px] rounded-lg border border-line bg-surface p-4 shadow-card"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="font-serif text-[16px] font-semibold">
              {t('lib.knowledge.drawio.importTitle')}
            </h2>
            <label className="mt-3 block">
              <span className="text-[12px] text-ink-2">{t('lib.knowledge.drawio.file')}</span>
              <input
                type="file"
                accept=".drawio,.xml,application/xml"
                data-testid="library-kg-import-file"
                className="mt-1 block w-full text-[12px] text-ink-2"
                onChange={(e) => {
                  void handleFileChange(e);
                }}
              />
            </label>
            <div className="mt-3 flex items-center gap-4">
              <label className="flex items-center gap-1.5 text-[12px] text-ink-2">
                <input
                  type="radio"
                  name="kg-drawio-import-mode"
                  data-testid="library-kg-import-mode-merge"
                  value="merge"
                  checked={mode === 'merge'}
                  onChange={() => setMode('merge')}
                />
                {t('lib.knowledge.drawio.modeMerge')}
              </label>
              <label className="flex items-center gap-1.5 text-[12px] text-ink-2">
                <input
                  type="radio"
                  name="kg-drawio-import-mode"
                  data-testid="library-kg-import-mode-replace"
                  value="replace"
                  checked={mode === 'replace'}
                  onChange={() => setMode('replace')}
                />
                {t('lib.knowledge.drawio.modeReplace')}
              </label>
            </div>
            {mode === 'replace' && (
              <label className="mt-3 flex items-start gap-1.5 text-[12px] text-err">
                <input
                  type="checkbox"
                  data-testid="library-kg-import-replace-ack"
                  checked={replaceAck}
                  onChange={(e) => setReplaceAck(e.target.checked)}
                  className="mt-0.5"
                />
                {t('lib.knowledge.drawio.replaceAck')}
              </label>
            )}
            {importError !== '' && (
              <p data-testid="library-kg-import-error" className="mt-3 text-[12px] text-err">
                {importError}
              </p>
            )}
            {result !== null && (
              <p data-testid="library-kg-import-result" className="mt-3 text-[12px] text-ink-2">
                {t('lib.knowledge.drawio.result', {
                  imported: result.imported,
                  skipped: result.skipped,
                  failed: result.failed,
                })}
              </p>
            )}
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                data-testid="library-kg-import-cancel"
                className="rounded-md border border-line px-3 py-1.5 text-[12px] text-ink-2 transition duration-150 hover:bg-surface-3"
                onClick={closeDialog}
              >
                {t('lib.knowledge.drawio.cancel')}
              </button>
              <button
                type="button"
                data-testid="library-kg-import-submit"
                className="rounded-md bg-accent px-3 py-1.5 text-[12px] text-accent-ink transition duration-150 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => {
                  void handleSubmit();
                }}
                disabled={submitDisabled}
              >
                {pending ? t('lib.knowledge.drawio.loading') : t('lib.knowledge.drawio.submit')}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
