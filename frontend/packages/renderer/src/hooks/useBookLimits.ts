/** F44 阶段2：多维上限配置 hook（Q2=C 项目级 ProjectConfig.extra 读写）。
 *  - values 初始 = project.config.extra 的 book_max_*（数字或 null）
 *  - setValue 仅更新本地 state（不立即持久化）
 *  - save() 合并 extra（保留既有键 + 覆盖 book_max_*；null 删除键）→ updateConfig
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { errorMessage } from '../api/client';
import { useProjectStore } from '../stores/project';

export interface BookLimitsValues {
  max_chapters: number | null;
  max_agent_calls: number | null;
  max_tokens: number | null;
  max_sessions: number | null;
}

/** extra 键 → values 字段映射（book_max_* 载体） */
const EXTRA_KEY_TO_FIELD: Array<[string, keyof BookLimitsValues]> = [
  ['book_max_chapters', 'max_chapters'],
  ['book_max_agent_calls', 'max_agent_calls'],
  ['book_max_tokens', 'max_tokens'],
  ['book_max_sessions', 'max_sessions'],
];

function readInitialValues(projectId: string): BookLimitsValues {
  const extra = useProjectStore
    .getState()
    .projects.find((p) => p.id === projectId)?.config.extra;
  const values: BookLimitsValues = {
    max_chapters: null,
    max_agent_calls: null,
    max_tokens: null,
    max_sessions: null,
  };
  for (const [extraKey, field] of EXTRA_KEY_TO_FIELD) {
    const raw = extra?.[extraKey];
    if (typeof raw === 'number') values[field] = raw;
  }
  return values;
}

export function useBookLimits(projectId: string): {
  values: BookLimitsValues;
  setValue: (field: keyof BookLimitsValues, value: number | null) => void;
  save: () => Promise<boolean>;
  saving: boolean;
  error: string | null;
} {
  const [values, setValues] = useState<BookLimitsValues>(() => readInitialValues(projectId));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const valuesRef = useRef(values);
  // 订阅项目 config.extra（外部变更后初始字段仍以本地编辑为准，仅保存时合并最新 extra）
  useProjectStore((s) => s.projects.find((p) => p.id === projectId)?.config.extra);

  const setValue = useCallback((field: keyof BookLimitsValues, value: number | null) => {
    setValues((prev) => {
      const next = { ...prev, [field]: value };
      valuesRef.current = next;
      return next;
    });
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const extra =
        useProjectStore.getState().projects.find((p) => p.id === projectId)?.config.extra ?? {};
      const merged: Record<string, number | string | boolean> = { ...extra };
      for (const [extraKey, field] of EXTRA_KEY_TO_FIELD) {
        const value = valuesRef.current[field];
        if (value === null) delete merged[extraKey];
        else merged[extraKey] = value;
      }
      await useProjectStore.getState().updateConfig(projectId, { extra: merged });
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }, [projectId]);

  return useMemo(
    () => ({ values, setValue, save, saving, error }),
    [values, setValue, save, saving, error],
  );
}
