# 易路由 EasyRouter

**一款全中文界面的软路由系统**：好安装、好部署，一键脚本 5 分钟上墙。

- 🌐 **全中文 Web 管理界面**（深色现代化 UI，无需任何前端构建，纯 HTML/CSS/JS）
- 📡 **DHCP 服务器**：支持「**不下发网关**」（客户端网关为空）、「**自定义网关**」（指向任一上游路由器）与**多地址池**
- 🖥️ **设备监控**：设备名称 / IP 地址 / MAC 地址，**按 IP 顺序排列**，自动识别厂商与设备类型
- 📈 **流量监控**：WAN/LAN 实时速率曲线、每台设备的上下行速率与累计流量
- 🔗 **会话监控**：**出口设备会话总数**（内核连接跟踪 conntrack）、每台设备会话数、协议分布、远程目标 TOP
- 🚪 **出口网关探针**：按网关注册上游路由器/光猫，通过 SNMP / SSH / HTTP 采集各自的**会话数与在线主机数**
- 🧩 支持 WAN 四种模式：不管理 / DHCP / 静态地址 / PPPoE 拨号
- 🧱 内置防火墙与 NAT（nftables）、每设备流量计数器、网络唤醒（Wake-on-LAN）

---

## 一、快速开始（演示模式，任意平台）

无需 Linux、无需网卡，一条命令预览全部界面（模拟数据，初始密码 `admin123`）：

```bash
python3 -m easyrouter demo          # 打开 http://127.0.0.1:8080
```

