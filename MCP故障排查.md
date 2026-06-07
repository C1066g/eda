# MCP 服务器故障排查指南

## 当前状态

✅ ngspice 已安装  
✅ KiCad MCP 服务器已安装并可以启动  
✅ SPICEBridge 已配置  
✅ MCP 配置文件已创建在正确位置  
❌ Kiro 界面中看不到 MCP 工具  

## 可能的原因

### 1. Kiro 需要完全重启
- 不是重新加载窗口，而是完全退出应用程序
- macOS: `Cmd+Q` 完全退出 Kiro
- 然后重新打开

### 2. MCP 服务器视图未打开
在 Kiro 中查找 MCP 相关的面板：
1. 打开命令面板：`Cmd+Shift+P`
2. 搜索 "MCP"
3. 查看是否有以下选项：
   - "Open MCP Server View"
   - "Reconnect MCP Servers"
   - "Show MCP Servers"

### 3. 检查 Kiro 日志
1. 打开命令面板：`Cmd+Shift+P`
2. 搜索 "Developer: Toggle Developer Tools"
3. 查看 Console 标签页，搜索 "MCP" 或 "spicebridge" 或 "kicad"
4. 查看是否有错误信息

### 4. 配置文件格式问题
虽然我们的配置看起来正确，但可以尝试简化版本：

```json
{
  "mcpServers": {
    "spicebridge": {
      "command": "uvx",
      "args": ["spicebridge"]
    }
  }
}
```

## 临时解决方案：直接使用命令行

在 MCP 工具可用之前，我们可以直接使用命令行工具：

### 方案 A：使用 ngspice 命令行

```bash
# 运行仿真
ngspice 三角波发生器.cir

# 在 ngspice 交互界面中
ngspice 1 -> run
ngspice 2 -> plot v(out1) v(out2)
ngspice 3 -> quit
```

### 方案 B：使用 SPICEBridge CLI

```bash
# 列出可用模板
uvx spicebridge --help

# 创建电路（需要编写 Python 脚本）
```

### 方案 C：我来帮你运行仿真

我可以直接使用命令行工具运行仿真并显示结果。

## 下一步行动

### 立即可以做的：

1. **完全退出并重启 Kiro**
   ```
   Cmd+Q 退出
   重新打开 Kiro
   ```

2. **查看开发者工具日志**
   ```
   Cmd+Shift+P -> "Developer: Toggle Developer Tools"
   查看 Console 中的 MCP 相关信息
   ```

3. **尝试命令面板中的 MCP 命令**
   ```
   Cmd+Shift+P -> 搜索 "MCP"
   ```

4. **让我直接运行仿真**
   ```
   我可以使用 ngspice 命令行运行三角波发生器仿真
   ```

## 验证 MCP 是否工作的方法

如果 MCP 正常工作，你应该能看到：

1. **在侧边栏**：MCP Server 视图显示 `kicad` 和 `spicebridge`
2. **在命令面板**：可以搜索到 MCP 相关命令
3. **在聊天中**：我可以直接调用 MCP 工具（你会看到工具调用）

## 联系我

告诉我：
1. 你是否完全重启了 Kiro？
2. 在命令面板中搜索 "MCP" 能看到什么？
3. 是否想让我直接用命令行运行三角波发生器仿真？
