# F61: 密钥自举与告警收敛（secret_key_bootstrap）— 功能规格

> **端**: backend（config 启动源 + key_manager 存储层）

> **Spec 版本**: 1.0 | **日期**: 2026-09-11 | **依据**: Issue #1096（0.15.0 milestone）

> **关联 Issues**: #1096（本模块）；#1076（F60 首启引导框架，本模块为其安全面增量）；#821（明文/密文交叉尝试兼容，本模块须保持其语义）；#614（F53 secret redact，消费 `redact.load_known_keys`）

> **依赖**: ✅ `core/config.py` 多源配置链（#977/#987）· ✅ `APIKeyManager` AES-256-GCM（F5）· ✅ `provider_config._load_stored_key` 三级回退链（#821）

> **参考 ADR**: ADR-008（配置管理，config.py 单一出口）

> **状态**: 🚧 实施中（#1096）

---

## 1. 概述与根因（代码实锤，2026-09-11）

`INKFLOW_SECRET_KEY` 未设置时，`APIKeyManager` 退化为明文存储用户 API Key。这是**已知降级路径**，但存在三个缺口：

| # | 缺口 | 根因（文件:行） |
|---|------|----------------|
| G1 | 每进程重复告警 **16 次** | `infrastructure/llm/key_manager.py:30-33` — 告警在 `__init__` 内，**无任何去重**；而 7 个调用点**均未缓存实例**，每次调用都新建 |
| G2 | 用户不可见 | 告警只落 `logs/inkflow_<date>.log`，GUI 无提示 |
| G3 | 无生成/设置入口 | `secret_key` 仅能从 `INKFLOW_SECRET_KEY` env 注入（`core/config.py:351`），零自动生成 |

### 1.1 G1 「16」的构成分析

调用点全集（`grep 'APIKeyManager('`）：

| 调用点 | 频率 |
|--------|------|
| `infrastructure/llm/provider_config.py:72` | `_load_stored_key` 主路径，**每次 key 解析调一次** |
| `infrastructure/llm/provider_config.py:88` | `_load_stored_key` 交叉尝试，**同一函数内第二次 new** |
| `infrastructure/llm/redact.py:90` | `load_known_keys()`，每次 chat 调用调一次 |
| `api/routers/settings.py:121` | `_get_key_manager()` 工厂 |
| `api/routers/provider_configs.py:82` | `_to_response` — **每个 provider 调一次** |
| `api/deps.py:688` | `_build_store()`（embedding 装配） |
| `api/deps_kg_extract.py:66` | KG 抽取装配 |
| `cli/commands/llm.py:23` | CLI 工厂 |

单个 GUI 会话中 `_load_stored_key`（×2/次）+ `provider_configs._to_response`（×N provider）+ 若干装配，累计到 16 条。**根因是实例未复用 + 告警无去重，二者叠加**。

### 1.2 交互规格（渲染面硬要求）

| 场景 | 必须 | 禁止 |
|------|------|------|
| 告警在 `__init__` 内无条件触发 | 去重后每进程 ≤1 条 | 每次实例化各打一条 |
| 多线程/并发实例化 | 去重原子（首条竞争只有一个赢家） | 依赖「先到先得」的时序巧合 |

---

## 2. 需求定义

- **目标**：全新数据目录首启时，`INKFLOW_SECRET_KEY` 缺失 → **自动生成**随机密钥并落盘 → 告警降级为单次 INFO；显式设置该 env 时零告警。
- **非目标**：
  - 不提供 GUI 弹窗/选择界面（方案 B 不在本模块范围；GUI 可见性由字段消费面 `secret_key_ready` 承接，见 §5）。
  - 不迁移已有明文 `keys/*.key` 文件为密文（存量文件靠 #821 交叉尝试继续可读，§3.4 边界 4）。
  - 不改动 `_load_stored_key` 三级回退链语义（#821 契约保持）。
  - 不引入新设置键（`secret_key` 字段已存在，沿用；镜像 #770 轻量契约先例）。

---

## 3. 设计

### 3.1 告警去重（G1，方案 A/B/C 共同必做）

位置：`backend/src/inkflow/infrastructure/llm/key_manager.py`

```python
# 模块级去重 flag（每进程一次）
_SECRET_KEY_WARNED = False


def _warn_empty_secret_key_once() -> None:
    """空 secret_key 降级告警，每进程至多一条（#1096 G1）。

    多线程原子：先置位再打日志，check-and-set 之间无线程切换窗口。
    """
    global _SECRET_KEY_WARNED
    if _SECRET_KEY_WARNED:
        return
    _SECRET_KEY_WARNED = True
    logger.info(...)
```

