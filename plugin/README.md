# mmod-workflow DSH 插件（动态 Cordis Plugin）

把本仓库的 8 步数学建模工作流引擎封装为 DSH（DeepSeek Harness）动态插件：

- **Host 半**（`host.js`）：注册 `mmod_workflow` 模型工具，驱动引擎全部动作
  （init/status/start/complete/gate/checkpoint/advance/resume/backfill/sync-state/report），
  另注册 `mmod-status` RPC 供状态看板读取。
- **Client 半**（`client.js`）：在设置页注册「数学建模工作流」8 步状态看板
  （S1–S8 状态、进度、8 秒自动刷新）。

## 安装（在 DSH 会话中）

动态插件是进程内临时扩展，需在会话中定义并激活；DSH 重启后重新激活即可
（定义与授权保留，`cordis_run` 重新 run）。

1. 准备环境：本仓库克隆到会话工作区根目录（引擎相对路径
   `scripts/workflow_engine.py` 必须可用；Windows 需 Python 3.10+）。
2. 在 DSH 会话中调用 `cordis_define`：
   - `plugin.kind: "new"`，`idPrefix: "mmod"`
   - `code.host` = `host.js` 的完整内容
   - `code.client` = `client.js` 的完整内容
3. `cordis_run` 激活（Client 半首次需在浏览器授权）。
4. 之后 Agent 可直接调用 `mmod_workflow` 工具；设置页出现「数学建模工作流」看板。

## 设计要点

- 通过 `shell` 服务以 argv 文本执行引擎（工作目录 = 会话工作区）；
  自由文本参数（title/note/response/feedback）经 `b64:` 前缀编码传递
  （引擎 `scripts/workflow_engine.py` 已内置 `decode_b64` 解码）。
- 沙箱策略取自 `sandboxPolicy.resolve({ session })`（会话级 workspaceRoot），
  不硬编码路径；`exec.agent.session.header.cwd` 提供会话工作区。
- 工具输出 schema 遵循 DSH value schema DSL（无 `required`、object 必须显式
  `additionalProperties`）。
