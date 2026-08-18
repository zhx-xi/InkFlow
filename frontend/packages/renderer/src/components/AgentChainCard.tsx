/** 写作 Agent 链（spec §4.2.3）：Architect/Writer/Auditor/Reviser 四行开关 ↔ config.agent_*；
 *  #225 三态语义：null=关闭（禁用角色）；字符串=开启且指定模型；
 *  "__default__"（AGENT_DEFAULT_SENTINEL）=跟随默认（预留，前端不暴露中间态 UI） */
import { useEffect, useState } from 'react';
import { GitBranch, Sparkles, type LucideIcon } from 'lucide-react';
import { useI18n } from '../i18n/useI18n';
import { useAgentStore } from '../stores/agent';
import { useAgentsStore } from '../stores/agents';
import { selectChatModelOptions, useModelsStore } from '../stores/models';
import { AGENT_DEFAULT_SENTINEL, type ProjectConfig } from '../stores/project';
import { useTemplatesStore } from '../stores/templates';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { Switch } from './ui/switch';
import { AgentRelationEditor } from './AgentRelationEditor';

type AgentField =
  | 'agent_architect'
  | 'agent_writer'
  | 'agent_auditor'
  | 'agent_reviser'
  | 'agent_worldview'
  | 'agent_polisher';

/** v1.5 #484：内置链角色键（模板 roles 过滤用——模板自定义键但无 Agent 实体仍渲染，§5.7.2 兼容既有模板；
 *  内置 4 键即使 agents 缺实体也不降级为自定义行） */
const BUILTIN_ROLE_KEYS = ['architect', 'writer', 'auditor', 'reviser'] as const;
/** F42 #296 / v1.5 #484：内置字段写顶层 config.agent_*（6 键）；自定义字段写 config.agent_roles */
const BUILTIN_FIELDS = [
  'agent_architect',
  'agent_writer',
  'agent_auditor',
  'agent_reviser',
  'agent_worldview',
  'agent_polisher',
];

/** 内置角色行（#473 R1：name/desc/icon 从 GET /api/v1/agents 按 role_key 派生；builtin=true → 读 config.agent_*） */
type BuiltinChainRow = {
  field: AgentField;
  name: string;
  desc: string;
  icon: string;
  builtin: true;
};

/** 自定义角色行（显示名 = role.name ?? 裸名；builtin=false → 读 config.agent_roles） */
type CustomChainRow = {
  field: string;
  name: string;
  icon: LucideIcon;
  builtin: false;
};

type ChainRow = BuiltinChainRow | CustomChainRow;

/** F42 #269：默认模板拓扑（与后端默认模板槽位一致：architect=0/writer=1/auditor=2/reviser=3）；
 *  agent_order 空/undefined 时仅用于显示与首次移动时显式化（B1 默认模板模式） */
const DEFAULT_AGENT_ORDER: string[][] = [
  ['agent_architect'],
  ['agent_writer'],
  ['agent_auditor'],
  ['agent_reviser'],
];

/** 角色 → 默认槽位（开启角色时写入 agent_order 的目标槽位，spec §5.3/M6；v1.5 #484 扩展 6 内置） */
const DEFAULT_SLOTS: Record<string, number> = {
  agent_architect: 0,
  agent_writer: 1,
  agent_auditor: 2,
  agent_reviser: 3,
  agent_worldview: 4,
  agent_polisher: 5,
};

export interface AgentChainCardProps {
  /** 开关变更回调（#105 🔴-2：AgentPanel 即改即存 PATCH；不传则仅更新本地 store） */
  onConfigChange?: () => void;
}

function agentPatch(
  field: string,
  value: string | null,
  current: ProjectConfig,
): Partial<ProjectConfig> {
  // 内置字段 → 顶层 config.agent_*；自定义字段 → agent_roles 浅合并（防丢其他自定义角色）
  if (BUILTIN_FIELDS.includes(field)) {
    const patch: Partial<ProjectConfig> & Record<string, string | null> = {};
    patch[field] = value;
    return patch;
  }
  return { agent_roles: { ...(current.agent_roles ?? {}), [field]: value } };
}

