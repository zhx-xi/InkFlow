/** 项目页（spec §4.2.2：卡片网格 + 新建对话框，TDD 实现批次补全） */
import { useI18n } from '../i18n/useI18n';

export function ProjectsPage() {
  const { t } = useI18n();
  return (
    <div className="mx-auto max-w-[1080px] px-12 py-10">
      <div className="mb-7 flex items-baseline justify-between">
        <div>
          <h1 className="font-serif text-[26px] font-semibold">{t('pj.title')}</h1>
          <p className="mt-0.5 text-[13px] text-ink-3">{t('pj.sub')}</p>
        </div>
        <button type="button" className="btn-solid">
          {t('pj.new')}
        </button>
      </div>
      <div className="text-sm text-ink-3">{t('common.empty')}</div>
    </div>
  );
}
