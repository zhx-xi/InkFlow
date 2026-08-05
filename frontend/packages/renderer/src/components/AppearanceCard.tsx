/** 外观卡片（spec §4.2.3/§4.3）：主题三选 + 背景随主题过滤 + 语言切换，持久化走 theme store */
import { useId } from 'react';
import { BG_BY_THEME, type Lang, type ThemeBg, type ThemeName } from '../theme';
import { useI18n } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';
import { RadioGroup, RadioGroupItem } from './ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

const THEMES: Array<{ value: ThemeName; labelKey: string }> = [
  { value: 'paper', labelKey: 'theme.paper' },
  { value: 'night', labelKey: 'theme.night' },
  { value: 'ink', labelKey: 'theme.ink' },
];

export function AppearanceCard() {
  const { t } = useI18n();
  const radioGroupId = useId();
  const theme = useThemeStore((s) => s.theme);
  const bg = useThemeStore((s) => s.bg);
  const lang = useThemeStore((s) => s.lang);
  const setTheme = useThemeStore((s) => s.setTheme);
  const setBg = useThemeStore((s) => s.setBg);
  const setLang = useThemeStore((s) => s.setLang);

  return (
    <section data-testid="agent-appearance-card" className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('ap.title')}</h2>
      <div className="mt-4 space-y-4">
        <div className="flex flex-col gap-1.5">
          <div className="text-[12px] text-ink-2">{t('ap.theme')}</div>
          <RadioGroup
            value={theme}
            onValueChange={(v) => setTheme(v as ThemeName)}
            aria-label={t('ap.theme')}
            className="flex gap-4"
          >
            {THEMES.map((th) => (
              <div key={th.value} className="flex items-center gap-1.5 text-[13px]">
                <RadioGroupItem value={th.value} id={`${radioGroupId}-${th.value}`} />
                <label htmlFor={`${radioGroupId}-${th.value}`} className="cursor-pointer">
                  {t(th.labelKey)}
                </label>
              </div>
            ))}
          </RadioGroup>
        </div>
        <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('ap.bg')}</span>
          <Select
            value={bg}
            onValueChange={(v) => setBg(v as ThemeBg)}
          >
            <SelectTrigger
              aria-label={t('ap.bg')}
              className="w-56"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {BG_BY_THEME[theme].map((b) => (
                <SelectItem key={b} value={b}>
                  {t(`bg.${b}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5 text-[12px] text-ink-2">
          <span>{t('ap.lang')}</span>
          <Select
            value={lang}
            onValueChange={(v) => setLang(v as Lang)}
          >
            <SelectTrigger
              aria-label={t('ap.lang')}
              className="w-56"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="zh">{t('lang.zh')}</SelectItem>
              <SelectItem value="en">{t('lang.en')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </section>
  );
}
