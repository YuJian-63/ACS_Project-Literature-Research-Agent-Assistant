# main 自动部署到 ECS

适用于当前 `acs@8.218.149.237`、systemd、Nginx 和 PostgreSQL 17 容器的安装。工作流位于 [deploy-ecs.yml](../.github/workflows/deploy-ecs.yml)。

## 1. 部署行为

推送到 `main` 后，GitHub 托管 Runner 构建前端，导出带哈希的后端生产依赖，将该提交的 Git bundle、前端产物、requirements 和校验清单上传 ECS。服务器不需要保存 GitHub 访问令牌，也不从 GitHub 拉取代码。

服务器按顺序执行：

1. 获取部署锁，确认当前分支为 `main`、工作区干净、五个应用服务及 Nginx 正常。
2. 验证发布包、完整提交 SHA、快进关系及至少 2 GB 剩余磁盘空间。
3. 在独立发布目录解包源码、准备 Python 3.12 环境，从 PyPI 安装锁定依赖，并比较新旧配置解析结果。
4. 备份 `.env`、Nginx 配置和前端；暂停应用服务，备份 PostgreSQL 并验证备份可读取。
5. 快进更新工作区，切换虚拟环境，执行 Alembic 迁移并等待 API `/ready`。
6. 启动研究、解析、导入和邮件 Worker，再发布前端。保留旧哈希资源，最后原子替换 `index.html`。
7. 检查经过 Nginx 返回的页面、HTTPS `/ready`、服务状态及部署 SHA。

更新源码包含当前 `main` 的 Agent 和 TACC 作业模板，后续新任务使用新版本。不会取消 TACC 远程作业，也不会改写现有鉴权、SMTP、arXiv、百炼、SSH 或 TACC 配置。Worker 会短暂停机；不能把一次代码更新等同于所有跨版本研究任务均可无缝恢复。

Actions 串行运行且不取消正在执行的部署。GitHub 默认可能用更新的待运行提交替换较旧的待运行提交，因此目标是自动部署最新 `main`，不保证每一个中间提交都单独上线。服务暂停期间 API 暂时不可用，这不是零停机方案。

## 2. 一次性安装 ECS 部署入口

先安装入口，再将工作流推送 `main`，避免第一次触发时入口尚不存在。

生产 `backend/.env` 中的 `STORAGE_ROOT` 必须明确设置为持久目录的绝对路径；当前 ECS 为 `/home/acs/acs-data/storage`。可选 `AGENT_EXCHANGE_ROOT` 应留空使用默认值，或同样使用绝对路径。开发示例中的 `runtime/storage` 是相对路径，不适用于这种独立发布目录的生产部署。脚本会在停服务前检查并拒绝相对路径，不会擅自搬迁已有 PDF。

在 **Windows PowerShell，项目根目录**，使用已有 ECS 登录密钥上传四个运维文件：

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_rsa" `
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes `
  acs@8.218.149.237 'mkdir -p /home/acs/acs-deploy/auto-bootstrap'

scp -i "$env:USERPROFILE\.ssh\id_rsa" `
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes `
  .\ops\deploy\setup-ecs.sh `
  .\ops\deploy\deploy-ecs.sh `
  .\ops\deploy\release.py `
  .\ops\deploy\backup_database.py `
  acs@8.218.149.237:/home/acs/acs-deploy/auto-bootstrap/
```

在 **ECS root 终端**：

```bash
command -v sudo >/dev/null || dnf -y install sudo
bash /home/acs/acs-deploy/auto-bootstrap/setup-ecs.sh
runuser -u acs -- sudo -n -l /usr/local/sbin/acs-deploy-release
```

安装脚本不重启服务。它将固定入口和辅助程序安装为 root 所有，给 `acs` 仅授予执行该入口的免密 sudo 权限；入口仅接受完整 SHA 和数字运行编号，不接受任意 shell 命令。前端目录改为由 `acs` 管理，Nginx 仍只有读取权限。

后续修改 `ops/deploy/` 中的已安装程序后，需要重新上传并以 root 运行安装脚本；自动部署不会自行替换特权入口。

## 3. 为 GitHub Actions 创建专用 ECS 登录密钥

在 **Windows PowerShell** 运行以下命令。若目标文件已存在，停止并确认用途，不要覆盖现有密钥。

```powershell
ssh-keygen -t ed25519 `
  -f "$env:USERPROFILE\.ssh\acs_ecs_deploy" `
  -C 'github-actions-ecs-deploy'
```

用于无人值守部署时，口令提示直接按 Enter，再按 Enter 确认。查看公钥：

```powershell
Get-Content "$env:USERPROFILE\.ssh\acs_ecs_deploy.pub"
```

在 **ECS 的 acs 终端**，将下面占位内容替换为刚生成的整行公钥：

```bash
install -d -m 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
printf '%s\n' 'restrict ssh-ed25519 在这里填写公钥 github-actions-ecs-deploy' >> "$HOME/.ssh/authorized_keys"
```

`restrict` 禁止端口转发、代理转发和 PTY，保留 SSH 命令与 SCP/SFTP 上传能力。保留原有 `authorized_keys` 内容。这个密钥只能用于 ECS，不复用个人登录密钥或 TACC 私钥。

在 Windows 测试专用密钥；此命令只检查入口权限：

```powershell
ssh -i "$env:USERPROFILE\.ssh\acs_ecs_deploy" `
  -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes `
  acs@8.218.149.237 'sudo -n -l /usr/local/sbin/acs-deploy-release'
```

