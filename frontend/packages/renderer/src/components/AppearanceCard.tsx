/** 外观卡片（spec §4.2.3/§4.3 + §6.2⑤）：三主题缩略预览卡（底色 + accent 圆点 + 文字标签）
 *  + 背景随主题过滤（BG_BY_THEME）+ 语言切换，持久化到 theme store */
import { BG_BY_THEME, type Lang, type ThemeBg, type ThemeName } from '../theme';
import { useI18n } from '../i18n/useI18n';
import { useThemeStore } from '../stores/theme';
import { cn } from '../lib/cn';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

/** 三主题缩略预览卡配色（对照 tokens.css data-theme 色板：surface 底色 + ink 文字 + accent 圆点） */
const PREVIEWS: Record<ThemeName, { bg: string; fg: string; accent: string }> = {
  paper: { bg: '#F3F1EC', fg: '#2A2A28', accent: '#3B5B7C' },
  night: { bg: '#22221F', fg: '#E8E6E1', accent: '#C9A24B' },
  ink: { bg: '#EFE9DA', fg: '#2B2A26', accent: '#A6402E' },
};

const THEMES: ThemeName[] = ['paper', 'night', 'ink'];

export function AppearanceCard() {
  const { t } = useI18n();
  const theme = useThemeStore((s) => s.theme);
  const bg = useThemeStore((s) => s.bg);
  const lang = useThemeStore((s) => s.lang);
  const setTheme = useThemeStore((s) => s.setTheme);
  const setBg = useThemeStore((s) => s.setBg);
  const setLang = useThemeStore((s) => s.setLang);

  return (
    <section data-testid="appearance-card" className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('ap.title')}</h2>
      <div className="mt-4 space-y-4">
        <div className="flex flex-col gap-1.5">
          <div className="text-[12px] text-ink-2">{t('ap.theme')}</div>
          <div role="radiogroup" aria-label={t('ap.theme')} className="flex gap-3">
            {THEMES.map((th) => {
              const preview = PREVIEWS[th];
              const selected = theme === th;
              return (
                <div
                  key={th}
                  data-testid={`theme-preview-${th}`}
                  role="radio"
                  aria-checked={selected}
                  tabIndex={0}
                  onClick={() => setTheme(th)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setTheme(th);
                    }
                  }}
                  className={cn(
                    'w-28 cursor-pointer rounded-md border bg-surface p-1.5 transition duration-180 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    selected ? 'border-accent ring-2 ring-ring/50' : 'border-line hover:border-accent/50',
                  )}
                >
                  <div
                    className="flex h-12 items-end justify-between rounded-sm px-1.5 pb-1"
                    style={{ backgroundColor: preview.bg }}
                  >
                    <span className="text-[11px] font-medium" style={{ color: preview.fg }}>
                      {t(`theme.${th}`).split(' · ')[0]}
                    </span>
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: preview.accent }} />
                  </div>
                </div>
              );
            })}
          </div>
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
