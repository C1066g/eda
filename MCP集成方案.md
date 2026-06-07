# EDA 工具与仿真工具的 MCP 集成方案

## 概述

通过 Model Context Protocol (MCP)，你可以在 Kiro 中同时使用 KiCad 进行原理图设计和 SPICE 进行电路仿真。以下是找到的官方和社区 MCP 服务器：

## 可用的 MCP 服务器

### 1. KiCad MCP 服务器

**项目地址**: [lamaalrajih/kicad-mcp](https://github.com/lamaalrajih/kicad-mcp)

**功能特性**:
- 项目管理：列出、检查和打开 KiCad 项目
- PCB 设计分析：获取 PCB 设计和原理图的洞察
- BOM 管理：物料清单管理
- 设计规则检查 (DRC)
- 支持 macOS、Windows 和 Linux
- 需要 KiCad 9.0 或更高版本

**安装步骤**:
```bash
# 克隆仓库
git clone https://github.com/lamaalrajih/kicad-mcp.git
cd kicad-mcp

# 安装依赖（需要先安装 uv）
make install

# 创建环境配置
cp .env.example .env
# 编辑 .env 文件，添加你的 KiCad 项目路径
```

**Kiro 配置**:
在 `~/.kiro/settings/mcp.json` 中添加：
```json
{
  "mcpServers": {
    "kicad": {
      "command": "/绝对路径/kicad-mcp/.venv/bin/python",
      "args": [
        "/绝对路径/kicad-mcp/main.py"
      ],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### 2. SPICE 仿真 MCP 服务器

有多个选择：

#### 选项 A: SPICEBridge（推荐）

**项目地址**: [clanker-lover/spicebridge](https://github.com/clanker-lover/spicebridge)

**功能特性**:
- 28 个工具覆盖完整的电路设计工作流
- 11 个内置模板，自动计算元件值（E24 系列）
- 仿真类型：AC 扫描、瞬态、DC 工作点
- 测量：带宽、增益、DC 电平、瞬态指标、功率
- 蒙特卡洛和最坏情况分析
- **KiCad 导出**：可输出 `.kicad_sch` 原理图文件
- 交互式原理图查看器
- 规格验证

**安装**:
```bash
# 需要 Python 3.10+ 和 ngspice
# macOS 安装 ngspice
brew install ngspice

# 安装 SPICEBridge
pip install spicebridge
```

**Kiro 配置**:
```json
{
  "mcpServers": {
    "spicebridge": {
      "command": "spicebridge",
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

#### 选项 B: ngspice-mcp

**项目地址**: [gtnoble/ngspice-mcp](https://github.com/gtnoble/ngspice-mcp)

**功能特性**:
- 直接与 ngspice 共享库接口集成
- 加载电路网表
- 执行仿真命令（op、dc、ac、tran）
- 获取仿真数据和波形

**安装**:
```bash
git clone https://github.com/gtnoble/ngspice-mcp.git
cd ngspice-mcp
dub build --config=server
```

## 工作流程示例

### 场景 1：从 KiCad 原理图到 SPICE 仿真

1. **在 KiCad 中设计原理图**
   ```
   使用 KiCad MCP 工具：
   - 打开项目
   - 分析原理图
   - 导出网表
   ```

2. **在 SPICE 中仿真**
   ```
   使用 SPICEBridge MCP 工具：
   - 加载网表或使用模板
   - 运行 AC/瞬态/DC 分析
   - 测量关键参数
   - 验证规格
   ```

3. **迭代优化**
   ```
   - 根据仿真结果调整元件值
   - 在 KiCad 中更新原理图
   - 重新仿真验证
   ```

### 场景 2：从 SPICE 设计到 KiCad 原理图

1. **在 SPICE 中快速原型设计**
   ```
   使用 SPICEBridge：
   - 使用模板创建电路
   - 自动计算元件值
   - 仿真和优化
   - 导出 KiCad 原理图
   ```

2. **在 KiCad 中完善设计**
   ```
   使用 KiCad MCP：
   - 打开导出的原理图
   - 添加封装信息
   - 进行 PCB 布局
   ```

## 在 Kiro 中的使用示例

安装配置完成后，你可以在 Kiro 中这样使用：

```
你: "列出我所有的 KiCad 项目"
Kiro: [使用 KiCad MCP 列出项目]

你: "打开温度传感器项目，分析原理图"
Kiro: [打开项目并分析]

你: "为这个运放电路创建一个 SPICE 仿真，目标增益 20dB，带宽 10kHz"
Kiro: [使用 SPICEBridge 创建仿真]

你: "运行 AC 分析并测量带宽"
Kiro: [执行仿真并返回结果]

你: "将这个电路导出为 KiCad 原理图"
Kiro: [使用 SPICEBridge 的 export_kicad 功能]
```

## 优势

1. **无缝集成**：在同一个 AI 助手中完成设计和仿真
2. **自然语言交互**：用中文或英文描述需求，AI 自动调用工具
3. **快速迭代**：设计-仿真-优化循环更快
4. **自动化**：自动计算元件值、验证规格
5. **双向工作流**：可以从 KiCad 到 SPICE，也可以从 SPICE 到 KiCad

## 注意事项

1. **ngspice 依赖**：SPICE 仿真工具都需要安装 ngspice
2. **路径配置**：确保使用绝对路径配置 MCP 服务器
3. **版本要求**：
   - KiCad 9.0+
   - Python 3.10+
   - ngspice（最新版本）
4. **LTspice 支持**：目前没有找到 LTspice 的官方 MCP 服务器，但 ngspice 是开源替代方案，功能相似

## 下一步

1. 安装 ngspice
2. 选择并安装一个 SPICE MCP 服务器（推荐 SPICEBridge）
3. 安装 KiCad MCP 服务器
4. 在 Kiro 中配置 MCP 服务器
5. 重启 Kiro 或重新连接 MCP 服务器

## 参考资源

- [KiCad MCP 文档](https://github.com/lamaalrajih/kicad-mcp)
- [SPICEBridge 文档](https://github.com/clanker-lover/spicebridge)
- [ngspice-mcp 文档](https://github.com/gtnoble/ngspice-mcp)
- [MCP 官方文档](https://github.com/modelcontextprotocol)
- [ngspice 官网](http://ngspice.sourceforge.net/)
