# clash-tun-session skill

clash-tun-session 是一个 macOS 上的 Codex skill，解决“浏览器控制需要 TUN，但又不想一直开着”的问题：需要时临时开启 Clash Verge 的 TUN，工作结束后恢复原状态；对话中断时，再由独立看护处理到期收尾。

它管的是 **TUN 的按需使用与恢复**。浏览器断联仍要看实际读取和操作结果，不能把“开关已经打开”当成“连接一定修好了”。

## 能力

- **三种使用模式**：`ask` 每次询问、`auto` 按约定条件自动使用、`off` 禁止新的自动申请。公开版默认 `ask`，安装不会开启 TUN。
- **恢复原状态**：原本关闭、由脚本开启的，结束后关闭；原本就开启的，保持开启。
- **多个聊天可以一起用**：每个聊天领取自己的租约，只释放自己的那一份，最后一个任务结束才恢复，避免一个聊天把另一个正在用的 TUN 关掉。
- **异常收尾**：默认租约 15 分钟，可按需续期。所属进程消失或租约到期时，独立看护尝试恢复，不只靠 agent 记得执行“关闭”。
- **尊重手动改动**：发现 Clash 偏好被外部操作改写，会保守放弃自动关闭，并把原因写入状态，避免覆盖用户的选择。
- **操作 Clash 自己的开关**：通过 macOS 辅助功能定位“虚拟网卡模式”，先读值再设置；不盲点坐标，不开放外部控制端口，不直接编辑代理配置来切换。
- **有停止条件**：控件找不到、权限不可用或恢复连续失败时停止，保留恢复记录，不在后台无限重试。

## 安装

