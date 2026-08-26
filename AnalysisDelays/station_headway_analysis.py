#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
车站到发间隔统计分析工具 V2
功能：
  从宽格式时刻表CSV中提取指定车站的到发时刻，计算到达间隔和出发间隔，
  按指定时间分辨率（默认1小时）分桶统计。
  图表4面板：
    1.列车到发瀑布时序图
    2.最大到达间隔 vs 最大出发间隔
    3.最小到达间隔 vs 最小出发间隔
    4.平均到达间隔 vs 平均出发间隔
用法：
  python station_interval_analysis.py <csv_file> --station 徐州东 [--start 6:00] [--end 20:00] [--resolution 1]
参数：
  csv_file       时刻表CSV文件路径
  --station      车站名称（如 徐州东），必填
  --start        统计起始时间 HH:MM，默认全部
  --end          统计结束时间 HH:MM，默认全部
  --resolution   时间分辨率（小时），默认1
  --direction    方向筛选：down(下行)/up(上行)/all，默认all
  --output-dir   输出目录，默认当前目录
"""
import argparse
import re
import sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 中文字体设置
plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def parse_time(t):
    """将 'H:MM' 或 'HH:MM' 字符串转为分钟数（int），无效返回 NaN"""
    if pd.isna(t):
        return np.nan
    s = str(t).strip()
    if not s or s.lower() == "nan":
        return np.nan
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        return np.nan
    return int(m.group(1)) * 60 + int(m.group(2))


def fmt_time(minutes):
    """分钟数转 'H:MM' 字符串"""
    if pd.isna(minutes):
        return ""
    h = int(minutes) // 60
    m = int(minutes) % 60
    return f"{h}:{m:02d}"


def extract_station_timetable(df, station_name):
    """
    从宽格式时刻表中提取指定车站的所有列车到发时刻。
    返回 DataFrame，列：train, arrival_min, departure_min, dwell_min, direction
    """
    # 找到目标站行
    station_mask = df["NODE_NAME"].str.strip() == station_name
    if not station_mask.any():
        # 尝试模糊匹配
        station_mask = df["NODE_NAME"].str.contains(station_name, na=False)
    if not station_mask.any():
        raise ValueError(f"车站 '{station_name}' 未在时刻表中找到")
    station_row = df[station_mask].iloc[0]
    station_idx = df[station_mask].index[0]
    # 提取所有列车列
    train_cols = [c for c in df.columns if c.endswith("_A")]
    trains = [c[:-2] for c in train_cols]  # 去掉 '_A'
    records = []
    for t in trains:
        a_val = station_row.get(f"{t}_A")
        d_val = station_row.get(f"{t}_D")
        seq_val = station_row.get(f"{t}__SEQ")
        a_min = parse_time(a_val)
        d_min = parse_time(d_val)
        if pd.isna(a_min) and pd.isna(d_min):
            continue  # 该列车不停此站
        # 通过SEQ判断方向：检查此站前后站的SEQ变化
        direction = infer_direction(df, t, station_idx)
        dwell = d_min - a_min if (pd.notna(a_min) and pd.notna(d_min)) else np.nan
        records.append({
            "train": t,
            "arrival": a_min,
            "departure": d_min,
            "dwell": dwell,
            "direction": direction,
            "seq": seq_val,
        })
    result = pd.DataFrame(records)
    # 按到达时间排序（无到达时间的按出发时间排）
    result["sort_key"] = result["arrival"].fillna(result["departure"])
    result = result.sort_values("sort_key").reset_index(drop=True)
    result = result.drop(columns=["sort_key"])
    return result


def infer_direction(df, train, station_idx):
    """
    根据SEQ列判断列车在该站的运行方向。
    下行(down): SEQ从北向南递增（北京南→上海虹桥方向）
    上行(up):   SEQ从南向北递增
    """
    seq_col = f"{train}__SEQ"
    if seq_col not in df.columns:
        return "unknown"
    # 找此站前后有SEQ的站
    seq_values = df[seq_col]
    current_seq = seq_values.iloc[station_idx]
    if pd.isna(current_seq):
        return "unknown"
    # 向前找最近的有SEQ的站
    prev_seq = np.nan
    for i in range(station_idx - 1, -1, -1):
        if pd.notna(seq_values.iloc[i]):
            prev_seq = seq_values.iloc[i]
            break
    # 向后找最近的有SEQ的站
    next_seq = np.nan
    for i in range(station_idx + 1, len(df)):
        if pd.notna(seq_values.iloc[i]):
            next_seq = seq_values.iloc[i]
            break
    # 判断方向
    if pd.notna(prev_seq) and pd.notna(next_seq):
        if prev_seq < current_seq < next_seq:
            return "down"  # SEQ递增 = 南行/下行
        elif prev_seq > current_seq > next_seq:
            return "up"    # SEQ递减 = 北行/上行
    elif pd.notna(prev_seq) and pd.isna(next_seq):
        # 此站是终点站
        return "down" if prev_seq < current_seq else "up"
    elif pd.isna(prev_seq) and pd.notna(next_seq):
        # 此站是始发站
        return "down" if current_seq < next_seq else "up"
    return "unknown"


def compute_intervals(timetable_df):
    """
    计算相邻列车的到达间隔和出发间隔（分钟）。
    - 到达间隔：按到达时间排序后，相邻到达的差值（非负）
    - 出发间隔：按出发时间排序后，相邻出发的差值（非负）
    同时保留按到达顺序的出发间隔（arr_order_dep_interval），
    负值表示存在越行（后到先发）。
    """
    df = timetable_df.copy()
    # 按到达时间排序 → 到达间隔
    df = df.sort_values("arrival").reset_index(drop=True)
    df["arr_interval"] = df["arrival"].diff()
    # 按到达顺序的出发间隔（可能为负，表示越行）
    df["arr_order_dep_interval"] = df["departure"].diff()
    # 按出发时间排序 → 出发间隔（非负）
    df_dep_sorted = df.sort_values("departure").reset_index(drop=True)
    df_dep_sorted["dep_interval"] = df_dep_sorted["departure"].diff()
    # 将 dep_interval 映射回原 DataFrame（按 train 匹配）
    dep_interval_map = dict(zip(df_dep_sorted["train"], df_dep_sorted["dep_interval"]))
    df["dep_interval"] = df["train"].map(dep_interval_map)
    # 标记越行：按到达顺序的出发间隔为负
    df["overtake"] = df["arr_order_dep_interval"] < 0
    return df


def bin_analysis(df, start_min=None, end_min=None, resolution_hours=1.0):
    """
    按时间分辨率分桶统计每个桶内的到达间隔和出发间隔。
    每个桶统计：
      - 列车数
      - 最大到达间隔
      - 最小到达间隔
      - 平均到达间隔
      - 最大出发间隔
      - 最小出发间隔
      - 平均出发间隔
      - 是否满足 最大到达间隔 > 最小出发间隔
    """
    res_min = int(resolution_hours * 60)
    # 确定时间范围
    all_times = pd.concat([df["arrival"], df["departure"]]).dropna()
    if all_times.empty:
        raise ValueError("没有有效的到发时间数据")
    if start_min is None:
        start_min = int(np.floor(all_times.min() / res_min) * res_min)
    if end_min is None:
        end_min = int(np.ceil(all_times.max() / res_min) * res_min)
    bins = list(range(start_min, end_min + res_min, res_min))
    bin_labels = [f"{fmt_time(b)}-{fmt_time(b + res_min)}" for b in bins[:-1]]
    records = []
    for i in range(len(bins) - 1):
        b_start = bins[i]
        b_end = bins[i + 1]
        # 到达间隔：到达时间在 [b_start, b_end) 内的列车
        arr_mask = (df["arrival"] >= b_start) & (df["arrival"] < b_end)
        arr_in_bin = df[arr_mask]
        # 出发间隔：出发时间在 [b_start, b_end) 内的列车（按出发时间排序的间隔）
        dep_mask = (df["departure"] >= b_start) & (df["departure"] < b_end)
        dep_in_bin = df[dep_mask]

        arr_intervals = arr_in_bin["arr_interval"].dropna()
        dep_intervals = dep_in_bin["dep_interval"].dropna()

        n_trains = len(arr_in_bin)
        n_overtakes = int(arr_in_bin["overtake"].sum()) if "overtake" in arr_in_bin.columns else 0

        max_arr = arr_intervals.max() if len(arr_intervals) > 0 else np.nan
        min_arr = arr_intervals.min() if len(arr_intervals) > 0 else np.nan
        mean_arr = arr_intervals.mean() if len(arr_intervals) > 0 else np.nan

        max_dep = dep_intervals.max() if len(dep_intervals) > 0 else np.nan
        min_dep = dep_intervals.min() if len(dep_intervals) > 0 else np.nan
        mean_dep = dep_intervals.mean() if len(dep_intervals) > 0 else np.nan

        # 判定：最大到达间隔 > 最小出发间隔
        arr_gt_dep = (
            pd.notna(max_arr) and pd.notna(min_dep) and max_arr > min_dep
        )
        records.append({
            "time_bin": bin_labels[i],
            "bin_start": fmt_time(b_start),
            "bin_end": fmt_time(b_end),
            "n_trains": n_trains,
            "n_overtakes": n_overtakes,
            "max_arrival_interval_min": round(max_arr, 1) if pd.notna(max_arr) else "",
            "min_arrival_interval_min": round(min_arr, 1) if pd.notna(min_arr) else "",
            "mean_arrival_interval_min": round(mean_arr, 1) if pd.notna(mean_arr) else "",
            "max_departure_interval_min": round(max_dep, 1) if pd.notna(max_dep) else "",
            "min_departure_interval_min": round(min_dep, 1) if pd.notna(min_dep) else "",
            "mean_departure_interval_min": round(mean_dep, 1) if pd.notna(mean_dep) else "",
            "arrival_gt_departure": "YES" if arr_gt_dep else "NO",
        })
    return pd.DataFrame(records), bins


def plot_results(timetable_df, bin_df, bins, station_name, direction, output_dir):
    """
    V2新版绘图：4张子图
    子图1：列车到发瀑布时序图
    子图2：每小时最大到达间隔 vs 最大出发间隔
    子图3：每小时最小到达间隔 vs 最小出发间隔
    子图4：每小时平均到达间隔 vs 平均出发间隔
    """
    fig, axes = plt.subplots(4, 1, figsize=(13, 15), dpi=120)
    ax0, ax1, ax2, ax3 = axes
    fig.suptitle(f"{station_name} 站 {direction} 方向 到发间隔统计", fontsize=14, weight="bold")

    # ----------子图0：瀑布时序图----------
    df_sorted = timetable_df.dropna(subset=["arrival"]).sort_values("arrival").reset_index(drop=True)
    x_idx = np.arange(len(df_sorted))
    arr_mins = df_sorted["arrival"].values
    dep_mins = df_sorted["departure"].values
    dwell_height = dep_mins - arr_mins

    ax0.bar(x_idx, dwell_height, bottom=arr_mins, width=0.4, color="#88aadd", label="站内停留时长")
    ax0.scatter(x_idx, arr_mins, c="#2e7d32", s=30, label="到达时刻", zorder=5)
    ax0.scatter(x_idx, dep_mins, c="#d32f2f", s=30, label="出发时刻", zorder=5)
    ax0.set_title("列车到发时序瀑布图")
    ax0.set_ylabel("当日分钟数")
    ax0.set_xticks(x_idx)
    ax0.set_xticklabels(df_sorted["train"], rotation=90, fontsize=6.5)
    ax0.legend(loc="upper left")
    ax0.grid(alpha=0.3)

    # ----------准备柱状绘图数据----------
    x_pos = np.arange(len(bin_df))
    width = 0.35

    def safe_float(val):
        if val == "" or pd.isna(val):
            return 0.0
        return float(val)

    max_arr = [safe_float(v) for v in bin_df["max_arrival_interval_min"]]
    max_dep = [safe_float(v) for v in bin_df["max_departure_interval_min"]]
    min_arr = [safe_float(v) for v in bin_df["min_arrival_interval_min"]]
    min_dep = [safe_float(v) for v in bin_df["min_departure_interval_min"]]
    avg_arr = [safe_float(v) for v in bin_df["mean_arrival_interval_min"]]
    avg_dep = [safe_float(v) for v in bin_df["mean_departure_interval_min"]]
    xtick_labels = bin_df["time_bin"].values

    # ----------子图1：最大到达间隔 vs 最大出发间隔----------
    ax1.bar(x_pos - width/2, max_arr, width, label="最大到达间隔", color="#2E86AB")
    ax1.bar(x_pos + width/2, max_dep, width, label="最大出发间隔", color="#A23B72")
    ax1.set_title("每小时：最大到达间隔 VS 最大出发间隔（单位：min）")
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
    ax1.legend()
    ax1.grid(axis="y", alpha=0.3)

    # ----------子图2：最小到达间隔 vs 最小出发间隔----------
    ax2.bar(x_pos - width/2, min_arr, width, label="最小到达间隔", color="#F18F01")
    ax2.bar(x_pos + width/2, min_dep, width, label="最小出发间隔", color="#C73E1D")
    ax2.set_title("每小时：最小到达间隔 VS 最小出发间隔（单位：min）")
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
    ax2.legend()
    ax2.grid(axis="y", alpha=0.3)

    # ----------子图3：平均到达间隔 vs 平均出发间隔----------
    ax3.bar(x_pos - width/2, avg_arr, width, label="平均到达间隔", color="#38b000")
    ax3.bar(x_pos + width/2, avg_dep, width, label="平均出发间隔", color="#0077b6")
    ax3.set_title("每小时：平均到达间隔 VS 平均出发间隔（单位：min）")
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(xtick_labels, rotation=30, ha="right", fontsize=8)
    ax3.legend()
    ax3.grid(axis="y", alpha=0.3)

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    out_path = Path(output_dir) / f"{station_name}_{direction}_interval_4panel.png"
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"4面板图表已保存: {out_path}")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="车站到发间隔统计分析工具 V2")
    parser.add_argument("csv_file", help="时刻表CSV文件路径")
    parser.add_argument("--station", required=True, help="车站名称（如 徐州东）")
    parser.add_argument("--start", default=None, help="统计起始时间 HH:MM，默认全部")
    parser.add_argument("--end", default=None, help="统计结束时间 HH:MM，默认全部")
    parser.add_argument("--resolution", type=float, default=1.0, help="时间分辨率（小时），默认1")
    parser.add_argument("--direction", default="all", choices=["down", "up", "all"],
                        help="方向筛选：down(下行)/up(上行)/all，默认all")
    parser.add_argument("--output-dir", default=".", help="输出目录，默认当前目录")
    args = parser.parse_args()

    # 读取CSV
    df = pd.read_csv(args.csv_file)
    print(f"时刻表: {len(df)} 站, {len([c for c in df.columns if c.endswith('_A')])} 列列车")

    # 提取指定车站时刻表
    timetable = extract_station_timetable(df, args.station)
    print(f"\n{args.station} 站共 {len(timetable)} 列车停靠")

    # 方向筛选
    if args.direction != "all":
        timetable = timetable[timetable["direction"] == args.direction].reset_index(drop=True)
        print(f"筛选 {args.direction} 方向后: {len(timetable)} 列车")
    if timetable.empty:
        print("错误：筛选后无数据，请检查车站名和方向参数")
        sys.exit(1)

    # 计算间隔
    timetable = compute_intervals(timetable)

    # 打印详细时刻表
    print(f"\n{'='*110}")
    print(f"{args.station} 站 {args.direction} 方向 列车到发明细")
    print(f"{'='*110}")
    print(f"{'车次':<18} {'到达':>6} {'出发':>6} {'停留':>5} {'到达间隔':>8} {'出发间隔':>8} {'越行':>4}")
    print("-" * 110)
    for _, row in timetable.iterrows():
        arr_s = fmt_time(row["arrival"]) if pd.notna(row["arrival"]) else "—"
        dep_s = fmt_time(row["departure"]) if pd.notna(row["departure"]) else "—"
        dwell_s = f"{row['dwell']:.0f}" if pd.notna(row["dwell"]) else "—"
        ai_s = f"{row['arr_interval']:.0f}" if pd.notna(row["arr_interval"]) else "—"
        di_s = f"{row['dep_interval']:.0f}" if pd.notna(row["dep_interval"]) else "—"
        ot_s = "★" if row.get("overtake", False) else ""
        print(f"{row['train']:<18} {arr_s:>6} {dep_s:>6} {dwell_s:>5} {ai_s:>8} {di_s:>8} {ot_s:>4}")

    # 时间范围
    start_min = parse_time(args.start) if args.start else None
    end_min = parse_time(args.end) if args.end else None

    # 分桶统计
    bin_df, bins = bin_analysis(timetable, start_min, end_min, args.resolution)

    # 打印分桶结果
    print(f"\n{'='*120}")
    print(f"分桶统计结果（分辨率={args.resolution}小时）")
    print(f"{'='*120}")
    print(bin_df.to_string(index=False))

    # 标注满足条件的时段
    hit_bins = bin_df[bin_df["arrival_gt_departure"] == "YES"]
    print(f"\n{'='*60}")
    print(f"★ 到达间隔 > 出发间隔 的时段（共 {len(hit_bins)} 个）：")
    print(f"{'='*60}")
    for _, row in hit_bins.iterrows():
        print(f"  {row['time_bin']}: 最大到达间隔={row['max_arrival_interval_min']}min > "
              f"最小出发间隔={row['min_departure_interval_min']}min (列车数={row['n_trains']})")

    # 输出CSV
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{args.station}_{args.direction}_interval_stats.csv"
    bin_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n统计CSV已保存: {csv_path}")

    # 详细时刻表CSV
    detail_path = output_dir / f"{args.station}_{args.direction}_timetable_detail.csv"
    timetable_out = timetable.copy()
    timetable_out["arrival_time"] = timetable_out["arrival"].apply(fmt_time)
    timetable_out["departure_time"] = timetable_out["departure"].apply(fmt_time)
    timetable_out.to_csv(detail_path, index=False, encoding="utf-8-sig")
    print(f"明细CSV已保存: {detail_path}")

    # 绘图（新版4面板）
    plot_path = plot_results(timetable, bin_df, bins, args.station, args.direction, output_dir)
    print(f"\n分析完成！")
    return bin_df, timetable


if __name__ == "__main__":
    main()