## 4. 配置 GitHub Repository secrets

打开仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加：

| 名称 | 内容 |
| --- | --- |
| `ECS_SSH_PRIVATE_KEY` | 新生成的 `acs_ecs_deploy` 私钥全文，包括 BEGIN/END 行 |
| `ECS_SSH_KNOWN_HOSTS` | 经过验证的服务器 ED25519 known_hosts 整行 |

可以在 Windows 将私钥复制到剪贴板后直接粘贴到 GitHub secret，避免在终端输出：

```powershell
Get-Content -Raw "$env:USERPROFILE\.ssh\acs_ecs_deploy" | Set-Clipboard
```

粘贴完成后清空剪贴板，不要将私钥发到聊天、写入仓库或放在普通 Actions Variables 中。

在 **ECS root 终端**检查主机公钥指纹并输出 known_hosts 行：

```bash
ssh-keygen -E sha256 -lf /etc/ssh/ssh_host_ed25519_key.pub
awk '{print "8.218.149.237 " $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub
```

此前确认过的指纹是 `SHA256:fiuyczygVkv3kXcwxBf24pPe81kYtDbX1JdyUpZW6IY`。若不同，先核实是否更换了服务器主机密钥，再设置 secret。不要通过关闭主机校验解决连接问题。

默认地址为 `8.218.149.237:22`。如网络入口变化，可设置 Repository variables `ECS_HOST`、`ECS_PORT`，并同步更新 known_hosts 的主机名；非 22 端口须使用 `[主机名或IP]:端口` 格式。部署程序本身仍针对当前安装及其公网 HTTPS 地址。安全组需要允许 GitHub 托管 Runner 的 SSH 连接；如果 SSH 只允许个人 IP，应先确定合适的固定出口或 Runner 方案，不要盲目放开全部端口。

GitHub 不需要数据库密码、SMTP 授权码、百炼 API Key 或 TACC 密钥。仓库 **Settings → Actions → General** 中应允许 GitHub Actions 和所使用的官方 Actions。

## 5. 发布并检查第一次自动部署

确认入口、专用密钥和两个 secrets 配置完成后，将本次部署文件提交并推送到 `main`。本地准备脚本不会替你提交或推送。

在仓库 **Actions → Deploy main to ECS** 查看运行。也可以选择 **Run workflow → main** 手动触发；工作流不允许部署其他分支。它始终部署触发时的完整提交 SHA，不会在执行中改成另一个版本。

成功时日志出现：

```text
Database backup: OK
Deployment complete: <完整 SHA>
Backup: /var/backups/acs/<SHA>-<运行编号>-<随机后缀>
```

在 **ECS root 终端**核对：

```bash
git -c safe.directory=/home/acs/ACS_Project-Literature-Research-Agent-Assistant \
  -C /home/acs/ACS_Project-Literature-Research-Agent-Assistant rev-parse HEAD
systemctl is-active acs-api acs-runner acs-parser acs-import acs-mail nginx
curl -fsS https://8.218.149.237/ready
```

SHA 必须等于 Actions 摘要中的提交；服务应分别显示 `active`，就绪接口返回 `{"status":"ready"}`。这证明部署完成，不代表已经通过新的 TACC 研究任务验收。

## 6. 失败与恢复

- 校验、构建、安装依赖或配置比较失败：服务尚未停止，旧版本继续运行。
- 数据库备份失败且代码尚未切换：尝试重新启动原应用服务。
- 代码切换或数据库迁移阶段失败：保持应用服务停止，保留旧前端、前一虚拟环境及数据库备份，等待人工确认。
- API 或 Worker 就绪检查失败：Actions 显示失败；先检查迁移状态和服务日志，再恢复。前端通常仍为原版本。
- 前端发布或外网检查失败：后端可能已经更新；不自动回滚数据库或声称恢复成功。

在 ECS root 终端读取本次 `Backup:` 目录中的 `deploy.log`，并执行：

```bash
journalctl -u acs-api -u acs-runner -u acs-parser -u acs-import -u acs-mail -n 150 --no-pager
```

`previous-commit.txt` 记录原提交，`release-directory.txt` 记录新发布目录，新目录内 `previous-venv` 保留原虚拟环境。若它是被移动的实体虚拟环境，恢复时必须将其移回原来的 `backend/.venv` 路径，不能直接从备份位置启动其中的控制台脚本。

不要只运行 `git reset` 然后启动旧代码：迁移后的数据库可能与旧版本不兼容。根据实际迁移决定前滚修复或停机恢复数据库；恢复数据库会丢弃备份之后的数据，应另行确认后操作。

代码发布位于 `/home/acs/acs-deploy/auto/releases/`，上传包位于同目录下的 `incoming/`，备份位于 root 专用的 `/var/backups/acs/`。脚本不自动删除历史发布和备份；定期检查磁盘，并在确认当前虚拟环境指向与恢复需求后清理。不要删除正在使用的发布目录。

## 7. 本地验证

```bash
python -B -m unittest discover -s ops/deploy/tests -v
bash -n ops/deploy/setup-ecs.sh
bash -n ops/deploy/deploy-ecs.sh
```

Windows 可通过环境变量 `ACS_BASH` 指定 Git for Windows 的 `bash.exe`。这些检查不访问 ECS、不连接生产数据库，也不提交研究任务。
