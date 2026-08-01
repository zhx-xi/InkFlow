# P0-11: 云端接口 Protocol 定义 — 功能规格

> **Spec 版本**: 1.0 | **日期**: 2026-08-01 | **依据**: PRD v2.1 §6.5, Constitution P1-P6
> **所属阶段**: Phase 1 补漏（Phase 1 Gate G4 拦截项 — 评审 `docs/phase1-gate-review-2026-08-01.md` §3.1）
> **关联 Issues**: [#34](https://github.com/zhx-xi/InkFlow/issues/34)（P0-11 云端接口 Protocol 定义）
> **依赖**: 无（纯接口定义，不依赖任何已实现模块）
> **参考 ADR**: [ADR-001](../../docs/adr/ADR-001.md)（模块化单体 + 接口隔离）, [ADR-002](../../docs/adr/ADR-002.md)（六边形分层）
> **状态**: 待实现 🔲

---

## 1. 概述

补齐 PRD P0-11：在领域层定义 6 个**云端演进接口**（Protocol），为 Phase 4+ 云端化
（PostgreSQL / 对象存储 / 多租户 / 项目同步 / Streamable HTTP）预留契约。

**核心价值**: 本地实现（SQLite / 本地文件 / 免认证 / stdio）与云端实现通过同一组
Protocol 隔离——Phase 4 换实现不换接口，领域层零改动。

> **原则**: 仅定义接口（含方法签名 + 类型 + docstring），**不实现任何云端功能**。
> 与 PRD §6.5「仅定义接口不实现」一致。

---

## 2. 架构依赖方向

```
 domain/ports/cloud/  ← 纯 Python Protocol（零框架依赖）
        ↑ 依赖倒置（Phase 4+）
 infrastructure/cloud/*  （未来实现，本次不创建）
```

- `domain/` 不 import `infrastructure/`
- 云端 Protocol 不引用任何已实现模块；已实现模块**不引用**云端 Protocol（Phase 1 本地
  路径不受影响，避免"未来契约"污染当前实现）

---

## 3. Protocol 定义

> 统一约定：所有云端 Protocol 为 `typing.Protocol`；方法为 async；docstring 注明
> 本地实现（Phase 1-3）与云端实现（Phase 4+）差异；类型用 `dataclass`/`TypedDict`，
> 不引入 Pydantic（保持 Port 层零框架依赖，与 `LLMClientProtocol` 一致）。

### 3.1 AuthProtocol — 认证

| 方法 | 签名 | 说明 |
|------|------|------|
| `authenticate` | `async (credentials: AuthCredentials) -> UserIdentity` | 本地: LocalTrust（免认证，恒通过）; 云端: JWTAuth（OAuth 2.1） |
| `verify_token` | `async (token: str) -> UserIdentity` | 云端: 校验 JWT; 本地: 返回默认身份 |

```python
@dataclass(frozen=True)
class AuthCredentials:
    """认证凭据。本地模式可为空（LocalTrust）。"""
    token: str = ""
    user_id: str = ""

@dataclass(frozen=True)
class UserIdentity:
    """认证后的用户身份。"""
    user_id: str
    display_name: str = ""

class AuthProtocol(Protocol):
    async def authenticate(self, credentials: AuthCredentials) -> UserIdentity: ...
    async def verify_token(self, token: str) -> UserIdentity: ...
```

### 3.2 DatabaseProtocol — 数据库访问

| 方法 | 签名 | 说明 |
|------|------|------|
| `connect` | `async () -> None` | 本地: SQLiteAdapter（aiosqlite）; 云端: PostgreSQLAdapter |
| `execute` | `async (statement: str, params: Mapping | None) -> Any` | 通用 SQL 执行入口（对 Repository 层透明） |
| `close` | `async () -> None` | 释放连接池 |

```python
class DatabaseProtocol(Protocol):
    async def connect(self) -> None: ...
    async def execute(self, statement: str, params: Mapping[str, Any] | None = None) -> Any: ...
    async def close(self) -> None: ...
```

### 3.3 StorageProtocol — 对象存储

| 方法 | 签名 | 说明 |
|------|------|------|
| `save` | `async (key: str, data: bytes) -> str` | 本地: LocalFileStorage（data_dir）; 云端: CloudObjectStorage（S3 兼容） |
| `load` | `async (key: str) -> bytes` | 按 key 读取 |
| `delete` | `async (key: str) -> None` | 删除对象 |

```python
class StorageProtocol(Protocol):
    async def save(self, key: str, data: bytes) -> str: ...
    async def load(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
```

### 3.4 UserProtocol — 用户管理

| 方法 | 签名 | 说明 |
|------|------|------|
| `get_user` | `async (user_id: str) -> UserProfile \| None` | 本地: SingleUser（无用户概念，返回默认）; 云端: MultiTenant |
| `list_users` | `async () -> list[UserProfile]` | 云端: 租户内用户列表 |

```python
@dataclass(frozen=True)
class UserProfile:
    user_id: str
    display_name: str
    tenant_id: str = "local"

class UserProtocol(Protocol):
    async def get_user(self, user_id: str) -> UserProfile | None: ...
    async def list_users(self) -> list[UserProfile]: ...
```

### 3.5 SyncProtocol — 项目同步

| 方法 | 签名 | 说明 |
|------|------|------|
| `push` | `async (project_id: str, payload: Mapping) -> SyncResult` | 本地: 无同步（返回 noop 结果）; 云端: CloudSync |
| `pull` | `async (project_id: str, since: datetime \| None) -> SyncResult` | 增量拉取 |

```python
@dataclass(frozen=True)
class SyncResult:
    ok: bool
    rev: str = ""
    error: str = ""

class SyncProtocol(Protocol):
    async def push(self, project_id: str, payload: Mapping[str, Any]) -> SyncResult: ...
    async def pull(self, project_id: str, since: datetime | None = None) -> SyncResult: ...
```

### 3.6 MCPTransport — Agent 传输层

| 方法 | 签名 | 说明 |
|------|------|------|
| `connect` | `async (endpoint: str) -> None` | 本地: stdio; 云端: Streamable HTTP |
| `call` | `async (tool: str, args: Mapping) -> Any` | 调用 MCP 工具 |
| `close` | `async () -> None` | 断开连接 |

```python
class MCPTransport(Protocol):
    async def connect(self, endpoint: str) -> None: ...
    async def call(self, tool: str, args: Mapping[str, Any]) -> Any: ...
    async def close(self) -> None: ...
```

---

## 4. 文件结构

```
backend/src/inkflow/domain/ports/
└── cloud/                        # CREATE（新子目录）
    ├── __init__.py               #   聚合导出（沿用 ports/__init__.py 风格）
    ├── auth.py                   #   AuthProtocol + AuthCredentials + UserIdentity
    ├── database.py               #   DatabaseProtocol
    ├── storage.py                #   StorageProtocol
    ├── user.py                   #   UserProtocol + UserProfile
    ├── sync.py                   #   SyncProtocol + SyncResult
    └── mcp_transport.py          #   MCPTransport

backend/tests/unit/
└── test_cloud_protocols.py       # CREATE — Protocol 可 import + Mock 可实例化 + 签名可调用
```

MODIFY: 无（不触碰已实现模块；`domain/ports/__init__.py` 可选导出，倾向不导出——
云端契约与本地端口解耦，显式 `from inkflow.domain.ports.cloud import ...`）

---

## 5. 边界情况与错误处理

| 场景 | 处理 |
|------|------|
| Phase 1 本地模式调用云端 Protocol | 不可能发生——本地路径不引用云端 Protocol（§2 依赖方向） |
| Mock 实现缺失方法 | Protocol 是结构子类型，Mock 缺方法在运行时 AttributeError——测试用 `Mock(spec=...)` 验证签名 |
| 云端 Protocol 与已实现端口重名 | 不存在——云端在 `cloud/` 子目录，名称带域前缀（Auth/Storage/...） |
| 未来新增云端方法 | 直接扩展 Protocol（接口演进），本地实现不受影响 |

---

## 6. 测试策略

- **层次**: 单元测试（纯 import + 签名验证，无 I/O）
- **关键场景**:
  1. 6 个 Protocol 均可 import（`from inkflow.domain.ports.cloud import ...`）
  2. 每个 Protocol 用 `Mock(spec=Protocol)` 验证方法签名存在且可调用
  3. 数据类型（AuthCredentials/UserIdentity/UserProfile/SyncResult）可实例化
  4. dataclass 字段默认值符合本地模式（如 `tenant_id="local"`）
- **命令**: `cd backend && pytest tests/unit/test_cloud_protocols.py -v`
- **覆盖率目标**: 新增文件 100%（纯接口定义）

---

## 7. 不在范围内

| 项 | 原因 | 阶段 |
|----|------|------|
| 云端实现（JWT/PostgreSQL/S3/MultiTenant/CloudSync/Streamable HTTP） | PRD 明确"仅定义接口不实现" | Phase 4+ |
| 本地实现改造（SQLite→DatabaseProtocol 适配） | 本地路径已稳定，接口预留即可 | Phase 4+ |
| MCP Server 功能 | P1-11 独立需求 | Phase 3 |

---

## 8. 依赖关系

```
P0-11 依赖: 无（纯接口定义）
P0-11 被依赖: 无（Phase 4+ 云端实现消费；当前模块不引用）
```

---

## 9. 关键架构决策记录

| 决策 | 方案 | 理由 |
|------|------|------|
| Protocol 放 `domain/ports/cloud/` 子目录 | 独立子目录 | 与本地端口解耦；演进边界清晰（ADR-001 模块化单体） |
| 零框架依赖（typing.Protocol + dataclass） | 不用 Pydantic | 与 `LLMClientProtocol` 一致；Port 层保持纯净（ADR-002） |
| 已实现模块不引用云端 Protocol | 单向依赖 | 避免"未来契约"反向污染当前实现；Phase 4 换实现不换接口 |
| 方法集最小化（2-3 个/Protocol） | 骨架级签名 | 满足契约意图即可；过度设计接口 = 空中楼阁 |

---

## 10. 验收标准

- **M1**: 6 个 Protocol 文件 + `cloud/__init__.py` 聚合导出
- **M2**: `backend/tests/unit/test_cloud_protocols.py` 全绿（import + Mock 签名验证 + dataclass 实例化）
- **M3**: `cd backend && pytest tests/unit/test_cloud_protocols.py -v` 通过；全量 `pytest tests/` 无回归
- **M4**: PR 引用 #34（`Closes #34`）与 ADR-001/ADR-002；Issue 验收清单全部勾选
