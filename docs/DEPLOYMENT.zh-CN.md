# Kid PC Monitor 部署说明

本文档描述当前推荐部署方式：

- **服务器端/家长端**：运行 Web 控制面板，供家长在浏览器或手机上设置时长、锁定时间、清空限制等。
- **客户端/孩子端**：Windows 电脑上安装 `KidPCMonitorService` 服务。服务以 `LocalSystem` 运行，保存本地策略和状态；孩子机器断网时仍按最后一次成功下发的策略继续管控。

旧版 `scripts/install.py` 是计划任务方案。新部署优先使用本文档里的 `scripts/install_service.py`。

## 1. 部署前准备

### 网络规划

确认以下地址：

- 家长端 IP：运行 Web 面板的机器 IP，例如 `192.168.10.38`。
- 孩子端 IP：每台孩子 Windows 电脑的 IP，例如 `192.168.10.251`。

端口要求：

- 家长端 Web 面板监听 TCP `5000`，手机/浏览器访问这个端口。
- 孩子端服务监听 TCP `9999`，只需要允许家长端 IP 访问。

### 权限要求

- 家长端：普通用户即可运行 Web 面板；如果要开放防火墙端口，可能需要管理员/sudo。
- 孩子端：安装、升级、卸载服务必须使用管理员权限。
- 孩子日常账号建议使用标准用户，不要给本机管理员权限。

### Python

- 家长端：Python 3.10+。
- 孩子端：Windows 10/11，Python 3.10+，安装时建议勾选 “Add Python to PATH”。

## 2. 家长端/服务器端部署

以下命令在家长端机器执行。

### 2.1 获取代码并安装依赖

```bash
git clone https://github.com/foxtwobao/kid-pc-monitor.git
cd kid-pc-monitor

python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 2.2 配置孩子端密钥

每台孩子端安装后，会生成：

```text
C:\ProgramData\KidPCMonitor\agent.secret
```

在孩子端用管理员 PowerShell 读取：

```powershell
Get-Content C:\ProgramData\KidPCMonitor\agent.secret
```

把每台孩子端 IP 和密钥配置到家长端环境变量 `KID_PC_DEVICE_SECRETS`。

Linux/macOS:

```bash
export KID_PC_DEVICE_SECRETS='{"192.168.10.251":"<agent.secret里的hex密钥>"}'
```

Windows PowerShell:

```powershell
$env:KID_PC_DEVICE_SECRETS='{"192.168.10.251":"<agent.secret里的hex密钥>"}'
```

多台孩子端写在同一个 JSON 对象里：

```bash
export KID_PC_DEVICE_SECRETS='{
  "192.168.10.251": "<secret-1>",
  "192.168.10.252": "<secret-2>"
}'
```

也可以直接编辑 `src/web_panel.py` 里的 `DEVICE_SECRETS`，但不建议把真实密钥提交到 Git。

### 2.3 启动 Web 面板

从仓库根目录启动：

```bash
python -m src.web_panel
```

启动后访问：

```text
http://<家长端IP>:5000
```

例如：

```text
http://192.168.10.38:5000
```

如果从手机访问，手机必须能路由到家长端机器，并且家长端防火墙允许 TCP `5000`。

Linux UFW 示例：

```bash
sudo ufw allow 5000/tcp
```

### 2.4 Linux 上作为用户服务运行

先确认已经安装依赖，并配置好 `KID_PC_DEVICE_SECRETS`。如果要长期作为 `systemd --user` 服务运行，建议把密钥放进用户级 systemd 环境或手工编辑 unit 添加 `Environment=`。

安装服务：

```bash
chmod +x scripts/install_web_panel_linux.sh
./scripts/install_web_panel_linux.sh install
./scripts/install_web_panel_linux.sh status
```

预览 unit：

```bash
./scripts/install_web_panel_linux.sh cat-unit
```

如果希望开机后不用登录桌面也启动：

```bash
sudo loginctl enable-linger "$USER"
```

卸载家长端用户服务：

```bash
./scripts/install_web_panel_linux.sh uninstall
```

## 3. 孩子端/客户端部署

以下命令在每台孩子 Windows 电脑执行。

### 3.1 获取代码并安装依赖

用管理员 PowerShell 打开：

```powershell
git clone https://github.com/foxtwobao/kid-pc-monitor.git
cd kid-pc-monitor
python -m pip install -r requirements.txt
```

如果机器没有 Git，可以把仓库 zip 复制到本机后解压，再进入解压目录执行后续命令。

### 3.2 安装 Windows 服务

准备一个卸载令牌。这个令牌只在家长处保存，不要告诉孩子，也不要提交到仓库。

```powershell
$parentIp = "192.168.10.38"
$token = "<自己生成的长随机卸载令牌>"

