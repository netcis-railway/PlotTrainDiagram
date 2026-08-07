# 列车运行图绘制系统

基于 MATLAB 的列车运行图自动绘制工具，支持 v3→v3f 格式转换、基本图与调度图对比等功能。

---

## 目录结构

```
public/
├── DrawTrainDigramFunctionV3f/    # 函数库与工具（主要工作区）
│   ├── DrawTrainDigramFunctionV3f.m   # 核心绘图函数库
│   ├── DrawV3f.m                      # 原始单时刻表绘图脚本
│   ├── ConvertV3toV3f.m               # 独立 v3→v3f 格式转换脚本
│   ├── test_DrawLineDigramBasevsRescheduled.m  # 对比画图测试脚本
│   └── Train TimeTable final data Metro (version 3).xlsx  # 示例数据
│
└── 画图新版V3F/                    # 参考实现（新版函数库 + 多种画图脚本）
    ├── DrawTrainDigramFunction_v3f_v5.m  # 新版函数库（功能更全）
    ├── DrawCompare_v3f.m                 # 计划/实际对比图（参考）
    ├── AddSeqV3f.m                       # 批量格式转换（参考）
    └── ...各种测试数据与脚本
```

---

## 新增功能

### 1. 基本图与调度图对比绘制

**函数**: `DrawLineDigramBasevsRescheduled`

位于 `DrawTrainDigramFunctionV3f.m`，在同一张运行图上对比绘制基本计划（黑色）和调度计划（红/蓝）。

```matlab
% 函数签名
[StationPosition] = DrawLineDigramBasevsRescheduled( ...
    RAW_base, trainNum_base, ...   % 基本计划 v3f 数据
    RAW_res,  trainNum_res, ...    % 调度计划 v3f 数据
    stationNum, LineID)            % 车站数, 线路号
```

**使用流程**（参考 `test_DrawLineDigramBasevsRescheduled.m`）:

```matlab
% 1. 加载函数库
DrawTrainDigram = DrawTrainDigramFunctionV3f;

% 2. 读取 v3 文件并转换为 v3f（在内存中完成，不需要写文件）
[~, ~, RAW_v3_plan] = xlsread('plan.xlsx');
RAW_plan = ConvertV3toV3f_core(RAW_v3_plan);  % 转换函数见测试脚本

[~, ~, RAW_v3_res] = xlsread('reschedule.xlsx');
RAW_res = ConvertV3toV3f_core(RAW_v3_res);

% 3. 计算数据维度
stationNum = size(RAW_plan, 1) - 1;
trainNum_plan = (size(RAW_plan, 2) - 5) / 4;
trainNum_res  = (size(RAW_res, 2) - 5) / 4;

% 4. 调用对比画图
DrawTrainDigram.DrawLineDigramBasevsRescheduled( ...
    RAW_plan, trainNum_plan, ...
    RAW_res, trainNum_res, ...
    stationNum, '');
```

| 参数 | 说明 |
|---|---|
| `RAW_base` | 基本计划时刻表（v3f 格式 cell 数组） |
| `trainNum_base` | 基本图列车数 |
| `RAW_res` | 调度计划时刻表（v3f 格式 cell 数组） |
| `trainNum_res` | 调度图列车数 |
| `stationNum` | 车站数量 |
| `LineID` | 线路号，`''` 表示全线，`1` 表示线路 1 |

| 返回值 | 说明 |
|---|---|
| `StationPosition` | 各站在 Y 轴上的坐标位置 |

---

### 2. 独立 V3→V3f 格式转换

**脚本**: `ConvertV3toV3f.m`

不依赖任何函数库的独立脚本，将 v3 格式时刻表（每车 3 列：`_A/_D/_G`）转换为 v3f 格式（每车 4 列，新增 `_SEQ` 列）。

```matlab
% 直接运行
run('ConvertV3toV3f');
```

包含两个局部函数：
- `convertV3toV3f_core(RAW_v3)` — 核心转换逻辑
- `rawToDateTime(RAW)` — 时间值转 datetime 格式（用于输出可读 Excel）

---

## 数据格式说明

### v3 格式（旧）

```
| NODE_ID | NODE_CODE | NODE_NAME | 车1_A | 车1_D | 车1_G | 车2_A | 车2_D | 车2_G | ... |
```

- 前 3 列为车站基础信息
- 每辆车占 **3 列**：到达时间 (`_A`)、发车时间 (`_D`)、股道 (`_G`)
- 无 SEQ（停站顺序）列

### v3f 格式（新）

```
| NODE_NAME_SHORT | NODE_ID | NODE_CODE | LINE_IND | NODE_NAME | 车1_A | 车1_D | 车1_G | 车1_SEQ | ... |
```

- 前 5 列为车站基础信息
- 每辆车占 **4 列**：到达、发车、股道、**停站顺序（SEQ）**
- SEQ 列按到发时间升序编号（发车 = 序号 + 0.1）

---

## 函数库参考

`DrawTrainDigramFunctionV3f` 返回一个结构体，包含以下函数句柄：

| 函数 | 功能 |
|---|---|
| `ReadTrainSchedule` | 读取 v3f 格式 Excel 时刻表 |
| `GetTrainTimeSegment` | 获取全表最早/最晚时间 |
| `JudgeUpOrDown` | 判断每列车上下行（1=下行, 2=上行） |
| `GetStationInterval` | 计算区间最小运行时间（Y 轴间距） |
| `DrawBackground` | 绘制背景网格与坐标轴 |
| `DrawDigram` | 绘制列车运行线（下行红/上行蓝） |
| `DrawLineDigram` | 按线路号筛选绘制运行线，支持自定义颜色 |
| `MarkTrainNumber` | 在图上标注列车车次号 |
| **`DrawLineDigramBasevsRescheduled`** | **新增：基本图与调度图对比绘制** |

---

## 配色规则

| 画图模式 | 基本图 | 调度图 | 车次号 |
|---|---|---|---|
| 单时刻表 | 红（下行）/ 蓝（上行） | — | 黑色 |
| 对比图 | **黑色** | 红（下行）/ 蓝（上行） | 黑色 |

---

## 版本历史

- **2026-01-25**: 初始版本，基础绘图功能
- **2026-03**: 新增按线路号筛选、SEQ 排序
- **2026-04**: 新增 v3→v3f 自动转换、车次高亮
- **2026-06**: 新增对比绘图、批量转换工具
- **2026-08**: 完善 `DrawLineDigramBasevsRescheduled` 对比画图函数；新增独立 `ConvertV3toV3f` 脚本；修复空 LineID 处理
