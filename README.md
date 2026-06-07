# eda

个人 EDA 工作区 + 通信网络技术复习工具。

## 通信网络技术复习（网页）

| 入口 | 文件 |
|------|------|
| 考试中心 | [通信网络技术_考试中心.html](通信网络技术_考试中心.html) |
| 分类刷题 | [通信网络技术_分类复习.html](通信网络技术_分类复习.html) |
| 题库模考 | [通信网络技术_题库模考.html](通信网络技术_题库模考.html) |
| 第4章公式 | [通信网络技术_第4章公式速查.html](通信网络技术_第4章公式速查.html) |

### 本地分享给同 WiFi / 热点

```bash
./启动复习服务器.sh
# 其他设备打开 http://<本机IP>:8765/通信网络技术_考试中心.html
```

### GitHub Pages（在线访问）

仓库 Settings → Pages → Source: **Deploy from branch** → Branch: `main` / folder: `/ (root)`  
访问地址：`https://c1066g.github.io/eda/通信网络技术_考试中心.html`

## EDA

- KiCad 示例：`kicad_rc_lowpass/`（1 kHz RC 低通）
- SPICE 网表：根目录 `*.cir`
- Cursor 分屏工作流：`.cursor/rules/eda-split-workflow.mdc`
