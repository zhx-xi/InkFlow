/**
 * #389 世界观分类实体 state + 加载 + 新建（GET/POST /projects/{pid}/world-categories）。
 * 从 library.tsx 拆分以守 900 行护栏；失败静默空列表；新建成功 bump reloadKey 重新 GET。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch, errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';

export interface WorldCategoryEntity {
  id: string | number;
  name: string;
  count?: number;
}

export function useWorldCategories(
  currentProjectId: string | null,
  activeCat: string,
  reloadKey: number,
  onSaved?: () => void,
) {
  const { t } = useI18n();
  const [worldCategoryList, setWorldCategoryList] = useState<WorldCategoryEntity[]>([]);
  const [worldCatDialogOpen, setWorldCatDialogOpen] = useState(false);
  // 乐观追加标记：POST 成功后本地追加，随后的 GET 校准不覆盖乐观结果（避免空响应清掉 chips）
  const optimisticRef = useRef(false);

  // 世界观 tab 下加载分类实体列表（失败静默空列表；新建成功 bump reloadKey 刷新）
  useEffect(() => {
    if (!currentProjectId || activeCat !== 'world') {
      optimisticRef.current = false;
      setWorldCategoryList([]);
      return;
    }
    let cancelled = false;
    void apiFetch<{ items?: WorldCategoryEntity[] }>(
      `/api/v1/projects/${currentProjectId}/world-categories`,
    )
      .then((data) => {
        if (cancelled || optimisticRef.current) return;
        setWorldCategoryList(data.items ?? []);
      })
      .catch(() => {
        if (cancelled || optimisticRef.current) return;
        setWorldCategoryList([]);
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId, activeCat, reloadKey]);

  // 新建分类 → POST /world-categories → 成功关框 + reloadKey 刷新 + ok toast；失败 err toast
  const handleWorldCatSave = useCallback(
    async (name: string) => {
      if (!currentProjectId) return;
      try {
        await apiFetch(
          `/api/v1/projects/${currentProjectId}/world-categories`,
          { method: 'POST', body: { name } },
        );
        // 乐观更新：POST 成功后用输入名本地追加 chips（无需依赖响应实体/GET 往返），reloadKey GET 仅作校准
        optimisticRef.current = true;
        setWorldCategoryList((prev) => [
          ...prev,
          { id: `wc-${Date.now()}`, name, count: 0 },
        ]);
        setWorldCatDialogOpen(false);
        onSaved?.();
        useToastStore.getState().pushToast('ok', t('toast.saved'));
      } catch (err) {
        useToastStore.getState().pushToast('err', errorMessage(err));
      }
    },
    [currentProjectId, onSaved, t],
  );

  // #641-3：删除分类 → DELETE /world-categories/{id} → 成功本地移除 + ok toast；失败 err toast
  const handleWorldCatDelete = useCallback(
    async (id: string | number) => {
      try {
        await apiFetch(`/api/v1/world-categories/${id}`, { method: 'DELETE' });
        setWorldCategoryList((prev) => prev.filter((c) => c.id !== id));
        useToastStore.getState().pushToast('ok', t('toast.saved'));
      } catch (err) {
        useToastStore.getState().pushToast('err', errorMessage(err));
      }
    },
    [t],
  );

  return {
    worldCategoryList,
    worldCatDialogOpen,
    setWorldCatDialogOpen,
    handleWorldCatSave,
    handleWorldCatDelete,
  };
}