python scripts\install_service.py --parent-ip $parentIp --uninstall-token $token
```

安装脚本会做这些事：

- 复制运行文件到 `C:\Program Files\KidPCMonitor\`
- 创建数据目录 `C:\ProgramData\KidPCMonitor\`
- 生成 `agent.secret`
- 安装并启动 `KidPCMonitorService`
- 配置服务失败自动重启
- 配置 Windows 防火墙，只允许 `--parent-ip` 访问 TCP `9999`
- 注册 `KidPCMonitorHelper` 登录启动项，用于在孩子桌面会话中执行锁屏/提示
- 设置 ACL，让普通 Users 只能读取运行目录和数据目录

### 3.3 验证孩子端服务

管理员 PowerShell:

```powershell
sc.exe query KidPCMonitorService
Get-Service KidPCMonitorService
netsh advfirewall firewall show rule name="Kid PC Monitor Agent"
Get-ItemProperty -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "KidPCMonitorHelper"
Get-Content C:\ProgramData\KidPCMonitor\agent.secret
```

期望：

- `KidPCMonitorService` 状态为 `RUNNING` 或 `Running`
- 启动类型为自动启动
- 防火墙规则存在，并限制到家长端 IP
- `agent.secret` 存在
- `KidPCMonitorHelper` 启动项存在

从家长端测试端口：

```bash
timeout 3 bash -c '</dev/tcp/192.168.10.251/9999' && echo open || echo closed
```

Windows PowerShell 可以用：

```powershell
Test-NetConnection 192.168.10.251 -Port 9999
```

## 4. 第一次联调

1. 在孩子端确认服务已运行，并读取 `agent.secret`。
2. 在家长端配置 `KID_PC_DEVICE_SECRETS`。
3. 在家长端启动：

```bash
python -m src.web_panel
```

4. 打开 `http://<家长端IP>:5000`。
5. 点击扫描，或直接进入孩子端 IP 对应控制页。
6. 设置一个短的每日限制或睡眠时间窗口。
7. 在孩子端确认：

```powershell
Get-Content C:\ProgramData\KidPCMonitor\policy.json
Get-Content C:\ProgramData\KidPCMonitor\state.json
Get-Content C:\ProgramData\KidPCMonitor\events.jsonl
Get-Content C:\ProgramData\KidPCMonitor\helper_commands.jsonl
```

如果孩子端暂时离线，家长端对策略类命令会记录 pending sync；等孩子端重新在线后再同步。已经成功下发到孩子端的策略会保存在本地，断网后继续生效。

## 5. 断网管控验证

推荐在测试机器上验证一次：

1. 家长端下发一个明确会锁定的策略，例如当前时间覆盖的睡眠窗口，或 1 分钟每日限制。
2. 确认孩子端 `policy.json` 已更新，`state.json` 的 `last_policy_version` 对应最新策略。
3. 暂时断开孩子端网络。
4. 等待服务 tick，确认本地仍会写入锁定状态和 helper 命令：

```powershell
Get-Content C:\ProgramData\KidPCMonitor\state.json
Get-Content C:\ProgramData\KidPCMonitor\helper_commands.jsonl
```

