# 本机 TUN 开关说明

入口：`~/.codex/bin/tun-session`，脚本本身不请求管理员权限；前提是 Clash 已配置好并安装了它自己的服务。不开放控制端口，不修改应用或插件包。

公开版初始模式为 `ask`；安装不会开启 TUN，也不会自动写入代理设置。用户可明确选择 `mode auto` 启用按需自动。使用自定义 `CODEX_HOME` 时，入口和状态目录随之迁移。

## 常用开关

| 命令 | 行为 |
|---|---|
| `tun-session status` | 查看 TUN、模式、活跃任务及恢复警告 |
| `tun-session mode auto` | 允许 Skill 按条件临时使用，命令本身不开 TUN |
| `tun-session mode ask` | 每次新申请必须先获得明确同意，再传 `--approved` |
| `tun-session mode off` | 禁止新自动申请，不打断已有任务的租约 |
| `tun-session acquire --owner CHAT_ID` | 申请默认 900 秒的临时使用权 |
| `tun-session renew LEASE` | 给仍在进行的工作续期 900 秒 |
| `tun-session release LEASE` | 释放自己的使用权；最后一个结束才恢复 |
| `tun-session keep` | 交还给用户控制，后续释放不自动关闭 |
| `tun-session restore` | 无其他活跃租约时恢复脚本拥有的状态 |
| `tun-session on` | 用户明确要求手动开启，后续按用户持有处理 |
| `tun-session off` | 用户明确要求手动关闭；有活跃任务时拒绝 |

`acquire`、`renew` 支持 `--ttl 5..7200`，正常使用建议 900 秒并按需续期。测试用的短 TTL 不应用于实际网页工作。强制恢复用 `restore --force`，强制手动关闭用 `off --force`；它们会影响其他聊天，须有用户明确的取消或应急指令。

从任意工作目录可用绝对入口；`~/.codex/bin` 若不在终端 PATH 中，不需要为此修改 shell 配置。

## 本机控制方式

- 作者验证的版本为 Clash Verge Rev 2.5.10 的中文首页，既有服务已安装。
- `scripts/clash-tun-ax` 为从随附 Swift 源码编译的本地工具，通过 macOS Accessibility 定位明确的“虚拟网卡模式”和唯一开关，读取当前值再按目标状态设置。没有找准控件会停止，不使用坐标猜测。
- 它可能把 Clash 窗口切到首页的虚拟网卡页签；不会触碰浏览器标签页。Clash 未运行时拒绝；若只是关闭了窗口，可通过正常应用打开入口恢复窗口。
- 控制工具要求现有辅助功能权限。作者的 Codex 环境已验证可用；从别的终端、应用或改变二进制签名后不保证继承权限。权限缺失时只报错，不弹窗或自行授权。
- Python 层交叉检查 `verge.yaml` 的开关与生成配置的 `tun.enable` 一致。这证明界面与配置一致，不证明所有网页都能连通，原任务仍须实测。

重新构建工具：

```sh
swiftc ~/.codex/skills/clash-tun-session/scripts/clash_tun_ax.swift -o ~/.codex/skills/clash-tun-session/scripts/clash-tun-ax
```

构建后先执行 `clash-tun-ax check` 和 `get`，确认权限与控件适配；不要以编译成功代替真实开关测试。

## 状态与异常收尾

状态放在 `~/.codex/tun-session/`，目录权限 700，文件 600。仅记录模式、原状态、租约、进程身份及恢复错误，不保存订阅、密钥或网页内容。

每次操作用文件锁串行化，不会因两个聊天同时申请而重复切换。看护仅在有租约或待恢复状态时运行，无登录启动项、常驻网络监听或系统配置修改；空闲时退出。它在启用前已启动，并持有独立进程会话。

看护每秒检查租约；默认 15 分钟不续期即回收。能识别 Codex 所属进程时记录进程及启动时间，避免 PID 重用误判；所属进程消失可提前恢复。没有识别到所属进程时仅使用 TTL。测试可用 `--owner-pid PID` 绑定专用测试进程。

为避免误关手动开启的 TUN：原来开启则永不由该租约关闭；原来关闭且本脚本开启才拥有恢复权。看护观察偏好文件修改时间，发现外部改动即放弃关闭并记录警告。这会保守地把部分无关偏好修改也视为人工接管；因此出现警告后可能需要用户明确执行手动关闭。

正常释放与租约过期/所属进程异常结束共用恢复逻辑。连续三次恢复失败即记录 `recovery-required` 并停止，避免后台无限重试。日志在 `watchdog.log`；下次 `status` 可查看错误。没有申请系统通知权限，因此不承诺在客户端关闭时弹出提醒。

机器关机时无法运行，休眠期间可能延后回收，Clash UI/权限丢失也可能阻止关闭。不要把它用于必须保证某一秒恢复网络的场景。恢复期若用户已改动 Clash 设置，优先保留用户状态。

回归测试：`python3 ~/.codex/skills/clash-tun-session/scripts/test_tun_session.py`。这些测试使用临时目录与模拟开关，不改变真实 TUN。作者的真实开关与异常退出验收摘要见仓库 README，不随仓库分发私人诊断文件。

卸载前先释放自己的租约，确认无任务及脚本持有状态；`mode off` 后移除 Skill、入口链接及 `~/.codex/AGENTS.md` 中“按需 TUN：浏览器控制连接恢复”这一小节，保留其他全局约定。不要在 TUN 仍由脚本持有时删除状态目录。

## 设计依据

- [Clash Verge 自身 TUN 切换使用配置更新流程](https://github.com/clash-verge-rev/clash-verge-rev/blob/389dddf51204984e91a9769c3dee08db2eeefbb2/src-tauri/src/feat/proxy.rs)
- [Mihomo 运行配置 API](https://wiki.metacubex.one/api/#configs)：本实现没有启用它，避免控制端口及前端状态同步问题。
