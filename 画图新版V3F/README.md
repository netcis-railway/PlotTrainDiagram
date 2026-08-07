# 京沪线列车运行图绘制系统 V3F

基于 MATLAB 的列车运行图自动绘制工具，支持 v3→v3f 格式转换、计划图与实际图对比等功能。

---

## 快速开始

在终端中进入本文件夹，执行：

```bash
matlab -batch "RunAll"
```

一键完成格式转换 + 三张运行图输出。修改 `RunAll.m` 顶部两行即可切换数据源：

```matlab
planFile   = 'plan_TT0 .xlsx';       % 计划时刻表
actualFile = 'reschedule_TT0.xlsx';  % 实际时刻表
```

---

## 文件清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `RunAll.m` | **一键脚本** | 格式转换 + 三张图全流程 |
| `DrawPlanOnly_v3f.m` | 单独画图 | 仅计划时刻表（蓝线） |
| `DrawActualOnly_v3f.m` | 单独画图 | 仅实际时刻表（红线） |
| `DrawCompare_v3f.m` | 单独画图 | 计划+实际对比图（蓝+红） |
| `DrawV3f_v5.m` | 旧版画图 | 原始单时刻表绘图 |
| `AddSeqV3f.m` | 工具 | 批量 v3 → v3f 转换 |
| `DrawTrainDigramFunction_v3f_v5.m` | 函数库 | 核心绘图函数（不需要直接运行） |

---

## 终端运行命令

> 前提：MATLAB 已加入系统 PATH。若未加入，将 `matlab` 替换为完整路径如 `"C:\Program Files\MATLAB\R2024a\bin\matlab.exe"`

### 一键运行（推荐）

```bash
matlab -batch "RunAll"
```

输出 5 个文件：`plan_TT0_v3f.xlsx`、`actual_v3f.xlsx`、`01_plan.png`、`02_actual.png`、`03_compare.png`

### 单独画图

```bash
matlab -batch "DrawPlanOnly_v3f"     # 仅计划运行图（蓝色）
matlab -batch "DrawActualOnly_v3f"   # 仅实际运行图（红色）
matlab -batch "DrawCompare_v3f"      # 对比运行图（蓝+红）
matlab -batch "DrawV3f_v5"           # 原始版单图
```

### 格式转换

```bash
matlab -batch "AddSeqV3f"            # v3 → v3f 批量转换
```

---

## 数据格式

### v3 格式（旧）

```
| NODE_ID | NODE_CODE | NODE_NAME | 车1_A | 车1_D | 车1_G | 车2_A | 车2_D | 车2_G | ... |
```

- 每辆车占 **3 列**：到达时间（`_A`）、发车时间（`_D`）、股道（`_G`）
- 无 SEQ（停站顺序）列，无 LINE_IND（线路归属）列

### v3f 格式（新）

```
| NODE_NAME_SHORT | NODE_ID | NODE_CODE | LINE_IND | NODE_NAME | 车1_A | 车1_D | 车1_G | 车1_SEQ | ... |
```

- 前 5 列为车站基础信息
- 每辆车占 **4 列**：到达、发车、股道、**停站顺序（SEQ）**
- SEQ 列按到发时间升序编号（发车 = 序号 + 0.1）

---

## 函数库参考

`DrawTrainDigramFunction_v3f_v5` 返回一个结构体，包含以下函数句柄：

| 函数名 | 功能 | 主要输出 |
|---|---|---|
| `ConvertV3toV3f` | v3 → v3f 格式转换（自动生成 SEQ） | RAW_v3f |
| `GetTrainTimeSegment` | 获取全表最早/最晚时间 | startHour, endHour |
| `JudgeUpOrDown` | 判断每辆车上下行 | DirectionSign（1=下行, 2=上行） |
| `GetStationInterval` | 计算区间最小运行时间（Y 轴间距） | minTravelTime |
| `DrawBackground` | 绘制背景网格与坐标轴 | StationPosition |
| `DrawLineDigram` | 绘制运行线（下行红/上行蓝） | LineHandle, trainName |
| `DrawLineDigramColor` | 绘制运行线（指定颜色） | LineHandle, trainName |
| `MarkTrainNumber` | 标注车次号（默认黑） | — |
| `MarkTrainNumberColor` | 标注车次号（指定颜色） | — |
| `HighlightTrainLines` | 高亮指定车次（黑色加粗） | — |
| `RAWtoDateTime` | Excel 序列值 → datetime | RAW_date |
| `RebuildV3fByScope` | 按时间+车站区间筛选重构 | 重构后 v3f |

---

## 配色规则

| 脚本 | 计划线 | 实际线 | 车次号 |
|---|---|---|---|
| `DrawPlanOnly_v3f` | 🔵 蓝色 | — | ⚫ 黑色 |
| `DrawActualOnly_v3f` | — | 🔴 红色 | ⚫ 黑色 |
| `DrawCompare_v3f` | 🔵 蓝色 | 🔴 红色 | ⚫ 黑色 |

---

## 版本历史

- **2026-01-25**: 初始版本，基础绘图功能
- **2026-03-11**: 调整上下行逻辑，修复错误，增加异常处理
- **2026-03-12**: 新增按线路号筛选，修复车次号悬空问题
- **2026-03-13**: Y 轴仅显示有效车站，固定红蓝配色，SEQ 排序
- **2026-04-03**: 适配 `_A`/`_a` 后缀，新增车次高亮、v3→v3f 自动转换
- **2026-06-15**: 新增对比绘图、颜色参数版函数、批量转换工具
- **2026-06-16**: 新增 `RunAll` 一键脚本、`DrawPlanOnly_v3f`、`DrawActualOnly_v3f`，去掉图例和标题
