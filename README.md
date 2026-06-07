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

**推荐：GitHub Actions 部署**（已配置 `.github/workflows/deploy-pages.yml`）

1. 打开 [Settings → Actions → General](https://github.com/C1066g/eda/settings/actions)
   - **Workflow permissions** → 选 **Read and write permissions** → Save
2. 打开 [Settings → Pages](https://github.com/C1066g/eda/settings/pages)
   - **Build and deployment → Source** → 选 **GitHub Actions**（不是 Deploy from branch）
3. 打开 [Actions](https://github.com/C1066g/eda/actions) 标签，等 `Deploy to GitHub Pages` 跑绿
4. 访问：**https://c1066g.github.io/eda/**

> 其他仓库开 Pages **不会**占用本项目地址。只有 `C1066g.github.io` 这个仓库名才是用户主页，与 `eda` 项目页互不冲突。

## EDA

- KiCad 示例：`kicad_rc_lowpass/`（1 kHz RC 低通）
- SPICE 网表：根目录 `*.cir`
- Cursor 分屏工作流：`.cursor/rules/eda-split-workflow.mdc`