**关键契约**：
- 告警级别从 `WARNING` 降为 `INFO`（方案 A 下「已自动生成」属正常路径，非警告）。
- 去重是**模块级**的，跨实例生效。
- 位置从 `__init__` 内部**移出**，改为「显式空 key 构造时调用一次」——但 A 方案落地后 `key_manager` 收到的 key 通常非空，该函数主要服务「生成失败/显式绕过」的兜底路径。

### 3.2 密钥自举（方案 A，G3）

位置：`backend/src/inkflow/core/config.py`

```python
SECRET_KEY_FILENAME = ".secret_key"

def load_or_create_secret_key(data_dir: Path) -> str:
    """读取 <data_dir>/keys/.secret_key；缺失则生成并落盘（权限 0600）。

    生成物：secrets.token_urlsafe(32) 的 hex 形态（64 hex chars = 32 bytes，
    与 APIKeyManager._get_or_derive_key 的 bytes.fromhex 期望一致）。

    Returns:
        64 hex chars 密钥串；IO 失败时返回 ""（调用方退化为明文降级）。
    """
```

**设计裁定**：

| 决策点 | 裁定 | 理由 |
|--------|------|------|
| D1 落盘位置 | `<data_dir>/keys/.secret_key` | **不用** issue 原文的 `<data_dir>/.secret_key`——与密文文件同域（`keys/`），备份/迁移只需带走 `keys/` 一个目录；且 `provider_config._load_stored_key` 已锚定 `keys/`（#821） |
| D2 已存在时不重新生成 | **必须** | 重新生成 → 已加密的 `keys/*.json` 全部解不开（**不可逆数据丢失**）。这是本方案最高危点，RED 契约专测 |
| D3 生成后回写 `config.secret_key` | **必须** | 否则同进程内 `config.secret_key` 仍为 `""`，7 个调用点仍走明文分支——A 方案最隐蔽的失效模式 |
| D4 权限 | POSIX `chmod 0600`；Windows 平台跳过（POSIX 权限位在 NTFS 无语义） | 跨平台不报错 |
| D5 IO 失败 | 返回 `""` → 退化为既有明文降级 + 单次 INFO 告警 | 不因密钥落盘失败而阻断启动 |
| D6 与显式 env 的关系 | 显式 `INKFLOW_SECRET_KEY` 非空时**完全不触碰文件系统**（不读不写） | 反例验收：显式设置 → 零告警、零落盘 |

### 3.3 装配顺序（避免鸡生蛋）

`config.py` 的 `_derive_paths`（`@model_validator(mode="after")`，L354）已保证 `data_dir.mkdir` 先执行。自举挂在该 validator 之后、且**仅当 `secret_key` 不在 `model_fields_set` 时**（镜像既有 `database_url`/`vector_store_dir`/`debug` 的「显式值优先」范式 L363-375）：

```
data_dir.mkdir → database_url 派生 → vector_store_dir 派生 → debug 派生
    → [新增] if "secret_key" not in model_fields_set:
              self.secret_key = load_or_create_secret_key(self.data_dir)
```

优先级链（`init > 进程 env > instance.env > .env > config.json > secrets`，L204）不变——env 显式值天然进 `model_fields_set`，自动跳过自举。

### 3.4 边界

| # | 边界 | 行为 |
|---|------|------|
| 1 | `<data_dir>/keys/.secret_key` 已存在 | 读取其内容，**不重新生成**（D2） |
| 2 | `keys/` 目录不存在 | 创建（含父目录）后生成 |
| 3 | `keys/.secret_key` 存在但内容为空/非法 | 视为缺失 → 生成覆盖？**否**——按「内容为空串」处理为异常，退化为 `""`（保守：宁可明文降级，不覆盖可能有效的密钥文件） |
| 4 | 存量 `keys/*.key` 明文文件（升级用户） | 不受影响——`_load_stored_key` 第 2 级明文读取仍命中（#821 语义保留）；新写入的 key 走密文 |
| 5 | 显式 `INKFLOW_SECRET_KEY` | 零告警、零文件系统访问 |
| 6 | 多个进程并发首启 | 两进程可能各生成一份，后写者胜——两进程各自内存中的 key 均可解密自己写的数据；**已知局限**，不引入文件锁（详 §7 取舍） |

### 3.5 可见性最小面（G2）

本模块**不建 GUI 弹窗**，但为消费面提供可读信号：`GET /api/v1/settings/model-readiness`（F60 已建，spec f60 §3.1）响应中新增 `secret_key_ready: bool` 字段（= `bool(config.secret_key)`）。GUI 侧渲染归 F60 后续迭代，本模块只保证**信号可查**。

---

## 4. 测试策略（RED 契约 → GREEN）

### 4.1 边界与异常矩阵

