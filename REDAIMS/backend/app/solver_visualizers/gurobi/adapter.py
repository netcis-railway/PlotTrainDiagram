import math

from .plot_gurobi_progress import parse_gurobi_log, plot_progress


def render(input_path, output_dir, filename, options):
    import matplotlib.pyplot as plt

    data = parse_gurobi_log(str(input_path))
    if not data["times"] and all(
        data[key] is None for key in ("root_obj", "final_obj", "final_bound")
    ):
        raise ValueError("日志中没有可绘制的Gurobi进度数据（进度表、根松弛或最终目标值）")
    numbers = [
        value
        for values in (data["times"], data["incumbents"], data["best_bounds"])
        for value in values
    ]
    numbers += [data[key] for key in ("root_obj", "final_obj", "final_bound", "total_time")]
    if any(value is not None and not math.isfinite(value) for value in numbers):
        raise ValueError("日志包含超出数值范围的进度数据")
    image = output_dir / "gurobi_progress.png"
    figure = plot_progress(data, filename, output_path=image, show=False)
    plt.close(figure)
    return {
        "image_path": str(image),
        "summary": {
            "rows": len(data["times"]),
            "heuristic_rows": data["flags"].count("H"),
            "branch_and_bound_rows": data["flags"].count("*"),
            **{key: data[key] for key in ("root_obj", "final_obj", "final_bound", "total_time")},
        },
    }