/** 当前 order 派生：agent_order 非空 = 配置驱动模式；空/undefined = 默认模板拓扑（仅显示） */
function deriveOrder(config: ProjectConfig): string[][] {
  return config.agent_order && config.agent_order.length > 0
    ? config.agent_order
    : DEFAULT_AGENT_ORDER;
}

/** F42 #296：角色默认槽位（内置 0-3；自定义 = 4 + roles 顺序索引，不在列表则 4） */
function defaultSlotOf(field: string, customRoleFields: string[]): number {
  if (field in DEFAULT_SLOTS) {
    return DEFAULT_SLOTS[field];
  }
  const idx = customRoleFields.indexOf(field);
  return idx >= 0 ? 4 + idx : 4;
}

/** 角色所在层索引（不在 order 中 → 默认槽位，用于显示与移动边界判定） */
function slotOf(order: string[][], field: string, customRoleFields: string[]): number {
  const idx = order.findIndex((layer) => layer.includes(field));
  return idx >= 0 ? idx : defaultSlotOf(field, customRoleFields);
}

export function AgentChainCard({ onConfigChange }: AgentChainCardProps = {}) {
  const { t } = useI18n();
  const config = useAgentStore((s) => s.config);
  const setConfig = useAgentStore((s) => s.setConfig);
  const providers = useModelsStore((s) => s.providers);
  // F46 #270：依赖关系编辑器展开态（点行内「依赖」入口切换）
  const [relationOpen, setRelationOpen] = useState(false);
  // v1.5 #484：角色池展开态（点「添加角色」切换，spec §5.7.3）
  const [rolePoolOpen, setRolePoolOpen] = useState(false);

  // F42 #268（spec §5.2 Q3）：挂载即加载 provider-configs 数据源，Select 选项随 store 响应式更新
  useEffect(() => {
    void useModelsStore.getState().loadProviders();
    // F42 #296：挂载即加载模板，自定义角色行随模板响应式更新（与 loadProviders 并行）
    void useTemplatesStore.getState().loadTemplates();
    // #473 R1：挂载即加载 Agents（内置角色行按 role_key 派生的数据源，与上两者并行）
    void useAgentsStore.getState().loadAgents();
  }, []);

  const chatOptions = selectChatModelOptions(providers);
  const followDefaultOption = { value: AGENT_DEFAULT_SENTINEL, label: t('ag.followDefault') };

  // F42 #296：模板 roles 非四键 → 自定义角色行（显示名 = role.name ?? 裸名，Sparkles 图标）
  // ?? [] 兜底：loadTemplates 响应缺 items 时 store 可能短暂为 undefined（边界守卫，不改契约语义）
  const templates = useTemplatesStore((s) => s.templates) ?? [];
  const template = templates.find((t) => String(t.id) === String(config.template_id));
  // #473 R1：内置行从后端真源派生——按链角色键顺序匹配 role_key（与后端列表顺序无关）；
  // role_key 缺失（agents 未加载/缺该内置）→ 该行不渲染（派生严格性）
  const agents = useAgentsStore((s) => s.agents) ?? [];
  const chain = deriveOrder(config);
  const chainFields = chain.flat();

  // v1.5 #484（spec §5.7.1/§5.7.2）：内置行 = 默认 4 链角色（既有零回归：关闭后行保留、可重开）
  // ∪ 配置 order 中的新内置角色（worldview/polisher 进链后渲染）；显示顺序按 DEFAULT_SLOTS（M6 契约）
  const builtinFields = [...new Set([...DEFAULT_AGENT_ORDER.flat(), ...chainFields])];
  const builtinRows: BuiltinChainRow[] = builtinFields
    .sort(
      (a, b) =>
        (DEFAULT_SLOTS[a] ?? Number.MAX_SAFE_INTEGER) -
        (DEFAULT_SLOTS[b] ?? Number.MAX_SAFE_INTEGER),
    )
    .map((field) => agents.find((a) => a.builtin && a.role_key === field.replace(/^agent_/, '')))
    .filter((a): a is NonNullable<typeof a> => a != null)
    .map((a) => ({
      field: `agent_${a.role_key}` as AgentField,
      name: a.name,
      desc: a.description,
      icon: a.icon,
      builtin: true,
    }));

  // v1.5 #484：自定义 Agent 行 = 链中角色在 agents 匹配 builtin=false（仅进链后渲染，§5.7.2）
  const customAgentRows: CustomChainRow[] = chainFields
    .map((field) => {
      const agent = agents.find(
        (a) => a.role_key === field.replace(/^agent_/, '') && !a.builtin,
      );
      return agent
        ? { field, name: agent.name, icon: Sparkles, builtin: false }
        : null;
    })
    .filter((r): r is CustomChainRow => r != null);

  // F42 #296 兼容（§5.7.2 注）：模板 roles 非内置键且无 agents 实体 → 自定义角色行（显示名 = role.name ?? 裸名）
  const agentRoleKeys = new Set(agents.filter((a) => a.role_key).map((a) => a.role_key));
  const templateCustomRows: CustomChainRow[] = template
    ? Object.entries(template.roles)
        .filter(
          ([key]) =>
            !agentRoleKeys.has(key) &&
            !(BUILTIN_ROLE_KEYS as readonly string[]).includes(key),
        )
        .map(([bareName, role]) => ({
          field: `agent_${bareName}`,
          name: role.name ?? bareName,
          icon: Sparkles,
          builtin: false,
        }))
    : [];

  const customRoleFields = [...customAgentRows, ...templateCustomRows].map((r) => r.field);
  const allRows: ChainRow[] = [...builtinRows, ...customAgentRows, ...templateCustomRows];
  const renderedFields = new Set(allRows.map((r) => r.field));

  // v1.5 #484（spec §5.7.2/§5.7.3）：角色池 = agents 真源全量（role_key 非空）− 已渲染行字段
  const rolePoolOptions = agents
    .filter((a) => a.role_key && !renderedFields.has(`agent_${a.role_key}`))
    .map((a) => ({ field: `agent_${a.role_key as string}`, name: a.name }));

  const addRole = (field: string) => {
    // ① 写入三态字段 = sentinel（跟随默认；内置 → 顶层 agent_*，自定义 → agent_roles）
    // ② agent_order 显式化：未在链中 → 追加末尾层（配置驱动模式显式化，B1 语义）
    const patch = agentPatch(field, AGENT_DEFAULT_SENTINEL, config);
    const base = deriveOrder(config).map((layer) => [...layer]);
    if (!base.some((layer) => layer.includes(field))) base.push([field]);
    setConfig({ ...patch, agent_order: base });
    setRolePoolOpen(false);
    onConfigChange?.();
  };

  return (
    <section data-testid="agent-chain-card" className="rounded-lg border border-line bg-surface p-6 shadow-card">
      <h2 className="font-serif text-[17px] font-semibold">{t('ag.chainTitle')}</h2>
      <p className="mt-1 text-[12px] text-ink-3">{t('ag.chainDesc')}</p>
      <div className="mt-4 divide-y divide-line">
        {allRows.map((role) => {
          const value = role.builtin
            ? config[role.field as AgentField]
            : config.agent_roles?.[role.field];
          const displayName = role.name;
          // 三态语义（#225）：null=关闭（禁用角色）；字符串=开启且指定模型；
          // "__default__"（AGENT_DEFAULT_SENTINEL）=跟随默认（预留）
          const checked = typeof value === 'string';
          const tagWarn =
            typeof value === 'string' &&
            value !== AGENT_DEFAULT_SENTINEL &&
            !chatOptions.some((o) => o.value === value);
          const tag =
            value == null
              ? t('ag.disabled')
              : value === AGENT_DEFAULT_SENTINEL
                ? t('ag.defaultModel')
                : tagWarn && !value.includes('/')
                  ? t('ag.modelFormatFix')
                  : tagWarn
                    ? t('ag.unregisteredModel')
                    : value;
          // F42 #269：槽位号 + 上移/下移边界（M6 契约）
          const order = deriveOrder(config);
          const slot = slotOf(order, role.field, customRoleFields);
          const idx = order.findIndex((layer) => layer.includes(role.field));
          const upDisabled = idx <= 0; // 首层或不在 order → 上移禁用
          const downDisabled = idx < 0 || idx === order.length - 1; // 末层或不在 order → 下移禁用
          const moveRole = (direction: 'up' | 'down') => {
            // 上移 = 并入上一层（与该层角色并行）；下移 = 并入下一层；
            // 移动后空层压缩；操作作用于 config.agent_order（首次移动显式化默认拓扑）
            const base = deriveOrder(config).map((layer) => [...layer]);
            const current = base.findIndex((layer) => layer.includes(role.field));
            if (current < 0) return;
            const target = direction === 'up' ? current - 1 : current + 1;
            if (target < 0 || target >= base.length) return;
            const targetLayer = base[target]; // 目标层（field 不在其中）
            // 从原层移除角色；层变空 → 压缩删除
            base[current] = base[current].filter((r) => r !== role.field);
            const compressed = base.filter((layer) => layer.length > 0);
            // 目标层在压缩后的位置（filter 保留引用，内容定位）
            const targetIdx = compressed.findIndex((layer) => layer === targetLayer);
            if (targetIdx >= 0) {
              // 并入目标层末尾（保持层内既有角色）
              compressed[targetIdx].push(role.field);
            } else {
              // 目标层为空槽（[]）→ 按压缩后位置插入新层
              const before = base
                .slice(0, target)
                .filter((layer) => layer.length > 0).length;
              compressed.splice(before, 0, [role.field]);
            }
            // #347：移动 = 该角色参与管线 → 未启用时自动启用（sentinel 跟随默认），
            // 防后端 C1「配置驱动模式至少需要 1 个启用角色」422
            const fieldValue = BUILTIN_FIELDS.includes(role.field)
              ? config[role.field as AgentField]
              : (config.agent_roles ?? {})[role.field];
            if (fieldValue == null || fieldValue === '') {
              const patch = agentPatch(role.field, AGENT_DEFAULT_SENTINEL, config);
              setConfig({ ...patch, agent_order: compressed });
            } else {
              setConfig({ agent_order: compressed });
            }
            onConfigChange?.();
          };
          const toggle = () => {
            // 关闭 → 显式 null（JSON.stringify 保留 → 后端落库 null → 重启仍关闭）；
            // 配置驱动模式（order 非空）同步从 agent_order 剔除该角色并压缩空层（B1）；
            // 打开 → sentinel "__default__"（跟随默认，本期无模型选择 UI）；
            // 配置驱动模式同步加入默认槽位；默认模板模式（order 空）不写 agent_order
            const patch = agentPatch(role.field, checked ? null : AGENT_DEFAULT_SENTINEL, config);
            if (checked) {
              // 关闭
              if (config.agent_order && config.agent_order.length > 0) {
                const removed = config.agent_order
                  .map((layer) => layer.filter((r) => r !== role.field))
                  .filter((layer) => layer.length > 0);
                setConfig({ ...patch, agent_order: removed });
              } else {
                setConfig(patch);
              }
            } else if (config.agent_order && config.agent_order.length > 0) {
              // 开启（配置驱动模式）：角色加入默认槽位（新层插入，既有层后移）
              const order = config.agent_order.map((layer) => [...layer]);
              order.splice(defaultSlotOf(role.field, customRoleFields), 0, [role.field]);
              setConfig({ ...patch, agent_order: order });
            } else {
              // 开启（默认模板模式）：只写 field，不写 agent_order（B1 保持默认模式）
              setConfig(patch);
            }
            onConfigChange?.();
          };
          return (
            <div key={role.field} className="flex items-center gap-3 py-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent-weak text-accent">
                {role.builtin ? role.icon : <role.icon className="h-4 w-4" aria-hidden="true" />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-medium">{displayName}</span>
                  <span
                    className={`rounded bg-surface-3 px-1.5 py-0.5 text-[11px] ${tagWarn ? 'text-warn' : 'text-ink-3'}`}
                  >
                    {tag}
                  </span>
                </div>
                {role.builtin && role.desc && (
                  <p className="mt-0.5 text-[12px] text-ink-3">{role.desc}</p>
                )}
              </div>
              {/* F42 #269：槽位号 + 上移/下移（M6 契约，data-testid 即契约） */}
              <div className="flex shrink-0 items-center gap-1" aria-label={`${t('ag.slot')} ${slot}`}>
                <span
                  data-testid={`agent-order-slot-${role.field}`}
                  className="rounded bg-surface-3 px-1.5 py-0.5 text-[11px] text-ink-3"
                  aria-label={`${t('ag.slot')} ${slot}`}
                >
                  {slot}
                </span>
                <button
                  type="button"
                  data-testid={`agent-order-move-up-${role.field}`}
                  aria-label={t('ag.moveUp')}
                  disabled={upDisabled}
                  onClick={() => moveRole('up')}
                  className="flex h-6 w-6 items-center justify-center rounded border border-line text-ink-3 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ↑
                </button>
                <button
                  type="button"
                  data-testid={`agent-order-move-down-${role.field}`}
                  aria-label={t('ag.moveDown')}
                  disabled={downDisabled}
                  onClick={() => moveRole('down')}
                  className="flex h-6 w-6 items-center justify-center rounded border border-line text-ink-3 hover:bg-surface-3 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  ↓
                </button>
              </div>
              {checked && (
                <Select
                  value={typeof value === 'string' ? value : AGENT_DEFAULT_SENTINEL}
                  onValueChange={(v) => {
                    setConfig(agentPatch(role.field, v, config));
                    onConfigChange?.();
                  }}
                >
                  <SelectTrigger
                    data-testid={`agent-model-select-${role.field}`}
                    aria-label={t('ag.defaultModel')}
                    className="w-52"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={followDefaultOption.value}>{followDefaultOption.label}</SelectItem>
                    {chatOptions.map((o) => (
                      <SelectItem key={o.value} value={o.value}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              {/* F46 #270：依赖入口（spec §5.2）——切换显示 AgentRelationEditor */}
              <button
                type="button"
                data-testid={`agent-relation-entry-${role.field}`}
                aria-label={t('ag.relationEntry')}
                onClick={() => setRelationOpen((v) => !v)}
                className="flex h-6 w-6 items-center justify-center rounded border border-line text-ink-3 hover:bg-surface-3"
              >
                <GitBranch className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
              <Switch checked={checked} onCheckedChange={toggle} aria-label={displayName} />
            </div>
          );
        })}
      </div>
      {/* v1.5 #484：添加角色（spec §5.7.3）——角色行列表之后、依赖编辑器之前 */}
      <div className="mt-3">
        <button
          type="button"
          data-testid="agent-chain-add-role"
          onClick={() => setRolePoolOpen((v) => !v)}
          className="flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-[12px] text-ink-3 transition-colors hover:bg-surface-3"
        >
          + {t('ag.addRole')}
        </button>
        {rolePoolOpen && (
          <div className="mt-2 flex flex-wrap gap-2" data-testid="agent-chain-role-pool">
            {rolePoolOptions.map((option) => (
              <button
                key={option.field}
                type="button"
                data-testid={`agent-chain-role-option-${option.field}`}
                onClick={() => addRole(option.field)}
                className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] text-ink-3 transition-colors hover:bg-surface-3"
              >
                {option.name}
              </button>
            ))}
          </div>
        )}
      </div>
      {/* F46 #270：依赖关系编辑器（section 内关系列表区，即角色行 </div> 之后、</section> 之前） */}
      {relationOpen && <AgentRelationEditor onConfigChange={onConfigChange} />}
    </section>
  );
}
