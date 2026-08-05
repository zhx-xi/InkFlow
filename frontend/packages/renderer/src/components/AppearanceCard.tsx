/** 外观卡片（spec §4.2.3/§4.3）：主题三选 + 背景随主题过滤 + 语言切换，持久化走 theme store */
import { BG_BY_THEME, type Lang, type ThemeBg, type ThemeName } from '../theme';
import { useI18n } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';

const THEMES: Array<{ value: ThemeName; labelKey: string }> = [
  { value: 'paper', labelKey: 'theme.paper' },
  { value: 'night', labelKey: 'theme.night' },
  { value: 'ink', labelKey: 'theme.ink' },
];

export function AppearanceCard() {
  const { t } = useI18n();
  const theme = useThemeStore((s) => s.theme);
  const bg = useThemeStore((s) => s.bg);
  const lang = useThemeStore((s) => s.lang);
  const setTheme = useThemeStore((s) => s.setTheme);
  const setBg = useThemeStore((s) => s.setBg);
  const setLang = useThemeStore((s) => s.setLang);

  return (
    <section data-testid="agent-appearance-card" className="rounded-lg border border-line bg-surface p-6">
      <h2 className="font-serif text-[17px] font-semibold">{t('ap.title')}</h2>
      <div className="mt-4 space-y-4">
        <div>
          <div className="mb-1.5 text-[12px] text-ink-2">{t('ap.theme')}</div>
          <div className="flex gap-4">
            {THEMES.map((th) => (
              <label key={th.value} className="flex cursor-pointer items-center gap-1.5 text-[13px]">
                <input
                  type="radio"
                  name="appearance-theme"
                  value={th.value}
                  checked={theme === th.value}
                  onChange={() => setTheme(th.value)}
                />
                {t(th.labelKey)}
              </label>
            ))}
          </div>
        </div>
        <label className="block text-[12px] text-ink-2">
          <span className="mb-1 block">{t('ap.bg')}</span>
          <select
            aria-label={t('ap.bg')}
            className="w-56 rounded-md border border-line bg-surface px-3 py-2 text-[13px] outline-none"
            value={bg}
            onChange={(e) => setBg(e.target.value as ThemeBg)}
          >
            {BG_BY_THEME[theme].map((b) => (
              <option key={b} value={b}>
                {t(`bg.${b}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[12px] text-ink-2">
          <span className="mb-1 block">{t('ap.lang')}</span>
          <select
            aria-label={t('ap.lang')}
            className="w-56 rounded-md border border-line bg-surface px-3 py-2 text-[13px] outline-none"
            value={lang}
            onChange={(e) => setLang(e.target.value as Lang)}
          >
            <option value="zh">{t('lang.zh')}</option>
            <option value="en">{t('lang.en')}</option>
          </select>
        </label>
      </div>
    </section>
  );
}