1  把[仓库链接](https://github.com/reF0o0/clash-tun-session)发给 agent，说“下载并安装这个 skill”。agent 应先说明网络影响和使用模式，再安装；安装本身不代表允许开启 TUN。

2  从 GitHub 页面选择 **Code → Download ZIP**，解压后进入仓库目录，运行：

   ```bash
   python3 install.py
   ```

3  也可以从源码装：

   ```bash
   git clone https://github.com/reF0o0/clash-tun-session.git
   cd clash-tun-session
   python3 install.py
   ```

安装程序会编译本地开关工具，把 skill 放到 `~/.codex/skills/clash-tun-session/`，并创建 `~/.codex/bin/tun-session` 入口。支持自定义 `CODEX_HOME`，不需要第三方 Python 依赖。

如果希望在全局约定里也放一句提醒，可以显式指定自己的 `AGENTS.md`：

```bash
python3 install.py --agents-file ~/.codex/AGENTS.md
```

原文件会先备份，已有同名小节不会重复添加。更新同样运行安装程序；有活跃租约或待恢复状态时会拒绝更新，避免替换仍在使用的开关工具。已有模式选择会保留，不会被更新重置。

安装后在新聊天中使用；如果当前聊天尚未发现 skill，也可以让 agent 直接读取安装目录里的 `SKILL.md`。

## 使用

需要实际控制网页时，默认优先 Chrome；用户指定浏览器、标签页或已有工作流时，遵从该选择。Chrome 不可用或任务必须在内置浏览器完成时，再使用内置浏览器。普通联网搜索和连接器任务仍使用相应专用工具；选择 Chrome 本身不会触发 TUN。

1  先选自己希望的模式。你可以直接对 agent 说“改成每次询问”“允许按需自动使用 TUN”或“禁用自动 TUN”，也可以运行：

   ```bash
   ~/.codex/bin/tun-session mode ask     # 每次新申请先询问，公开版默认
   ~/.codex/bin/tun-session mode auto    # 明确允许按条件自动使用
   ~/.codex/bin/tun-session mode off     # 禁止新自动申请，不打断已有任务
   ```

   `auto` 也有使用条件：要实际控制浏览器，并且当前机器已经有证据表明该类连接故障需要 TUN。普通聊天、写代码、读取文件、联网搜索、连接器和仅原生应用控制不触发。

2  查看当前状态：

   ```bash
   ~/.codex/bin/tun-session status
   ```

   空闲状态的输出类似这样：

   ```json
   {
     "mode": "ask",
     "enabled": false,
     "owned": false,
     "originally_enabled": null,
     "phase": "idle",
     "leases": [],
     "last_error": null,
     "watchdog_running": false
   }
   ```

3  一次临时使用。默认 `ask` 模式下，先确认同意这次开启，再执行：

   ```bash
   ~/.codex/bin/tun-session acquire --owner browser-task --approved
   ```

   记下输出里的 `lease`，完成浏览器工作后释放：

   ```bash
   ~/.codex/bin/tun-session release <lease>
   ```

   `auto` 模式不需要 `--approved`。同一任务超过 5 分钟，或剩余时间不足 2 分钟时，agent 应先续期：

   ```bash
   ~/.codex/bin/tun-session renew <lease>
   ```

4  想让当前开启的 TUN 保持开启，交还给自己控制：

   ```bash
   ~/.codex/bin/tun-session keep
   ```

   之后再释放任务租约，不会自动关闭。需要恢复脚本持有的状态时可用 `restore`；有其他活跃租约会拒绝。明确的手动开关是 `on` / `off`，`off` 同样不会无提示地中断活跃任务。

平时也可以显式用 `$clash-tun-session` 调用。完整命令与收尾规则见[使用说明](clash-tun-session/references/usage.md)。

## 什么情况下会恢复

| 情况 | 行为 |
|---|---|
| 原本关闭，本任务开启，最后一个租约结束 | 恢复关闭 |
| 原本已经开启 | 保持开启 |
| 其他聊天仍持有租约 | 保持开启，等待其他任务结束 |
| 租约到期或记录的所属进程消失 | 看护尝试回收，并按原状态恢复 |
| 用户明确选择 `keep` | 交还用户，后续不自动关闭 |
| Clash 偏好被外部操作改写 | 保守停止自动关闭，记录状态警告 |
| 恢复连续失败 | 保留 `recovery-required`，停止自动重试 |

租约默认 900 秒，`acquire` / `renew` 可以用 `--ttl` 指定 5–7200 秒。短期限适合测试，实际浏览器工作应使用足够的期限并按需续期。

## 实测结果

以下来自作者的一台 macOS / Apple Silicon 机器，Clash Verge Rev 2.5.10 中文界面；不是所有系统、版本和网络的保证。

| 测试 | 结果 |
|---|---|
| 两个任务同时使用，先释放一个 | TUN 保持开启 |
| 释放最后一个任务 | 自动恢复关闭 |
| 强制结束专用测试所属进程 | 看护约 1.9 秒恢复关闭 |
| 5 秒租约不释放 | 约 6 秒后恢复关闭 |
| 原本开启，申请后再释放 | 保持开启 |
| 脚本开启后读取公开网页、点击链接、继续读取 | 成功 |

2026-11-11 在同一台机器复测：TUN 关闭时，Chrome 打开并读取页面后出现 Statsig 超时；临时开启后，Chrome 读取、点击、导航成功，但内置浏览器仍在 30 秒后超时。因此默认优先 Chrome，并保留内置浏览器作为备选，不把这次结果视为所有环境的保证。

浏览器测试仍曾出现 `Timed out waiting for Statsig values`，因此这里不宣称解决所有浏览器故障。开启后仍要验证原任务，失败就释放租约并说明原因，不能反复开关碰运气。

仓库附带模拟开关的回归测试，不会改变真实 TUN：

```bash
python3 -m unittest discover -s clash-tun-session/scripts -p 'test_*.py'
```

覆盖并发、原本开启、默认询问、到期、续期、外部改动、部分开启失败、恢复失败和看护停止条件。

## 环境要求

- macOS；目前的真实开关验收来自 Apple Silicon。
- 已安装并配置好的 [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev)，其服务已安装，TUN 手动开关正常。
- Clash Verge 中文界面；当前控件适配按 2.5.10 验证，其他语言或界面变化需要重新适配。
- Python 3.9 或更新版本，仅使用标准库。
- Apple Command Line Tools 中的 `swiftc`，用于本机编译开关工具。
- 实际执行脚本的环境具备 macOS 辅助功能权限。工具只检查权限，不弹出授权窗口，也不会代替用户授予权限。

只读检查编译工具的权限状态：

```bash
~/.codex/skills/clash-tun-session/scripts/clash-tun-ax check
```

若从 Codex 可用、换到其他终端却不可用，需要核对那个执行环境的权限，不能把作者环境的结果直接套用过去。

## 注意事项

- TUN 会影响整机路由及部分 DNS 行为。使用的是已有 Clash 配置，不切换节点、规则模式、订阅或 DNS 设置。
- “原本已开不关闭”有真实测试；外部改动检测采用保守策略，连无关偏好改写也可能让出控制。这种情况可能需要用户明确手动恢复，状态会说明原因。
- 看护需要机器仍在运行、Clash 界面可用。休眠、关机、锁屏或辅助功能权限被撤销时，不能保证立即关闭。没有为了验收而关闭当前 Codex 客户端，也没有做断电或锁屏测试。
- 看护只在有任务或待恢复状态时运行，空闲退出；没有登录启动项或常驻网络监听。没有申请系统通知权限，恢复错误记录在状态和日志中，不保证客户端关闭时弹出提醒。
- 状态位于 `~/.codex/tun-session/`，目录权限 700、文件 600。只保存模式、租约、进程身份和恢复错误，不保存订阅密钥或网页内容。
- `restore --force` 和 `off --force` 会影响其他任务，只在用户明确取消其他任务或要求应急关闭时使用。
- 安装和 README 示例不构成开启 TUN 的授权；agent 仍须遵守用户当前选择和运行时权限要求。
- 仓库不含作者的本机绝对路径、API key、真实聊天标识、订阅配置或诊断日志；原生工具在安装时从源码编译。

卸载前先完成或释放任务，确认没有脚本持有的 TUN，再设置 `mode off`，移除 skill、入口链接和可选的全局提醒。不要在尚待恢复时直接删掉状态目录。
