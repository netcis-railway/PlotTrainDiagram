# 求解器日志作图扩展

人工编写的作图代码放在本目录下，按求解器建子目录。例如：

```text
solver_visualizers/
  gurobi/
    plot_gurobi_progress.py
    adapter.py
  your_solver/
    your_original_plot.py
    adapter.py
```

原脚本保留文件名。Gurobi原脚本已从项目根目录移动至`gurobi/plot_gurobi_progress.py`，原命令行入口、双参数函数调用及交互显示仍可用；新增`plot_progress(data, filename, output_path=..., show=False)`及Figure返回值支持网页。解析保留原进度线、H圆环及B&B菱形，补充负数/科学计数法/小数秒和零目标值处理。

项目根目录`solver_logs.json`与`diagram_styles.json`并列，统一登记类型识别规则及作图函数。一个求解器可注册多个plotter，由default_plotter指定默认值；添加求解器和脚本不需要修改API分发代码。

## 新增一种作图方式

1. 创建求解器子目录及`__init__.py`，放入原作图文件。
2. 写适配函数，默认名为`render`：

```python
def render(input_path, output_dir, filename, options):
    # input_path：严格按用户选择编码解码后重写为UTF-8的临时日志。
    # filename：原日志显示名称，不应作为磁盘输出路径使用。
    # output_dir：本次请求独占的临时输出目录。
    # options：作图JSON参数，当前Gurobi适配器不需要额外参数。
    image_path = output_dir / "progress.png"
    # 在这里调用原解析/绘图函数，将PNG写入image_path。
    return {"image_path": str(image_path), "summary": {"rows": 10}}
```

3. 在`solver_logs.json`的solvers加入类型识别规则，在plotters登记id、label、solver_type、module、function、source_file、timeout_seconds。例如module为`your_solver.adapter`，function为`render`，source_file为`your_solver/your_original_plot.py`。
4. 在对应solver的default_plotter填写该plotter的id。原作图函数已满足四参数适配契约时，也可直接登记原模块和函数。
5. 在后端实际Python环境安装新脚本所需依赖，并同步requirements/项目依赖。重新读取日志或点击“按当前规则重新识别”即可加载当前JSON配置。

适配器须使用无GUI绘图，返回临时目录内的PNG及可JSON序列化的summary。服务在独立Python子进程中执行，固定MPLBACKEND=Agg；不弹出服务器桌面窗口。函数标准输出转入进程诊断，不与返回协议混用。图片最多16MB，超时由配置限制为1–60秒，结束后删除临时输入/图片。原日志字节、受管源文件和时刻表不会被覆盖。

注册表只允许本目录内的模块/相对源路径。HTTP请求只接受已登记的plotter_id，不能提交Python代码、模块、函数或任意路径。不要把日志上传目录当作代码目录。