| 用例 | 输入 | 期望 |
|------|------|------|
| E1 全新目录无人为密钥 | `load_or_create_secret_key(tmp_dir)` | 返回 64 hex；`<tmp>/keys/.secret_key` 存在且内容 == 返回值 |
| E2 幂等（**不可逆风险守护**） | 连续调两次 | 两次返回**相同**值；文件内容不变 |
| E3 权限 | POSIX 下 stat 文件 | `mode & 0o777 == 0o600`；Windows 跳过（`sys.platform` 分支） |
| E4 空内容文件 | 预写空文件 | 退化返回 `""`（**不覆盖**）；文件内容仍为空 |
| E5 IO 失败 | `keys/` 路径被同名文件占位 | 返回 `""`，不抛异常 |
| E6 告警去重（**核心验收**） | 连续构造 16 个空 key 的 `APIKeyManager` | loguru sink 捕获的告警数 **== 1** |
| E7 反例：非空 key | 构造 16 个非空 key 实例 | 告警数 **== 0** |
| E8 告警级别 | 空 key 构造 | 级别为 `INFO`，非 `WARNING` |
| E9 装配接线 | `InkFlowConfig` 在全新 data_dir 下实例化 | `config.secret_key` 非空且 == 文件内容 |
| E10 显式 env 优先 | `INKFLOW_SECRET_KEY=<hex>` + 全新 data_dir | `config.secret_key == <hex>`；**文件未被创建** |
| E11 反例：显式 env 零告警 | 同上 | 告警数 == 0 |

### 4.2 测试形态

- 单元轨：`backend/tests/unit/core/test_secret_key_bootstrap.py`（NEW）—— E1-E5、E9-E11
- 单元轨：`backend/tests/unit/infrastructure/llm/test_key_manager.py`（MODIFY 末尾追加段）—— E6-E8
- API 轨：`tests/api/test_settings_api.py`（MODIFY，追加 `secret_key_ready` 字段用例）
- 告警捕获用 **loguru sink**（`logger.add(sink, level="INFO")` + 移除），镜像既有 F53 日志测试形态

### 4.3 RED 预期形态

- NEW 文件：收集期 `ImportError: cannot import name 'load_or_create_secret_key'`（等价 ModuleNotFoundError，exit 2）
- MODIFY 追加段：新用例 FAILED（`APIKeyManager` 现状每次 `__init__` 都告警 → 计数 16 ≠ 1），既有用例全 PASS
- 反例 E7/E11 在 RED 期即 PASS（**守护用例**，刻意为之；docstring 注明防父侧误判）

---

## 5. 验收判据（对齐 issue #1096）

- [ ] 全新数据目录启动后 `logs` 中该告警 **≤1 条**（非 16 条）
- [ ] key 实际加密存储（`keys/*.json` 密文；`APIKeyManager.load` 往返成功）
- [ ] 落盘文件权限 0600（POSIX）
- [ ] 反例：显式 `INKFLOW_SECRET_KEY` → **零**告警、零落盘
- [ ] 已存在密钥文件 → 不重新生成（数据可逆性守护）

---

## 6. 影响面

| 文件 | 改动 |
|------|------|
| `backend/src/inkflow/core/config.py` | 新增 `SECRET_KEY_FILENAME` + `load_or_create_secret_key()`；`_derive_paths` 追加自举分支 |
| `backend/src/inkflow/infrastructure/llm/key_manager.py` | 模块级去重 flag + `_warn_empty_secret_key_once()`；告警级别 WARNING→INFO |
| `backend/src/inkflow/api/routers/settings.py` | `model-readiness` 响应加 `secret_key_ready` |
| `backend/tests/unit/core/test_secret_key_bootstrap.py` | NEW |
| `backend/tests/unit/infrastructure/llm/test_key_manager.py` | 追加段 |
| `tests/api/test_settings_api.py` | 追加段 |
| `ci_cd/openapi_snapshot.json` + `frontend/.../openapi.d.ts` | 契约变更 → 必刷（本仓门禁） |

---

## 7. 已知取舍（记录，非阻断）

| 取舍 | 选择 | 放弃 |
|------|------|------|
| 自动生成 vs 用户显式选择 | **自动生成** | 与「AI 自动化默认关闭显式开启」偏好有张力——但本处自动化的对象是**安全默认值**（fail-safe），非功能行为；且用户仍可用 env 显式覆盖。方案 B（GUI 弹窗）留待 F60 迭代 |
| 文件锁 vs 无锁并发 | **无锁** | 多进程并发首启存在后写者胜的理论窗口。InkFlow 为单机单用户自用，内核进程单实例（ADR-030），实际不可达 |
| 保留明文降级路径 | **保留** | 未彻底移除明文模式（`secret_key=""` 构造仍可明文）——既有测试 `test_plaintext_mode` 等 5 个用例依赖该分支；彻底移除属破坏性变更，超出本 issue 范围 |
