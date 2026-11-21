# Cloudflare Tunnel PDF 探测

验证 TACC CPU 作业能否经公网 HTTPS 下载本机后端提供的 PDF，并用 PyMuPDF 解析正文。本机的 `/paper.pdf` 接口读取本目录的 [测试 PDF](paper.pdf)。提交目录只包含作业脚本、配置、URL 和 PDF 校验值。

## 复跑

本机需要 Python 3、`cloudflared` 和已配置的 `tcloud`。作业使用现有的 `acs-network-probe` 环境，其他账号可在提交前把配置改为自己可用的 Python 3.10+ 环境。以下命令从仓库根目录执行。

1. 在一个终端运行本地后端。

   ```sh
   python3 tacc/tunnel-probe/origin.py
   ```

2. 在另一个终端开启 [Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)，记录它打印的 HTTPS 地址。两个进程需要保持在线，直到 TACC 作业下载完成。

   ```sh
   cloudflared tunnel --protocol http2 --url http://127.0.0.1:8765
   ```

3. 在第三个终端填入隧道地址，并准备一个独立的作业提交目录。

   ```sh
   TUNNEL_URL='https://YOUR_HOST.trycloudflare.com' # 换成步骤 2 的地址
   probe_dir=$(mktemp -d "${TMPDIR:-/tmp}/acs-pdf-tunnel-probe-XXXXXX")
   cp tacc/tunnel-probe/job.sh tacc/tunnel-probe/main.py tacc/tunnel-probe/tuxiv.conf "$probe_dir/"
   python3 - "$TUNNEL_URL" "$probe_dir" <<'PY'
   import hashlib
   import json
   import sys
   from pathlib import Path

   pdf = Path("tacc/tunnel-probe/paper.pdf").read_bytes()
   target = {"url": sys.argv[1].rstrip("/") + "/paper.pdf", "sha256": hashlib.sha256(pdf).hexdigest()}
   (Path(sys.argv[2]) / "target.json").write_text(json.dumps(target) + "\n")
   PY
   ```

   若使用其他 TACC 环境，先改 `$probe_dir/tuxiv.conf`。确认公网下载的 PDF 和原文件一致后提交。

   ```sh
   (set -o pipefail; curl -fsS "${TUNNEL_URL%/}/paper.pdf" | cmp tacc/tunnel-probe/paper.pdf -) &&
     (cd "$probe_dir" && tcloud submit)
   ```

   公网地址如果一直无法完成 TLS 握手，可以重开 Quick Tunnel，用新地址重新执行本步骤。

4. 将 `JOBID` 替换为提交返回的编号。检查报告的 `status` 为 `pass`，并在本机后端终端核对 `Origin served ... for TACC job JOBID`。完成后用 Ctrl+C 停止 Tunnel 和本地后端。

   ```sh
   JOBID=12345
   tcloud ps -j "$JOBID"
   tcloud cat "slurm_log/pdf-tunnel-probe-$JOBID.log"
   mkdir -p tacc/runs
   tcloud download "api-probe/runs/tunnel-probe-$JOBID.json" "tacc/runs/tunnel-probe-$JOBID.json"
   ```

## 实测

2026-11-19，初次探测 `29947` 通过。使用本目录独立复跑的 CPU 作业 `29958` 返回 HTTP 200 和 1,151 字节的 `application/pdf`，SHA-256 与本地文件一致，成功解析 1 页正文。本机后端日志记录了作业 `29958` 的请求。复跑报告位于 `tacc/runs/tunnel-probe-29958.json`。
