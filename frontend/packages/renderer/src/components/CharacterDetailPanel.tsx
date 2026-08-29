/** 角色详情面板（#650 角色关系 + #651 角色分组，specs/f9-character/gui-role-enhance-red-contract.md）
 * - 入口：library.tsx 角色行点名字打开；容器 character-detail-panel，标题 = 角色名，关闭 character-detail-close
 * - T1 关系区：GET/POST/PATCH/DELETE /characters/{cid}/relations（from=路径角色；编辑 from/to 不变）
 * - T2 分组区：多选 checkbox 列表 PATCH /characters/{cid} {group_ids:[...]}；管理面板 CRUD /projects/{pid}/character-groups
 * - 正交约束：group_ids（归属派系 N:M）与 extra.role_rank（等级）独立，分组控件仅存在于本面板，不进创建对话框
 */
import { useEffect, useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { Pencil, Plus, Trash2, X } from 'lucide-react';
import {
  createCharacterGroup,
  createCharacterRelation,
  deleteCharacterGroup,
  deleteCharacterRelation,
  listCharacterGroups,
  listCharacterRelations,
  listProjectCharacters,
  updateCharacter,
  updateCharacterGroup,
  updateCharacterRelation,
  type CharacterGroup,
  type CharacterDetailModel,
  type CharacterRelation,
  type ProjectCharacter,
} from '../api/character';
import { errorMessage } from '../api/client';
import { useI18n } from '../i18n/useI18n';
import { useToastStore } from '../stores/toast';
import { ConfirmDialog } from './ConfirmDialog';

export interface CharacterDetailPanelProps {
  /** 打开面板的角色（列表行对象；group_id 为 T2 归属分组字段，角色 model 有该字段） */
  item: CharacterDetailModel;
  projectId: string;
  onClose: () => void;
  /** 角色归属等变更成功后通知父级（刷新列表，可选） */
  onUpdated?: () => void;
}

const selectCls =
  'h-9 w-full rounded-md border border-line bg-surface px-3 py-1.5 text-[13px] text-ink transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-bg disabled:cursor-not-allowed disabled:opacity-50';

const inputCls =
  'h-9 w-full rounded-md border border-line bg-surface px-3 text-[13px] text-ink transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-bg';

const BTN_PRIMARY =
  'inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-[13px] text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60';

const BTN_GHOST =
  'inline-flex items-center gap-1 rounded-md border border-line px-3 py-1.5 text-[13px] text-ink-2 transition duration-180 hover:bg-surface-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60';

const ICON_BTN =
  'rounded p-1.5 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

export function CharacterDetailPanel({ item, projectId, onClose, onUpdated }: CharacterDetailPanelProps) {
  const { t } = useI18n();
  const characterId = String(item.id);
  const name = item.name ?? item.title ?? '';

  // ── T1 关系区状态 ──
  const [relations, setRelations] = useState<CharacterRelation[]>([]);
  const [relationsLoaded, setRelationsLoaded] = useState(false);
  const [relReload, setRelReload] = useState(0);
  const [relFormOpen, setRelFormOpen] = useState(false);
  const [relEditing, setRelEditing] = useState<CharacterRelation | null>(null);
  const [relFormTo, setRelFormTo] = useState('');
  const [relFormType, setRelFormType] = useState('');
  const [relFormDesc, setRelFormDesc] = useState('');
  const [pendingRelDelete, setPendingRelDelete] = useState<CharacterRelation | null>(null);

  // ── T2 分组区状态 ──
  const [selectedGroupIds, setSelectedGroupIds] = useState<(string | number)[]>(
    item.group_ids ?? (item.group_id != null ? [item.group_id] : []),
  );
  const [characters, setCharacters] = useState<ProjectCharacter[]>([]);
  const [groups, setGroups] = useState<CharacterGroup[]>([]);
  const [groupsLoaded, setGroupsLoaded] = useState(false);
  const [groupsReload, setGroupsReload] = useState(0);
  const [manageOpen, setManageOpen] = useState(false);
  const [groupFormOpen, setGroupFormOpen] = useState(false);
  const [groupEditing, setGroupEditing] = useState<CharacterGroup | null>(null);
  const [groupFormName, setGroupFormName] = useState('');
  const [groupFormDesc, setGroupFormDesc] = useState('');
  const [pendingGroupDelete, setPendingGroupDelete] = useState<CharacterGroup | null>(null);

  // 载入：关系列表（增删改后 bump relReload 局部刷新，让列表反映变化）
  useEffect(() => {
    let cancelled = false;
    void listCharacterRelations(characterId)
      .then((data) => {
        if (cancelled) return;
        setRelations(data.items ?? []);
        setRelationsLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setRelations([]);
        setRelationsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [characterId, relReload]);

  // 载入：项目角色（对方角色下拉选项来源）
  useEffect(() => {
    let cancelled = false;
    void listProjectCharacters(projectId)
      .then((data) => {
        if (!cancelled) setCharacters(data.items ?? []);
      })
      .catch(() => {
        if (!cancelled) setCharacters([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // 载入：角色分组（T2 下拉 + 管理面板；增删改后 bump groupsReload 局部刷新）
  useEffect(() => {
    let cancelled = false;
    void listCharacterGroups(projectId)
      .then((data) => {
        if (cancelled) return;
        setGroups(data.items ?? []);
        setGroupsLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setGroups([]);
        setGroupsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, groupsReload]);

  // 对方角色选项 = 项目角色排除当前角色（T1 契约）
  const otherCharacters = useMemo(
    () => characters.filter((c) => String(c.id) !== characterId),
    [characters, characterId],
  );

  // ── T1 关系 CRUD ──
  const openRelForm = (rel: CharacterRelation | null) => {
    setRelEditing(rel);
    setRelFormTo(rel ? String(rel.to_character_id) : '');
    setRelFormType(rel?.relation_type ?? '');
    setRelFormDesc(rel?.description ?? '');
    setRelFormOpen(true);
  };

  const closeRelForm = () => {
    setRelFormOpen(false);
    setRelEditing(null);
  };

  const handleRelFormSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const type = relFormType.trim();
    if (!relFormTo || !type) return;
    try {
      if (relEditing) {
        // 编辑：PATCH body={relation_type?, description?}，from/to 不变
        await updateCharacterRelation(characterId, relEditing.id, {
          relation_type: type,
          description: relFormDesc.trim(),
        });
      } else {
        // 添加：POST body={to_character_id, relation_type, description}，from=路径角色
        await createCharacterRelation(characterId, {
          to_character_id: relFormTo,
          relation_type: type,
          description: relFormDesc.trim(),
        });
      }
      setRelFormOpen(false);
      setRelEditing(null);
      setRelReload((k) => k + 1);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  const confirmRelDelete = async () => {
    if (!pendingRelDelete) return;
    try {
      await deleteCharacterRelation(characterId, pendingRelDelete.id);
      setPendingRelDelete(null);
      setRelReload((k) => k + 1);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      setPendingRelDelete(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  // ── T2 分组 CRUD ──
  /** #701：勾选/取消某分组 → 全量替换 group_ids（立即 PATCH，成功后通知父级 + toast） */
  const toggleGroup = (gid: string | number, checked: boolean) => {
    const next = checked
      ? Array.from(new Set([...selectedGroupIds, gid]))
      : selectedGroupIds.filter((id) => String(id) !== String(gid));
    setSelectedGroupIds(next);
    void patchGroupIds(next);
  };

  /** #701：「未分组」勾选 → 清空全部分组（group_ids: []）；已处于未分组时 no-op */
  const handleUngroupedToggle = () => {
    if (selectedGroupIds.length === 0) return;
    setSelectedGroupIds([]);
    void patchGroupIds([]);
  };

  /** #701：PATCH /characters/{cid} body={group_ids:[...]}（全量数组） */
  const patchGroupIds = async (ids: (string | number)[]) => {
    try {
      await updateCharacter(characterId, { group_ids: ids });
      onUpdated?.();
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  const openGroupForm = (g: CharacterGroup | null) => {
    setGroupEditing(g);
    setGroupFormName(g?.name ?? '');
    setGroupFormDesc(g?.description ?? '');
    setGroupFormOpen(true);
  };

  const closeGroupForm = () => {
    setGroupFormOpen(false);
    setGroupEditing(null);
  };

  const handleGroupFormSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const gname = groupFormName.trim();
    if (!gname) return;
    try {
      if (groupEditing) {
        await updateCharacterGroup(groupEditing.id, {
          name: gname,
          description: groupFormDesc.trim(),
        });
      } else {
        // POST body={name, description, sort_order}（顺位递增）
        await createCharacterGroup(projectId, {
          name: gname,
          description: groupFormDesc.trim(),
          sort_order: groups.length + 1,
        });
      }
      setGroupFormOpen(false);
      setGroupEditing(null);
      setGroupsReload((k) => k + 1);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  const confirmGroupDelete = async () => {
    if (!pendingGroupDelete) return;
    try {
      await deleteCharacterGroup(pendingGroupDelete.id);
      setPendingGroupDelete(null);
      setGroupsReload((k) => k + 1);
      useToastStore.getState().pushToast('ok', t('toast.saved'));
    } catch (err) {
      setPendingGroupDelete(null);
      useToastStore.getState().pushToast('err', errorMessage(err));
    }
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={name}
        data-testid="character-detail-panel"
        className="max-h-[85vh] w-[640px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 标题 = 角色名 + 关闭按钮 */}
        <div className="flex items-start justify-between gap-3">
          <h2 className="font-serif text-[18px] font-semibold">{name}</h2>
          <button
            type="button"
            data-testid="character-detail-close"
            aria-label={t('lib.charDetail.close')}
            className={ICON_BTN}
            onClick={onClose}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {/* T2 分组区：多选 checkbox 列表（#701 N:M）+ 管理入口（与等级 role_rank 正交，独立控件） */}
        <section className="mt-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-serif text-[15px] font-semibold">{t('lib.charGroup.title')}</h3>
            <button
              type="button"
              data-testid="character-group-manage"
              className={BTN_GHOST}
              onClick={() => setManageOpen(true)}
            >
              {t('lib.charGroup.manage')}
            </button>
          </div>
          <div data-testid="character-group-multi" className="mt-2 space-y-1.5">
            {groups.map((g) => {
              const checked = selectedGroupIds.some((id) => String(id) === String(g.id));
              return (
                <label
                  key={String(g.id)}
                  data-testid={`character-group-option-${g.id}`}
                  className="flex cursor-pointer items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-[13px] text-ink"
                >
                  <input
                    type="checkbox"
                    data-testid={`character-group-option-${g.id}-check`}
                    checked={checked}
                    onChange={(e) => toggleGroup(g.id, e.target.checked)}
                  />
                  <span>{g.name}</span>
                </label>
              );
            })}
            <label
              data-testid="character-group-option-ungrouped"
              className="flex cursor-pointer items-center gap-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-[13px] text-ink"
            >
              <input
                type="checkbox"
                data-testid="character-group-option-ungrouped-check"
                checked={selectedGroupIds.length === 0}
                onChange={handleUngroupedToggle}
              />
              <span>{t('lib.charGroup.ungrouped')}</span>
            </label>
          </div>
        </section>

        {/* T1 关系区：添加入口 + 列表（空态 character-rel-empty） */}
        <section className="mt-6">
          <div className="flex items-center justify-between gap-3">
            <h3 className="font-serif text-[15px] font-semibold">{t('lib.charRel.title')}</h3>
            <button
              type="button"
              data-testid="character-rel-add"
              className={BTN_PRIMARY}
              onClick={() => openRelForm(null)}
            >
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              {t('lib.charRel.add')}
            </button>
          </div>
          {relationsLoaded && (
            <div
              data-testid="character-rel-list"
              className="mt-2 divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card"
            >
              {relations.length === 0 ? (
                <div data-testid="character-rel-empty" className="px-4 py-8 text-center text-[13px] text-ink-2">
                  {t('lib.charRel.empty')}
                </div>
              ) : (
                relations.map((r) => (
                  <div
                    key={String(r.id)}
                    data-testid={`character-rel-${r.id}`}
                    className="group flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink"
                  >
                    <div className="min-w-0 flex-1">
                      <span className="font-medium">{String(r.to_character_id) === characterId ? r.from_name : r.to_name}</span>
                      <span className="mx-1.5 text-ink-3">·</span>
                      <span className="text-accent">{r.relation_type}</span>
                      {r.description ? (
                        <p className="mt-0.5 text-[12px] text-ink-2">{r.description}</p>
                      ) : null}
                    </div>
                    <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                      <button
                        type="button"
                        data-testid={`character-rel-edit-${r.id}`}
                        aria-label={`${t('lib.edit')} ${r.relation_type}`}
                        className={ICON_BTN}
                        onClick={() => openRelForm(r)}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        data-testid={`character-rel-delete-${r.id}`}
                        aria-label={`${t('lib.delete')} ${r.relation_type}`}
                        className={`${ICON_BTN} hover:text-err`}
                        onClick={() => setPendingRelDelete(r)}
                      >
                        <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </section>

        {/* 关系表单（添加/编辑共用：编辑回填现值，保存 → POST/PATCH） */}
        {relFormOpen && (
          <form
            data-testid="character-rel-form"
            className="mt-3 rounded-md border border-line bg-surface-2 p-3"
            onSubmit={(e) => void handleRelFormSubmit(e)}
          >
            <div className="flex items-center justify-between">
              <h4 className="text-[13px] font-medium">
                {relEditing ? t('lib.charRel.editTitle') : t('lib.charRel.formTitle')}
              </h4>
              <button
                type="button"
                data-testid="character-rel-form-cancel"
                className="rounded p-1 text-ink-3 transition duration-180 hover:bg-surface-3 hover:text-ink"
                aria-label={t('lib.charRel.cancel')}
                onClick={closeRelForm}
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </div>
            <label className="mt-2 block">
              <span className="text-[12px] text-ink-2">{t('lib.charRel.target')}</span>
              <select
                data-testid="character-rel-form-to"
                aria-label={t('lib.charRel.target')}
                className={`mt-1 ${selectCls}`}
                value={relFormTo}
                disabled={relEditing !== null}
                onChange={(e) => setRelFormTo(e.target.value)}
              >
                <option value="">{t('lib.charRel.targetPlaceholder')}</option>
                {otherCharacters.map((c) => (
                  <option key={String(c.id)} value={String(c.id)}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="mt-2 block">
              <span className="text-[12px] text-ink-2">{t('lib.charRel.type')}</span>
              <input
                data-testid="character-rel-form-type"
                aria-label={t('lib.charRel.type')}
                className={`mt-1 ${inputCls}`}
                value={relFormType}
                placeholder={t('lib.charRel.typePlaceholder')}
                onChange={(e) => setRelFormType(e.target.value)}
              />
            </label>
            <label className="mt-2 block">
              <span className="text-[12px] text-ink-2">{t('lib.charRel.desc')}</span>
              <input
                data-testid="character-rel-form-desc"
                aria-label={t('lib.charRel.desc')}
                className={`mt-1 ${inputCls}`}
                value={relFormDesc}
                placeholder={t('lib.charRel.descPlaceholder')}
                onChange={(e) => setRelFormDesc(e.target.value)}
              />
            </label>
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className={BTN_GHOST} onClick={closeRelForm}>
                {t('lib.charRel.cancel')}
              </button>
              <button type="submit" data-testid="character-rel-form-save" className={BTN_PRIMARY}>
                {relEditing ? t('lib.charRel.saveEdit') : t('lib.charRel.save')}
              </button>
            </div>
          </form>
        )}

        {/* T2 分组管理面板（叠加层；CRUD 表单 + 行内编辑/删除） */}
        {manageOpen && (
          <div role="presentation" className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30">
            <div
              role="dialog"
              aria-modal="true"
              aria-label={t('lib.charGroup.manage')}
              data-testid="character-group-manage-panel"
              className="max-h-[80vh] w-[480px] overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-card"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-serif text-[18px] font-semibold">{t('lib.charGroup.manage')}</h3>
                <button
                  type="button"
                  data-testid="character-group-manage-close"
                  aria-label={t('lib.charDetail.close')}
                  className={ICON_BTN}
                  onClick={() => setManageOpen(false)}
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
              <div className="mt-3 flex justify-end">
                <button
                  type="button"
                  data-testid="character-group-add"
                  className={BTN_PRIMARY}
                  onClick={() => openGroupForm(null)}
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  {t('lib.charGroup.add')}
                </button>
              </div>
              {groupsLoaded && (
                <div className="mt-3 divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface shadow-card">
                  {groups.length === 0 ? (
                    <div className="px-4 py-8 text-center text-[13px] text-ink-2">{t('lib.charGroup.empty')}</div>
                  ) : (
                    groups.map((g) => (
                      <div
                        key={String(g.id)}
                        data-testid={`character-group-row-${g.id}`}
                        className="group flex items-center gap-3 px-4 py-2.5 text-[13px] text-ink"
                      >
                        <div className="min-w-0 flex-1">
                          <span className="font-medium">{g.name}</span>
                          <span className="ml-2 text-[12px] text-ink-3">
                            {t('lib.charGroup.members', { count: g.member_count })}
                          </span>
                        </div>
                        <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity duration-180 group-hover:opacity-100 focus-within:opacity-100">
                          <button
                            type="button"
                            data-testid={`character-group-edit-${g.id}`}
                            aria-label={`${t('lib.edit')} ${g.name}`}
                            className={ICON_BTN}
                            onClick={() => openGroupForm(g)}
                          >
                            <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                          <button
                            type="button"
                            data-testid={`character-group-delete-${g.id}`}
                            aria-label={`${t('lib.delete')} ${g.name}`}
                            className={`${ICON_BTN} hover:text-err`}
                            onClick={() => setPendingGroupDelete(g)}
                          >
                            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* 新建/编辑分组表单（回填现值；保存 → POST/PATCH） */}
              {groupFormOpen && (
                <form
                  data-testid="character-group-form"
                  className="mt-3 rounded-md border border-line bg-surface-2 p-3"
                  onSubmit={(e) => void handleGroupFormSubmit(e)}
                >
                  <h4 className="text-[13px] font-medium">
                    {groupEditing ? t('lib.charGroup.editTitle') : t('lib.charGroup.formTitle')}
                  </h4>
                  <label className="mt-2 block">
                    <span className="text-[12px] text-ink-2">{t('lib.charGroup.name')}</span>
                    <input
                      data-testid="character-group-form-name"
                      aria-label={t('lib.charGroup.name')}
                      className={`mt-1 ${inputCls}`}
                      value={groupFormName}
                      onChange={(e) => setGroupFormName(e.target.value)}
                    />
                  </label>
                  <label className="mt-2 block">
                    <span className="text-[12px] text-ink-2">{t('lib.charGroup.desc')}</span>
                    <input
                      data-testid="character-group-form-desc"
                      aria-label={t('lib.charGroup.desc')}
                      className={`mt-1 ${inputCls}`}
                      value={groupFormDesc}
                      onChange={(e) => setGroupFormDesc(e.target.value)}
                    />
                  </label>
                  <div className="mt-3 flex justify-end gap-2">
                    <button type="button" className={BTN_GHOST} onClick={closeGroupForm}>
                      {t('lib.charGroup.cancel')}
                    </button>
                    <button type="submit" data-testid="character-group-form-save" className={BTN_PRIMARY}>
                      {groupEditing ? t('lib.charGroup.saveEdit') : t('lib.charGroup.save')}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        )}

        {/* 删除二次确认（真删；确认成功后列表局部刷新） */}
        {pendingRelDelete && (
          <ConfirmDialog
            open
            title={t('lib.charRel.deleteTitle')}
            message={t('lib.charRel.deleteConfirm')}
            confirmText={t('lib.delete.ok')}
            danger
            testidPrefix="character-rel-confirm"
            onConfirm={() => void confirmRelDelete()}
            onOpenChange={(open) => {
              if (!open) setPendingRelDelete(null);
            }}
          />
        )}
        {pendingGroupDelete && (
          <ConfirmDialog
            open
            title={t('lib.charGroup.deleteTitle')}
            message={t('lib.charGroup.deleteConfirm')}
            confirmText={t('lib.delete.ok')}
            danger
            testidPrefix="character-group-confirm"
            onConfirm={() => void confirmGroupDelete()}
            onOpenChange={(open) => {
              if (!open) setPendingGroupDelete(null);
            }}
          />
        )}
      </div>
    </div>
  );
}
