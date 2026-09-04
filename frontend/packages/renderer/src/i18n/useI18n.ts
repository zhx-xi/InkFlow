import { useThemeStore } from '../stores/theme';
import { en } from './en';
import { roleEnhanceEn, roleEnhanceZh } from './role-enhance';
import { extractEn, extractZh } from './extract-keys';
import { logEn, logZh } from './log';
import { bookEn, bookZh } from './book';
import { worldCatKindEn, worldCatKindZh } from './world-cat-kind';
import { chatDeleteUxEn, chatDeleteUxZh } from './chat-delete-ux';
import { chatUxEn, chatUxZh } from './chat-ux';
import { sessionsUxEn, sessionsUxZh } from './sessions-ux';
import { writingUxEn, writingUxZh } from './writing-ux';
import { sessionUxEn, sessionUxZh } from './session-ux';
import { zh } from './zh';

type Dict = Record<string, string>;
const dicts: Record<'zh' | 'en', Dict> = {
  zh: { ...zh, ...roleEnhanceZh, ...extractZh, ...worldCatKindZh, ...chatUxZh, ...chatDeleteUxZh, ...sessionsUxZh, ...writingUxZh, ...sessionUxZh, ...logZh, ...bookZh } as Dict,
  en: { ...en, ...roleEnhanceEn, ...extractEn, ...worldCatKindEn, ...chatUxEn, ...chatDeleteUxEn, ...sessionsUxEn, ...writingUxEn, ...sessionUxEn, ...logEn, ...bookEn },
};

/** 简单占位替换: t('write.stream.done', { words: 342, model: 'x', valid: '通过' }) */
function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    key in params ? String(params[key]) : `{${key}}`,
  );
}

/** 轻量 i18n hook（spec §4.3：文案 <100 key 自研，不引入 i18next） */
export function useI18n() {
  const lang = useThemeStore((s) => s.lang);
  const dict = lang === 'en' ? dicts.en : dicts.zh;

  return {
    lang,
    t: (key: string, params?: Record<string, string | number>): string => {
      const template = dict[key];
      if (template === undefined) {
        // 缺 key 回退中文（开发期暴露缺失）
        return interpolate(zh[key as keyof typeof zh] ?? bookZh[key as keyof typeof bookZh] ?? key, params);
      }
      return interpolate(template, params);
    },
  };
}
