# MCP 工具测试指南

## 配置状态

✅ ngspice 已安装  
✅ KiCad MCP 服务器已配置  
✅ SPICEBridge MCP 服务器已配置  
✅ MCP 配置文件已创建  

## 如何验证 MCP 工具是否可用

### 方法 1：查看 Kiro 界面
1. 在 Kiro 侧边栏找到 "MCP Server" 或 "Powers" 面板
2. 应该能看到 `kicad` 和 `spicebridge` 两个服务器
3. 状态应该显示为 "已连接" 或 "运行中"

### 方法 2：直接测试功能

尝试以下命令来测试 MCP 工具：

#### 测试 SPICEBridge

**创建一个简单的 RC 低通滤波器：**
```
请使用 SPICEBridge 创建一个 RC 低通滤波器，截止频率 1kHz
```

**列出可用的电路模板：**
```
列出 SPICEBridge 中所有可用的电路模板
```

**创建并仿真一个运放电路：**
```
使用 SPICEBridge 创建一个非反相放大器，增益为 10 倍，然后运行 AC 分析
```

#### 测试 KiCad MCP

**列出 KiCad 项目：**
```
列出我所有的 KiCad 项目
```

**打开特定项目：**
```
打开我的 [项目名称] KiCad 项目
```

## SPICEBridge 可用功能

### 创建和配置
- `create_circuit` - 存储 SPICE 网表
- `load_template` - 加载模板并自动计算元件值
- `calculate_components` - 根据目标规格计算元件值
- `modify_component` - 修改元件值
- `list_templates` - 列出可用模板

### 仿真
- `run_ac_analysis` - AC 频率扫描
- `run_transient` - 瞬态（时域）分析
- `run_dc_op` - DC 工作点分析

### 测量
- `measure_bandwidth` - 测量 -3dB 带宽
- `measure_gain` - 测量增益
- `measure_dc` - 提取 DC 工作点值
- `measure_transient` - 测量时域特性
- `measure_power` - 计算功耗

### 导出和可视化
- `draw_schematic` - 生成原理图（PNG/SVG）
- `export_kicad` - 导出为 KiCad 8 原理图（.kicad_sch）
- `compare_specs` - 验证规格
- `open_viewer` - 打开交互式网页查看器

### 高级分析
- `run_monte_carlo` - 蒙特卡洛分析
- `run_worst_case` - 最坏情况分析
- `auto_design` - 全自动设计循环

## KiCad MCP 可用功能

- 项目管理：列出、检查和打开 KiCad 项目
- PCB 设计分析：获取设计洞察
- BOM 管理：物料清单管理
- 设计规则检查（DRC）

## 完整工作流示例

### 示例 1：从零开始设计滤波器

1. **创建电路**
   ```
   使用 SPICEBridge 的 rc_lowpass_1st 模板创建一个截止频率为 1kHz 的低通滤波器
   ```

2. **运行仿真**
   ```
   对这个电路运行 AC 分析，频率范围从 1Hz 到 100kHz
   ```

3. **测量性能**
   ```
   测量这个电路的 -3dB 带宽和增益
   ```

4. **导出原理图**
   ```
   将这个电路导出为 KiCad 原理图文件
   ```

5. **在 KiCad 中打开**
   ```
   在 KiCad 中打开刚才导出的原理图
   ```

### 示例 2：优化现有设计

1. **加载电路**
   ```
   创建一个运放非反相放大器，目标增益 20dB
   ```

2. **仿真和测量**
   ```
   运行 AC 分析并测量实际增益
   ```

3. **调整参数**
   ```
   如果增益不符合要求，调整反馈电阻值
   ```

4. **验证规格**
   ```
   验证电路是否满足增益 20dB ±5% 的规格
   ```

## 故障排除

### 如果 MCP 工具不可用

1. **检查配置文件**
   ```bash
   cat ~/.kiro/settings/mcp.json
   ```

2. **手动测试服务器**
   ```bash
   # 测试 SPICEBridge
   uvx spicebridge --help
   
   # 测试 KiCad MCP
   /Users/mac/mcp-servers/kicad-mcp/.venv/bin/python /Users/mac/mcp-servers/kicad-mcp/main.py --help
   ```

3. **检查 ngspice**
   ```bash
   which ngspice
   ngspice --version
   ```

4. **重新连接 MCP 服务器**
   - 在 Kiro 侧边栏找到 MCP Server 视图
   - 点击重新连接按钮

### 常见问题

**Q: 提示找不到 ngspice**  
A: 运行 `brew install ngspice`

**Q: KiCad MCP 无法启动**  
A: 检查 Python 虚拟环境是否正确创建：
```bash
ls -la /Users/mac/mcp-servers/kicad-mcp/.venv/
```

**Q: SPICEBridge 下载很慢**  
A: 首次运行 uvx 会下载依赖，这是正常的，只需要一次

## 下一步

现在你可以：
1. 尝试上面的测试命令
2. 创建自己的电路设计
3. 将 SPICE 仿真结果导出到 KiCad
4. 在 KiCad 中完成 PCB 布局

祝你使用愉快！🎉
