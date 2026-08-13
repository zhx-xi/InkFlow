/** 账户分类：数据目录 + 数据管理（占位）+ 关于（版本/logo）
 *
 * 拆分自 settings.tsx（#281 测试文件规模治理——settings.tsx 999 行超护栏）。
 */
import { useEffect, useState } from 'react';
import inkflowIcon from '../assets/inkflow-icon-plain.svg?url&no-inline';
import inkflowIconDark from '../assets/inkflow-icon-plain-dark.svg?url&no-inline';
import inkflowIconInk from '../assets/inkflow-icon-plain-ink.svg?url&no-inline';
import { apiFetch, ensureApiReady, fetchDataDir, updateDataDir } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';
import { useToastStore } from '../stores/toast';
import type { ThemeName } from '../theme';

const LOGO_BY_THEME: Record<ThemeName, string> = {
  paper: inkflowIcon,
  night: inkflowIconDark,
  ink: inkflowIconInk,
};

export function AccountPanel() {
  const { t } = useI18n();
  const theme = useThemeStore((s) => s.theme);
  const pushToast = useToastStore((s) => s.pushToast);
  const [version, setVersion] = useState<string | null>(null);
  const [dataDir, setDataDir] = useState('');
  const [saving, setSaving] = useState(false);
  const [restartHint, setRestartHint] = useState(false);

  // #266：挂载读取当前生效数据目录（失败静默保持空，不阻断面板）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await ensureApiReady();
      try {
        const data = await fetchDataDir();
        if (!cancelled && data.data_dir) setDataDir(data.data_dir);
      } catch {
        if (!cancelled) setDataDir('');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 版本号不硬编码：读内核 /health 的 version 字段（内核为唯一版本源）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await ensureApiReady();
      try {
        const data = await apiFetch<{ version?: string }>('/health');
        if (!cancelled && typeof data.version === 'string' && data.version) setVersion(data.version);
      } catch {
        if (!cancelled) setVersion(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // #266：保存数据目录 → 持久化到 instance.env（重启后生效），成功显示重启提示
  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await updateDataDir({ data_dir: dataDir.trim() });
      setRestartHint(true);
      pushToast('ok', t('toast.saved'));
    } catch {
      pushToast('err', t('toast.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="space-y-5 rounded-lg border border-line bg-surface p-6 shadow-card">
      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] text-ink-2">{t('set.account.dataDir')}</span>
        <div className="flex items-center gap-2">
          <input
            data-testid="settings-data-dir-input"
            aria-label={t('set.account.dataDir')}
            value={dataDir}
            onChange={(e) => setDataDir(e.target.value)}
            className="w-56 rounded-md border border-line bg-surface px-3 py-2 text-[13px] text-ink outline-none focus:border-accent"
          />
          <button
            type="button"
            data-testid="settings-data-dir-save"
            disabled={saving}
            onClick={() => void handleSave()}
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {t('set.account.dataDirSave')}
          </button>
        </div>
        {restartHint && (
          <span data-testid="settings-data-dir-hint" className="text-[11px] text-ink-3">
            {t('set.account.dataDirRestart')}
          </span>
        )}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-ink-2">{t('set.account.dataMgr')}</span>
        <span className="text-[12px] text-ink-3">{t('set.account.dataMgrPlaceholder')}</span>
      </div>
      <div className="flex items-center gap-3">
        <img src={LOGO_BY_THEME[theme]} alt="" aria-hidden="true" className="h-8 w-8" />
        <div>
          <div className="text-[13px] font-medium text-ink">{t('set.account.about')}</div>
          <div className="text-[12px] text-ink-3">
            {t('app.brand')}
            {version ? ` ${t('set.account.version')} v${version}` : ''}
          </div>
        </div>
      </div>
    </section>
  );
}
