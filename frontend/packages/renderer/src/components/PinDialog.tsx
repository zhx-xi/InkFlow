/**
 * F43 P2 pin 对话框（specs/f43-setting-library-crud/spec.md §5.12）：
 * 标记名称（必填 1-50 字符去空白）+ 类型四档（shadcn Select）+ 关联实体可搜索选择
 * （type=other 隐藏关联字段；本地过滤 refOptions，含「不关联」选项）。
 * editing 非空 = 编辑模式预填；#195 拍板：遮罩点击不关闭（仅 取消/Esc/保存成功后关闭）。
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useI18n } from '../i18n/useI18n';
import type { MapPinDTO, PinType } from './MapWorkbench';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';

export interface PinRefOption {
  id: string;
  name: string;
  /** 关联实体类别（location/role/event；兼容纯 {id,name} 调用方） */
  type?: string;
}

export interface PinSaveInput {
  type: PinType;
  locationId?: string | null;
  refId?: string | null;
  x: number;
  y: number;
  label: string;
}

export interface PinDialogProps {
  open: boolean;
  /** 非空 = 编辑模式预填（名称/类型/关联/坐标） */
  editing?: MapPinDTO | null;
  /** 点击画布传入的坐标（新建模式预填） */
  defaultX?: number;
  defaultY?: number;
  /** 关联实体候选（按 type 由父级传入） */
  refOptions: PinRefOption[];
  onSave: (input: PinSaveInput) => void;
  onOpenChange: (open: boolean) => void;
}

const PIN_TYPES: PinType[] = ['location', 'role', 'event', 'other'];

const INPUT_CLS =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm outline-none focus:border-accent';

/** 字段行：label 文案 + 控件（label/aria-label 双关联，与 LibraryCreateDialog 同款） */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px]">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function PinDialog({
  open,
  editing = null,
  defaultX,
  defaultY,
  refOptions,
  onSave,
  onOpenChange,
}: PinDialogProps) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [type, setType] = useState<PinType>('location');
  const [refId, setRefId] = useState<string | null>(null);
  const [refQuery, setRefQuery] = useState('');

  // 打开时初始化表单：editing 非空 → 预填现值；空 → 重置新建态
  useEffect(() => {
    if (!open) return;
    setName(editing?.label ?? '');
    setType((editing?.type as PinType | undefined) ?? 'location');
    setRefId(
      editing
        ? String(
            (editing.type === 'location' ? editing.location_id : editing.ref_id) ?? '',
          ) || null
        : null,
    );
    setRefQuery('');
  }, [open, editing]);

  // ESC 关闭（尊重 Radix Select 等已 preventDefault 的 Escape；#195 遮罩不关闭）
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) onOpenChange(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, onOpenChange]);

  if (!open) return null;

  const trimmed = name.trim();
  // 必填 1-50 字符去空白（超长禁用）
  const canSave = trimmed.length > 0 && trimmed.length <= 50;
  const showRef = type !== 'other';
  const query = refQuery.trim().toLowerCase();
  const filteredRefs = showRef
    ? refOptions.filter(
        (o) =>
          (o.type === undefined || o.type === type) &&
          (query === '' || o.name.toLowerCase().includes(query)),
      )
    : [];
  const selectedRef = showRef ? (refOptions.find((o) => o.id === refId) ?? null) : null;

  const handleSave = () => {
    if (!canSave) return;
    onSave({
      type,
      locationId: type === 'location' ? refId : null,
      refId: type === 'role' || type === 'event' ? refId : null,
      x: editing ? editing.x : (defaultX ?? 0),
      y: editing ? editing.y : (defaultY ?? 0),
      label: trimmed,
    });
  };

  return (
    <div role="presentation" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={editing ? t('lib.pinEdit') : t('lib.pinNew')}
        data-testid="pin-dialog"
        className="w-[420px] rounded-lg border border-line bg-surface p-6 shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="font-serif text-[18px] font-semibold">
          {editing ? t('lib.pinEdit') : t('lib.pinNew')}
        </h2>
        <div className="mt-4 space-y-4">
          <Field label={t('lib.pin.name')}>
            <input
              data-testid="pin-name"
              aria-label={t('lib.pin.name')}
              className={INPUT_CLS}
              maxLength={50}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field label={t('lib.pin.type')}>
            <Select value={type} onValueChange={(v) => setType(v as PinType)}>
              <SelectTrigger data-testid="pin-type" aria-label={t('lib.pin.type')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PIN_TYPES.map((pinType) => (
                  <SelectItem key={pinType} value={pinType}>
                    {t(`lib.pinType.${pinType}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {showRef && (
            <Field label={t('lib.pin.ref')}>
              <input
                data-testid="pin-ref"
                aria-label={t('lib.pin.ref')}
                className={INPUT_CLS}
                placeholder={t('lib.pin.refPlaceholder', { type: t(`lib.pinType.${type}`) })}
                value={selectedRef ? selectedRef.name : refQuery}
                onChange={(e) => {
                  setRefId(null);
                  setRefQuery(e.target.value);
                }}
              />
              <div
                role="listbox"
                aria-label={t('lib.pin.ref')}
                className="max-h-44 overflow-y-auto rounded-md border border-line bg-surface"
              >
                <button
                  type="button"
                  role="option"
                  aria-selected={refId === null}
                  className="block w-full px-3 py-1.5 text-left text-[13px] text-ink-2 transition-colors hover:bg-surface-2"
                  onClick={() => {
                    setRefId(null);
                    setRefQuery('');
                  }}
                >
                  {t('lib.pin.refNone')}
                </button>
                {filteredRefs.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    role="option"
                    aria-selected={refId === opt.id}
                    className="block w-full px-3 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-surface-2"
                    onClick={() => {
                      setRefId(opt.id);
                      setRefQuery(opt.name);
                    }}
                  >
                    {opt.name}
                  </button>
                ))}
              </div>
            </Field>
          )}
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            data-testid="pin-cancel"
            className="rounded-md border border-line px-4 py-1.5 text-sm text-ink-2 transition duration-180 hover:bg-surface-3"
            onClick={() => onOpenChange(false)}
          >
            {t('lib.pin.cancel')}
          </button>
          <button
            type="button"
            data-testid="pin-save"
            className="rounded-md bg-accent px-4 py-1.5 text-sm text-accent-ink transition duration-180 hover:bg-accent-hover active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canSave}
            onClick={handleSave}
          >
            {t('lib.pin.save')}
          </button>
        </div>
      </div>
    </div>
  );
}
