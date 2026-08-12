# Provider 与模型管理（models.md）★版本敏感

agent 使用：Provider 注册表与模型管理。GUI 对应：`/models` 模型管理页（Provider CRUD + 模型增删 + 角色绑定只读）。**CLI 缺口**（#251 P1，0.8.0 修复前用 HTTP 直调）。

## 当前 CLI 能力（仅 key 文件）

| 命令 | 说明 |
|---|---|
| `llm list` | 列 Provider + key_status（读本地加密 key 文件 `data_dir/keys/`，**非** provider-configs 表） |
| `llm set-key` | 存 API Key：`--provider <name> --key <sk-...>`；stdin 管道会挂起；明文 --key 有 shell history 风险 |

⚠️ 与 GUI 的关键差异：`llm list` 显示的是 key 文件状态，**不含** provider-configs 注册表（base_url/default_model/models 列表）——GUI `/models` 页与 CLI `llm list` 看到的是两套东西。

## HTTP 直调兜底（0.8.0 前）

```powershell
# 拿 port/token（kernel.json 位置见 kernel.md：打包版 %APPDATA%\InkFlow\kernel.json）
$k = Get-Content "$env:APPDATA\InkFlow\kernel.json" | ConvertFrom-Json
$H = @{'X-InkFlow-Token'=$k.token; 'Content-Type'='application/json'}
$base = "http://127.0.0.1:$($k.port)/api/v1"

# 列 Provider（含模型表）
Invoke-RestMethod -Uri "$base/provider-configs" -Headers $H

# 新增 Provider（name 必填，正则 ^[a-z0-9_-]{1,32}$；内置 seed openai/deepseek/zhipu/ollama 删除 → 409）
Invoke-RestMethod -Uri "$base/provider-configs" -Method Post -Headers $H -Body (@{name='my-provider'; base_url='https://api.example.com'} | ConvertTo-Json)

# 模型管理：PATCH 全量 models 替换（先 GET 拿现有 models，追加后整体提交）
Invoke-RestMethod -Uri "$base/provider-configs/<id>" -Method Patch -Headers $H -Body (@{models=@(@{id='deepseek-chat'; type='chat'})} | ConvertTo-Json -Depth 5)

# LLM 连接测试（GUI ProviderDialog 同款）
Invoke-RestMethod -Uri "$base/settings/llm/test" -Method Post -Headers $H -Body (@{provider='deepseek'; api_key='sk-...'; model='deepseek/deepseek-chat'} | ConvertTo-Json)

# 落 key（POST /settings/llm-keys，body {provider, api_key}）
```

## 易错点

- key 是敏感凭据：**全程 mask**（`sk-****0a68`），不写入任何文档/skill/日志
- `data_dir/keys/` 是 key 落盘目录（明文凭据文件；`llm list` 的 key_status 即读此目录）
- PATCH models 是**整体替换**（#125 逐行失败不中断语义在 GUI，HTTP 直调需自己处理合并）
