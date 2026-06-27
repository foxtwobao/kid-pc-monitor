# 部署说明

## 最短安装

### 1. 服务端/家长端

在家长电脑上执行一行命令：

```bash
curl -fsSL https://raw.githubusercontent.com/foxtwobao/kid-pc-monitor/main/scripts/install_parent.sh | bash
```

它会自动下载项目、创建 Python 环境、安装依赖、生成配对 token、启动 Web 面板，并在终端打印孩子端安装命令。

保持这个终端窗口打开。浏览器访问：

```text
http://<家长电脑IP>:5000
```

### 2. 客户端/孩子端

在孩子 Windows 电脑上，用 **管理员 PowerShell** 执行服务端终端里打印的那一行命令，格式类似：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "iex (irm 'https://raw.githubusercontent.com/foxtwobao/kid-pc-monitor/main/scripts/install_child.ps1'); Install-KidPCMonitorChild -ParentUrl 'http://<家长电脑IP>:5000' -PairingToken '<服务端打印的token>'"
```

孩子端会自动完成：

- 下载项目
- 安装依赖
- 安装 `KidPCMonitorService`
- 列出本机 Windows 用户，让安装人员选择要监控的孩子账号
- 配置 Windows 防火墙，只允许家长端访问 TCP `9999`
- 生成孩子端密钥
- 自动把孩子端密钥注册到服务端

不需要手工复制 `agent.secret`。

用户选择规则：

1. 安装脚本会列出本机启用的 Windows 用户。
2. 输入序号选择要限制时长的孩子账号。
3. 如果你已经知道孩子账号，并且想跳过交互选择，可以在孩子端命令末尾加：

```powershell
-ChildUser "孩子Windows用户名"
```

安装脚本会把这个用户写入孩子端本地策略的 `monitored_users`，后续家长端设置时长/睡眠时间时会沿用这个用户范围。

## 前置要求

服务端/家长端：

- Linux/macOS/WSL，或其他能运行 `bash`、`curl`、`git`、`python3` 的环境
- 手机或浏览器能访问家长端 TCP `5000`

客户端/孩子端：

- Windows 10/11
- 管理员 PowerShell
- Python 3.10+
- 孩子日常账号建议是标准用户，不要给管理员权限

## 安装后检查

### 服务端

服务端终端应显示：

```text
Kid PC Monitor parent panel is ready.
Open:
  http://<家长电脑IP>:5000
Run this ONE command on each child Windows PC...
```

已配对的孩子端密钥会保存在：

```text
~/.kid-pc-monitor/app/device_secrets.json
```

孩子端用户信息会保存在：

```text
~/.kid-pc-monitor/app/device_profiles.json
```

### 孩子端

管理员 PowerShell:

```powershell
Get-Service KidPCMonitorService
netsh advfirewall firewall show rule name="Kid PC Monitor Agent"
Get-Content C:\ProgramData\KidPCMonitor\agent.secret
```

期望：

- `KidPCMonitorService` 是 `Running`
- 防火墙规则存在
- `agent.secret` 存在

## 日常使用

1. 打开 `http://<家长电脑IP>:5000`
2. 点击扫描，或进入孩子电脑控制页
3. 设置每日时长、锁定时间、发送消息或清空限制

策略成功下发后会保存在孩子电脑本地：

```text
C:\ProgramData\KidPCMonitor\policy.json
```

因此孩子电脑断网后，仍会按最后一次成功下发的策略继续管控。

## 升级

服务端重新执行同一行命令即可更新：

```bash
curl -fsSL https://raw.githubusercontent.com/foxtwobao/kid-pc-monitor/main/scripts/install_parent.sh | bash
```

孩子端重新执行服务端打印的孩子端命令即可更新服务。

## 卸载孩子端

孩子端安装时使用的配对 token 同时作为卸载 token。管理员 PowerShell:

```powershell
python "C:\Program Files\KidPCMonitor\scripts\uninstall_service.py" --token "<PairingToken>"
```

## 常见问题

### 服务端命令提示缺少 `git` 或 `python3`

先安装对应工具，再重新执行一行安装命令。

### 手机打不开 Web 面板

确认家长端防火墙允许 TCP `5000`。

Linux UFW 示例：

```bash
sudo ufw allow 5000/tcp
```

### 孩子端提示不是管理员

右键 PowerShell，选择“以管理员身份运行”，再执行服务端打印的孩子端命令。

### 孩子端提示找不到 Python

安装 Python 3.10+，安装时勾选 “Add Python to PATH”，然后重新执行孩子端命令。

### 孩子端配对失败

确认：

- 服务端终端还开着
- 孩子端能访问 `http://<家长电脑IP>:5000`
- 孩子端命令里的 `PairingToken` 没有被改错

## 安全边界

这个项目提高的是家庭场景下的管控门槛：

- 孩子端核心逻辑运行在 Windows 服务里
- 普通用户不能直接修改程序目录和策略文件
- 家长命令需要密钥签名
- 策略落地到孩子端，断网后继续执行

如果孩子拥有本机管理员权限、能重装系统、能改启动盘或能物理拆机，就不能保证无法绕过。
