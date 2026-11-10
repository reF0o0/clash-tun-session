---
name: clash-tun-session
description: Manage temporary Clash Verge TUN sessions on macOS for Computer Use browser connection failures, preserving the prior state and coordinating multiple chats. Use also for the user's TUN mode, status, or recovery requests; ordinary chat, code work, web search, connectors, and native-app-only tasks do not need TUN.
---

# 按需使用 TUN

安装此 Skill 不等于授权开启 TUN。首次使用前确认用户选择：公开版默认 `ask`，只有用户明确授权按需自动时才执行 `mode auto`。授权仅覆盖当前约定的用途；保留运行时要求的确认，不授予额外权限。不要修改节点、规则模式、订阅、DNS 配置、Codex 启动项或控制端口。

入口：`~/.codex/bin/tun-session`（使用自定义 `CODEX_HOME` 时为该目录的 `bin/tun-session`）。详细命令及限制见 [使用说明](references/usage.md)。脚本操作 Clash 自身开关，不依赖浏览器控制是否连通。

## 何时使用

- 先看用户的当前偏好及 `tun-session status`。`mode off` 时禁止自动开启；`mode ask` 需要本次明确同意后才能传 `--approved`。
- `mode auto`：仅在要实际控制 Chrome/内置浏览器，且已出现连接超时、调试连接丢失等故障时使用。只有在当前用户的机器上已经验证 TUN 对照有效、且明确授权自动模式时，才可在同类故障的后续浏览器工作开始前临时使用；不把本仓库作者的测试当作当前机器的证据。
- 普通联网搜索、连接器、写代码、读取文件、原生应用控制不自动触发。用户说“不要改变网络”“正在考试”“暂时不允许”等约束优先。
- 切换前简短说明将临时开启 TUN、保持原有规则模式；已有明确授权时不重复要求一般确认。遇到新的管理员、辅助功能或其他权限要求时停在该步骤，不代替用户授权。

## 一次浏览器工作

1. `status`；如当前聊天已有未过期租约，确认 owner 是本聊天后复用并 `renew`，不重复申请。其他聊天的租约不得续期或释放。
2. `acquire --owner <当前聊天ID或唯一任务标签>`，保存返回的 `lease`。默认有效 15 分钟；超过 5 分钟或剩余不足 2 分钟时，在继续工具操作前 `renew <lease>`。为仍在进行的工作续期，不为已结束任务无限续期。
3. 验证原任务的实际页面读取/操作。TUN 开启、标签枚举或 HTTP 401/403 都不等于任务成功。开启后仍失败时只作一次有依据的有限复测，随后释放并说明实际阻塞点，不反复切换。
4. 在完成、失败、取消、切换到无关任务，以及等待用户接手前，执行 `release <lease>` 并检查输出。进行中的上传/提交等先等到可安全交接，不为关开关打断它们；需要长时间交接时说明租约期限。
5. 结束只释放自己的租约，不执行 `off --force`。最后一个租约才恢复；原本已开的 TUN 保持开启。

## 外部改动与异常

- 检测到 Clash 偏好文件被其他操作改写时，看护会保守放弃自动关闭，即使只是无关设置。输出 `external-change` 或 `last_error` 时，明确告诉用户目前状态；不擅自覆盖该变化。
- 用户明确希望保持开启：`keep` 交还控制，再释放本聊天租约。用户要禁用自动使用：`mode off`，这不会打断已有租约。
- 租约过期或记录的所属进程消失时，独立看护尝试恢复；不依赖模型记得收尾。辅助功能被撤销、界面无法使用或机器休眠/关机时不能承诺立即恢复。连续恢复失败会保留 `recovery-required`，停止自动重试，在下一次状态查询时明确报告。
- `restore` 只恢复脚本拥有的状态；存在活跃租约会拒绝。`restore --force`、`off --force` 仅在用户明确要求取消其他任务或紧急关闭时使用。
- 不通过直接编辑 Clash YAML、Mihomo API、隐藏接口或坐标盲点绕过脚本的状态检查；若控件变更，保留状态记录并报告，先修复可观察的失配。

正常用户可直接说“禁用自动 TUN”“改成每次询问”“恢复按需自动”“查看 TUN 状态”。按对应命令执行并报告实际状态；模式切换本身不会开启 TUN。