**Windows：双击 `demo/demo.bat` 即可**。启动器会自动查找可用的 Python 3
（支持系统 Python、py 启动器，以及 DSH 内置 Python），启动服务后自动打开浏览器。
若未安装 Python，请先安装 [Python 3.9+](https://www.python.org/downloads/) 并勾选
“Add python.exe to PATH”。

> 演示模式只模拟数据，不会修改本机任何网络配置，可放心运行。
> 关闭启动的黑色窗口即停止演示服务。

---

## 二、真实部署（Debian 11+ / Ubuntu 20.04+）

### 1. 一键安装

```bash
# 将本项目放到软路由主机上（U 盘 / scp 均可），进入项目目录：
sudo bash scripts/install.sh
```

脚本会自动：安装依赖（python3、nftables、dnsmasq-base、iproute2、dhclient、ppp、conntrack）
→ 复制程序 → 写入 systemd 服务 → 开启内核 IP 转发与连接跟踪计费 → 停用系统自带 dnsmasq 冲突服务。

### 2. 首次配置（二选一）

**方式 A：浏览器安装向导（推荐）**

```bash
sudo systemctl start easyrouter
```

浏览器打开 `http://<本机IP>`，跟随 4 步中文向导：设置管理员密码 → 选择 WAN/LAN 网卡 →
设置内网地址与 DHCP（含“是否下发网关”开关）→ 完成。

> 若无法直接访问（如本机尚未配置 IP），先执行方式 B 或临时给 LAN 网卡配置地址。

**方式 B：命令行向导**

```bash
cd /opt/easyrouter && sudo python3 -m easyrouter setup
```

### 3. 常用命令

```bash
systemctl status easyrouter      # 查看状态
systemctl restart easyrouter     # 重启服务
journalctl -u easyrouter -f      # 跟随日志
sudo python3 -m easyrouter check # 环境自检
sudo python3 -m easyrouter reset-password   # 重置管理员密码
sudo bash scripts/uninstall.sh   # 一键卸载
```

---

## 三、核心功能说明

### 1. DHCP 不下发网关（客户端网关一栏为空）

在「网络设置 → DHCP 服务器」中关闭「下发网关」开关后，生成的 dnsmasq 配置为：

```
# 【不下发网关】客户端获得的“默认网关”一栏为空
dhcp-option=3
```

`dhcp-option=3`（不带值）是 dnsmasq 官方支持的特殊写法：**不发送路由器(option 3)选项**，
客户端只会获得 IP、掩码与 DNS，其“默认网关”一栏保持空白（已由 dnsmasq 官方邮件列表确认）。
适用于仅需内网互联、不希望客户端通过本机访问外网的场景。

#### 自定义下发网关（软路由只做 DHCP 时）

如果你的软路由**只作为 DHCP 服务器**、实际出口是多台上游路由器，可以在「网络设置 → DHCP 服务器 →
网关地址」中填写**上游路由器的 IP**（例如 `192.168.10.1`）。这样客户端获得的默认网关指向上游路由器，
而不是这台只做 DHCP 的软路由；留空则仍下发软路由自身的 LAN 地址。

> 当前一个 DHCP 实例只能下发一个网关。若要**按客户端分配不同网关**（客户端分别走上游路由器 A/B/C），
> 需要多个地址池/标签或按静态分配指定网关，属于后续规划功能。

> 仅做 DHCP 时，如果客户端 DNS 仍指向软路由，请确保软路由自身有默认路由（例如指向某台上游路由器），
> 否则请在 DHCP 设置里把“下发 DNS”改为上游路由器或公共 DNS（如 223.5.5.5）。

#### 多地址池（同网段 / VLAN）

「网络设置 → DHCP 服务器 → 附加地址池」支持两种池，每个池可单独设置地址范围、网关、DNS、租约时间：

| 类型 | 用法 | 分配方式 |
| --- | --- | --- |
| **同网段（tagged）** | 地址范围位于默认 LAN 网段内，可把不同设备分到不同网关 | **必须在“静态分配”中把设备 MAC 绑定到该池**；DHCP 协议无法对无标签客户端随机下发不同网关 |
| **VLAN** | 独立子网（如 `eth1.20` / 192.168.20.0/24），适合按 VLAN 划分不同宽带出口 | 该 VLAN 内所有客户端自动使用此池 |

- VLAN 池保存后会自动创建 `<父接口>.<VLAN ID>` 子接口并配置本机 VLAN 地址；交换机对应端口需设为 **Trunk**；
- VLAN 池的“下发网关”留空时使用本机 VLAN 地址；若客户端要直接走该 VLAN 内的上游路由器，填该路由器地址；
- **排除地址**：支持单个 IP 或范围（如 `192.168.1.150, 192.168.1.160-192.168.1.165`），保存后会自动从池中剔除并拆分为多段分配；
- **自定义 DHCP 选项**：每行“代码,值”（如 `43,01:04:C0:A8:0A:01`），按该池标签下发，适合 option43 等场景；
- 多 LAN/VLAN 接口已纳入 NAT/转发规则与设备流量计数；VLAN 功能建议先在测试环境验证；
- 同网段池的附加范围不要与默认池重叠，否则可能产生地址冲突。

### 2. 设备监控（名称 / IP / MAC，按顺序排列）

设备信息来源于三路合并：

| 来源 | 作用 |
| --- | --- |
| dnsmasq 租约文件 | IP、MAC、DHCP 主机名、租约到期时间 |
| ARP/邻居表（ip neigh） | 当前活跃 IP ↔ MAC 对应、在线状态 |
| NetBIOS 名称查询 | 向 Windows 设备询问计算机名（可关闭） |

名称优先级：**用户别名 > DHCP 主机名 > NetBIOS 名称 > 厂商名+“设备” > “未知设备”**。
列表默认按 IP 地址自然排序（192.168.1.2 在 192.168.1.10 之前），支持搜索、
按 MAC/名称/流量/会话排序、在线过滤、一键改名与离线设备网络唤醒。

### 3. 流量监控

- **每设备上下行**：nftables 在 `inet easyrouter` 表的 `acct` 链中为每台设备维护一对计数器
  （`iifname LAN oifname != LAN ip saddr <IP> counter` / 反向规则），2 秒采样一次，
  累计流量定期落盘（SQLite），路由器重启也不丢。
- **网卡速率**：读取 `/proc/net/dev` 计数器计算 WAN/LAN 实时速率并绘制曲线。

### 4. 出口会话总数（连接跟踪）

- 出口会话总数 = **本机（软路由）内核连接跟踪表**当前条目数（`nf_conntrack_count`），在「状态概览」顶栏与
  「会话监控」页大字展示，并绘制走势曲线；
- 它统计的是 **经过本机转发的会话 + 本机自身发起的连接**（dnsmasq 向上游解析、管理页、系统更新等），
  **不是**从上游光猫/运营商设备（ONT/BRAS）读取的会话表。若 WAN 前面还有一层 NAT 路由器，
  上游设备的会话数在本机不可见；
- 同时统计每台内网设备的会话数（以该设备为源的 conntrack 条目）、TCP/UDP/ICMP 分布与远程目标 TOP 15，
  并在会话页标注“其中内网设备会话数”，便于与总数区分；
- 需要内核开启 `nf_conntrack_acct=1`（安装脚本已自动配置）。

### 5. 出口网关探针（多宽带 / 多路由器）

本机的 conntrack **看不到上游路由器/光猫的会话表和在线主机表**。若你的出口是多台上游路由器
（每台一条宽带，软路由只做 DHCP），请在「出口网关」页逐台添加上游网关并配置采集方式：

| 方式 | 适用设备 | 需要填写 | 说明 |
| --- | --- | --- | --- |
| SSH 命令 | OpenWrt / 可登录路由器 | 用户名、密码或密钥、两条命令 | 默认命令：会话数 `cat /proc/net/nf_conntrack \| wc -l`，在线主机按 conntrack 去重源 IP 统计；密码登录需安装 `sshpass` |
| SNMP v2c | 开启 SNMP 的设备 | 团体名、会话数/主机数 OID | OID 因厂商而异；两项至少填一项 |
| HTTP JSON | 提供 JSON 接口的设备 | 接口地址、字段路径 | 字段路径如 `data.sessions`；普通光猫网页通常要登录，通用性差 |
| 自动探测 | 任意 | 仅 IP | 扫描 22/80/443/8080/8443/161 等端口，识别标题、SSH 横幅、SNMP sysDescr，并推荐方式 |

- 采集结果按网关列出：**会话数**、**在线主机数**、成功/失败状态、最近错误与耗时；
- 演示模式预置了 3 台模拟网关，可在「出口网关」页直接查看效果；
- **在线主机统计口径**：默认取上游路由器的 ARP/邻居表（软路由做 DHCP 时，上游的 DHCP 租约表通常为空）。
  如果上游路由器是“路由模式”而非二层桥接，它可能只能看到软路由一个主机，此时主机数不代表全部客户端；
  可改用其无线客户端列表等命令；
- 凭据保存在 `/etc/easyrouter/config.json`（仅 root 可读），建议使用只读账号。

### 6. 防火墙与 NAT（nftables）

应用启动/保存设置时自动重建 `inet easyrouter` 表：

```
forward:    默认丢弃 → 放行 established/related → 丢弃 invalid → LAN→非LAN 放行
postrouting: 非 LAN 出口 masquerade（DHCP/静态/PPPoE 出口自动适配）
```

---

## 四、目录结构

```
easyrouter/
├── easyrouter/              # Python 主程序（仅标准库，零第三方依赖）
│   ├── app.py               # 应用装配（配置/存储/认证/后端/HTTP）
│   ├── api.py               # HTTP API（全中文错误信息）
│   ├── httpd.py             # HTTP 服务（静态资源、CSRF、会话）
│   ├── auth.py              # PBKDF2 密码哈希、登录限流
│   ├── config.py            # 配置加载/保存/校验
│   ├── store.py             # SQLite：别名/累计流量/设备档案
│   ├── monitor.py           # 采样线程：设备合并/速率/历史曲线
│   ├── gateways.py          # 出口网关探针：SNMP v2c / SSH / HTTP / 自动探测
│   ├── cli.py               # 命令行：run/demo/setup/check/reset-password
│   ├── core/                # 采集后端
│   │   ├── linux.py         # Linux 真实后端（编排下面各服务）
│   │   ├── linux_dnsmasq.py # dnsmasq 配置生成与进程看护
│   │   ├── linux_nft.py     # nftables 规则与每设备计数器
│   │   ├── linux_wan.py     # WAN 四模式 / LAN 静态地址
│   │   ├── linux_conntrack.py # 会话总数与明细
│   │   ├── linux_sys.py     # CPU/内存/网卡速率
│   │   ├── nbns.py          # NetBIOS 设备名查询
│   │   ├── oui.py           # 内置厂商前缀库
│   │   └── demo.py          # 演示后端（模拟数据）
│   └── web/                 # 全中文前端（index.html + css + js，内嵌于包）
├── scripts/install.sh       # 一键安装（root）
├── scripts/uninstall.sh     # 一键卸载（root）
├── deploy/Dockerfile        # 容器化部署（实验性）
├── deploy/docker-compose.yml
├── demo/demo.bat            # Windows 演示模式一键启动（ASCII/CRLF）
├── demo/demo.ps1            # Windows 启动逻辑（自动查找 Python、打开浏览器）
├── demo/demo.sh             # Linux/macOS 演示模式启动
├── tests/                   # 单元测试（python -m unittest discover -s tests）
└── README.md
```

## 五、开发与测试

```bash
# 单元测试（跨平台，无需 root）
python3 -m unittest discover -s tests -v

# 本地预览（演示模式）
python3 -m easyrouter demo --port 8080
```

## 六、安全说明

- 管理登录使用 PBKDF2-HMAC-SHA256（12 万次迭代）+ 随机会话令牌（HttpOnly Cookie）；
- 写操作校验同源（CSRF 防护），登录失败 5 次锁 60 秒（逐次翻倍）；
- 建议在内网使用；如需暴露公网，请在前方加反向代理并启用 HTTPS。

## 七、常见问题

| 问题 | 处理 |
| --- | --- |
| 页面打不开 | `systemctl status easyrouter` 看日志；80 端口需 root，也可改配置 `web.port` |
| 上游路由器的会话 / 在线主机数在哪看 | 「出口网关」页添加每台网关并配置 SNMP/SSH/HTTP；本机 conntrack 看不到上游设备 |
| 软路由只做 DHCP，客户端网关填谁 | 「网络设置 → DHCP 服务器 → 网关地址」填上游路由器 IP；留空则指向软路由本身 |
| SSH 探针提示需要 sshpass | 安装 `sshpass`，或把管理机公钥加入上游路由器，密码留空使用密钥登录 |
| 自动检测只发现 Web 页面 | 路由器未开放 SSH/SNMP；如有 JSON 接口可用 HTTP 方式，否则需要针对型号适配 |
| Windows 双击 demo.bat 报 “‘Windows’ 不是内部或外部命令” | 旧版启动器编码问题，**已修复**（纯 ASCII + CRLF）；请使用最新版 `demo/demo.bat` |
| Windows 双击 demo.bat 闪退/提示找不到 Python | 安装 [Python 3.9+](https://www.python.org/downloads/) 并加入 PATH；或在 cmd 中进入项目目录执行 `demo\demo.bat` 查看详细报错 |
| 演示模式能改真实配置吗 | 不能。演示模式为模拟数据，不会修改任何网络配置 |
| DHCP 客户端拿不到网关 | 若关闭了“下发网关”属于预期；开启后检查“网关地址”是否填写正确 |
| 设备没有名字 | 该设备未提供 DHCP 主机名也未响应 NetBIOS，点击名称可手动改名 |
| PPPoE 拨号失败 | 确认已安装 `ppp`，日志查看 `[network]` 记录；也可用系统 pppoeconf 拨号并选 WAN“不管理”模式 |
| 容器部署 | 见 `deploy/docker-compose.yml`（host 网络 + 特权，实验性） |

## 八、路线图

- [ ] IPv6（SLAAC/DHCPv6、前缀下发）
- [ ] 端口转发 / DMZ / UPnP
- [ ] 多 LAN / VLAN、访客网络
- [ ] 按设备的网速限制（限速、分组）
- [ ] 流量历史按天/周统计报表

## 九、制作安装镜像（GitHub Actions）

仓库已包含 .github/workflows/build-iso.yml 与 image/ 构建配置，可在云端生成 **Debian 13 + 易路由** 的自动安装 ISO（UEFI + Legacy 双启动）：

1. 在 GitHub 新建仓库，把本项目全部文件上传（包含 .github、image 目录）；
2. 打开仓库的 **Actions → Build EasyRouter Install ISO → Run workflow**；
3. 等待约 10-20 分钟，下载 **EasyRouter-install-iso** 工件并解压；
4. 用 Rufus 选择该 ISO，以 **DD 模式** 写入 U 盘；
5. 目标机从 U 盘启动，选择要安装的磁盘，自动安装 Debian 与易路由；
6. 重启后浏览器访问安装后的 IP，完成易路由安装向导。

**注意事项：**

- 安装会**格式化你选择的磁盘**，请提前备份；
- Debian netinst 安装过程需要网络；
- 控制台 root 默认密码为 EasyRouter@2026，安装后请立即修改；
- 首次云端构建如失败，请把 Actions 日志发我，便于修正 Debian ISO 版本/引导参数；
- 当前 Windows 工作区无法直接生成可引导 Linux 镜像，因此必须走 GitHub Actions（或一台 Linux 构建机）。

## 十、DHCP 租约、备份与升级（v1.1.0）

### 1. 自由租期

「网络设置 → DHCP 服务器 → 租期」可按 **年 / 月 / 日 / 时 / 分** 设置，默认池和每个附加地址池可分别设置；1 月按 30 天、1 年按 365 天换算。也可选“永久”。

### 2. 首次分配自动固定

开启「首次自动固定」后，新设备第一次拿到 IP 会写入永久静态绑定（MAC↔IP），电脑关机再开机、路由器重启后仍使用同一地址。已有绑定不会被覆盖；可在「DHCP租约」页解绑。

> 自动固定依赖 Linux 后端；批量检查周期 15 秒，应用时会重启 dnsmasq。演示模式只展示，不写入。

### 3. DHCP 租约页

左侧「DHCP租约」列出：设备名称、IP、MAC、分配时间、到期时间、地址池、绑定状态；支持搜索和在线/离线/已绑定/未绑定/即将到期筛选，可一键绑定/解绑。

### 4. 备份与恢复

「系统 → 备份与恢复」可导出 JSON（配置、管理密码哈希、设备别名、累计流量、静态绑定、网关凭据），恢复时覆盖当前配置并重启服务。备份含敏感信息，请妥善保管。

### 5. 应用升级（只升级应用，不升级 Debian）

1. 生成升级包（项目根目录）：
   ```powershell
   Compress-Archive -Path easyrouter,VERSION -DestinationPath EasyRouter-update.zip -Force
   ```
2. 「系统 → 应用升级」选择 ZIP，点“开始升级”。
3. 真实设备上会自动备份当前版本、替换程序、重启服务并做健康检查；失败自动回滚。需要 **root + systemd**。
4. 演示模式只校验升级包，不替换程序。

升级包结构要求：
```
EasyRouter-update.zip
├── VERSION
└── easyrouter/
    ├── __init__.py
    └── ...
```