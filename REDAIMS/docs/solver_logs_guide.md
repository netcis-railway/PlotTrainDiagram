# 求解日志类型识别与可视化

## 使用

导入日志后，系统按项目根目录`solver_logs.json`判断求解器类型，并把类型、默认作图函数、识别编码和命中依据保存为日志属性。导入窗口及日志查看页显示类型。

在run或Experiment的“求解日志”小节选择日志。当前Gurobi日志会默认调用`plot_gurobi_progress.py`，显示incumbent、best bound、根节点松弛、H启发式及B&B节点改进点，可缩放图片、下载PNG和查看摘要。Experiment中仍先选择成员run，日志和作图均属于该run。

没有命中规则或同时命中多个类型时，显示“未识别”，不猜测类型和作图函数。可手动指定求解器，也可在修改JSON后点击“按当前规则重新识别”。选错编码会明确提示，可切换UTF-8/GB18030；新选择日志时采用导入检测到的编码，回看已保存展示时保留原编码选择。

旧日志不会在启动时自动重写属性，默认“未识别”；点击重新识别即可补充。重新上传同名同内容仍返回原附件，不会覆盖用户手动设置的类型。重新识别或手动指定类型会更新默认函数，但不改原字节、ID、摘要及来源。

日志无可绘制数据、脚本不可用、依赖缺失、超时等会显示错误，原文仍可查看和下载。保存“求解日志展示”记录所选plotter_id、缩放等配置；图片在回看时由原日志重新生成，不把PNG重复写入分析节点。

## 配置位置与规则

`solver_logs.json`与根目录`diagram_styles.json`、`config.yaml`并列。修改后下次读取配置/导入/重新识别/作图即重新校验，无需重启后端；新Python依赖仍须在实际后端环境安装。

默认Gurobi规则：第1–50行（包含首尾）任一行包含“Gurobi Optimizer version”“Gurobi Optimizer”或“Gurobi version”，忽略大小写。默认函数ID为gurobi_progress，对应gurobi子目录中的原文件。

```json
{
  "id": "gurobi",
  "label": "Gurobi",
  "case_sensitive": false,
  "conditions": [
    {
      "start_line": 1,
      "end_line": 50,
      "match": "any",
      "keywords": ["Gurobi Optimizer version", "Gurobi Optimizer", "Gurobi version"]
    }
  ],
  "default_plotter": "gurobi_progress"
}
```

行号从1开始，空行也计数，范围包含首尾。keywords为字面子串，不是正则。match=any表示该范围某一行包含任一关键词；match=all表示某一行包含全部关键词。一个类型的多个conditions必须全部满足，可以分别限定不同的行或范围。多个类型同时满足时标记歧义，不按数组先后选取。配置会校验重复ID、行范围、类型和默认函数引用及源文件路径，坏配置返回明确错误，不把它当作未知类型静默导入。

## 作图代码位置

人工代码统一放在`backend/app/solver_visualizers/<求解器>/`。本次原文件位于`backend/app/solver_visualizers/gurobi/plot_gurobi_progress.py`，文件名不变，由同目录adapter.py接入网页。新增其他求解器或同一求解器的其他图形时，可建立新子目录/原脚本/适配器，并在JSON中登记；无需修改分发API。契约见[作图扩展说明](../backend/app/solver_visualizers/README.md)。

## Linux更新

在项目根目录、运行后端的同一虚拟环境中安装依赖，然后按原命令重启后端并更新前端：

```bash
.venv/bin/python -m pip install -r requirements.txt
```

requirements.txt与pyproject.toml已同步包含Matplotlib及DuckDB读取带时区结果所需的pytz，无需再应用旧依赖补丁。安装依赖后重启实际运行的后端进程。