期望能看到类似：

```json
"active_lock_reason": "bedtime"
```

以及：

```json
{"reason": "bedtime", "type": "lock"}
```

5. 恢复网络。
6. 在家长端清空策略，确认孩子端恢复：

```powershell
Get-Content C:\ProgramData\KidPCMonitor\state.json
(Get-Item C:\ProgramData\KidPCMonitor\helper_commands.jsonl).Length
```

期望：

- `active_lock_reason` 为 `null`
- `helper_commands.jsonl` 长度为 `0`

## 6. 升级

### 家长端

```bash
git pull
source .venv/bin/activate  # Windows 用 .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m src.web_panel
```

如果使用 systemd 用户服务：

```bash
git pull
python -m pip install -r requirements.txt
systemctl --user restart kid-pc-monitor-web-panel.service
```

### 孩子端

管理员 PowerShell:

```powershell
git pull
python -m pip install -r requirements.txt
python scripts\install_service.py --parent-ip 192.168.10.38 --uninstall-token "<原卸载令牌>"
```

重新运行安装脚本会覆盖 `C:\Program Files\KidPCMonitor\` 里的运行文件；如果 `agent.secret` 已存在，不会重新生成。

## 7. 卸载

孩子端管理员 PowerShell：

```powershell
python scripts\uninstall_service.py --token "<卸载令牌>"
```

保留日志：

```powershell
python scripts\uninstall_service.py --token "<卸载令牌>" --preserve-logs
```

卸载会移除：

- `KidPCMonitorService`
- 防火墙规则
- `KidPCMonitorHelper` 登录启动项
- `C:\Program Files\KidPCMonitor\`
- 默认情况下也会删除 `C:\ProgramData\KidPCMonitor\`

## 8. 常见排查

### Web 面板启动时报 `No module named 'src'`

从仓库根目录运行：

```bash
python -m src.web_panel
```

不要进入 `src` 后执行 `python web_panel.py`。

### Web 面板显示 `No device secret configured`

家长端没有配置该孩子端 IP 的密钥。检查：

```bash
echo "$KID_PC_DEVICE_SECRETS"
```

Windows PowerShell:

```powershell
$env:KID_PC_DEVICE_SECRETS
```

### 端口连不上

检查孩子端服务：

```powershell
Get-Service KidPCMonitorService
netstat -ano | findstr 9999
netsh advfirewall firewall show rule name="Kid PC Monitor Agent"
```

检查家长端 IP 是否和安装时的 `--parent-ip` 一致。家长端换了 IP 后，需要在孩子端重新运行安装脚本或更新防火墙规则。

### 孩子端服务启动失败

查看 Windows 事件日志：

```powershell
Get-EventLog -LogName Application -Newest 30 |
  Where-Object { $_.Source -like "*KidPCMonitor*" -or $_.Message -like "*Traceback*" } |
  Format-List TimeGenerated,EntryType,Source,Message
```

也可以检查数据文件：

```powershell
Get-Content C:\ProgramData\KidPCMonitor\policy.json
Get-Content C:\ProgramData\KidPCMonitor\state.json
```

### 标准孩子账号能不能停服务

正常情况下，标准用户不能停止 `KidPCMonitorService`，也不能修改 `C:\Program Files\KidPCMonitor\` 和 `C:\ProgramData\KidPCMonitor\`。如果孩子有本机管理员权限，则不能保证不可绕过。

## 9. 安全边界

这个项目提高的是家庭场景下的管控门槛：

- 服务以 `LocalSystem` 运行
- 普通用户只有读权限
- 命令使用 HMAC 签名、时间戳和 nonce
- 防火墙可限制只有家长端能访问孩子端服务
- 策略落地到孩子端，本地离线继续执行

它不能对抗拥有管理员权限、能重装系统、能改 BIOS/启动盘、能拔硬盘的用户。实际部署时，孩子账号应保持标准用户，管理员密码和卸载令牌只由家长保存。
