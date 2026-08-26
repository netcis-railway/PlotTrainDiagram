#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
headway_analysis.py — 车站到达/出发间隔(Headway)统计分析工具
=============================================================
针对 v3f/v4 格式的时刻表 CSV（如 plan_TT0_v3f2.csv），
对指定车站按行别（上行/下行）的列车到达、出发时刻做间隔统计：

  * 到达间隔 (arrival headway)  = 相邻两列车到达时刻之差
  * 出发间隔 (departure headway)= 相邻两列车出发时刻之差
  * 按时间分辨率（默认 1 小时）分桶统计：数量 / 最小 / 最大 / 平均
  * 标注每个时间桶的“最大到达间隔”与“最小出发间隔”
  * 判断每个时间桶内“到达间隔是否比出发间隔更大”
  * 输出统计 CSV + 事件明细 CSV + 图表 PNG

字段说明（时刻表格式）:
  NODE_NAME_SHORT / NODE_ID / NODE_CODE / LINE_IND / NODE_NAME : 车站信息
  {车次}_A 到达时刻, {车次}_D 出发时刻, {车次}_G 股道, {车次}__SEQ 到站顺序
  某车次对应字段为空 => 该列车不经过该车站。

用法示例:
  python headway_analysis.py --csv plan_TT0_v3f2.csv --station 徐州东 \
      --direction 下行 --resolution 60
  python headway_analysis.py --csv plan_TT0_v3f2.csv --station XZD \
      --start 09:00 --end 16:00 --resolution 30 --outdir ./output
"""

import argparse
import os
import re
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------- 中文字体设置 ----------------
plt.rcParams["font.sans-serif"] = [
    "SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


# ---------------------------------------------------------------- 工具函数
def parse_time(s):
    """'H:MM' -> 距0点的分钟数；空值/NaN 返回 None"""
    if s is None:
        return None
    if isinstance(s, float) and np.isnan(s):
        return None
    s = str(s).strip()
    if not s or s.lower() in ("nan", "none", "null"):
        return None
    m = TIME_RE.match(s)
    if not m:
        raise ValueError(f"无法解析时间: {s!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def fmt_time(minutes):
    """分钟数 -> 'HH:MM'"""
    if minutes is None:
        return ""
    return f"{int(minutes) // 60:02d}:{int(minutes) % 60:02d}"


def read_timetable(path):
    """读取时刻表 CSV，返回 (DataFrame, 车次列表[按表头顺序])"""
    df = pd.read_csv(path, encoding="utf-8")
    seen, trains = set(), []
    for c in df.columns[5:]:
        for suf in ("_A", "_D", "_G", "__SEQ"):
            if c.endswith(suf):
                t = c[: -len(suf)]
                if t not in seen:
                    seen.add(t)
                    trains.append(t)
                break
    return df, trains


def train_direction(df, train):
    """按途经车站 NODE_ID 的走向判断行别：递增=下行，递减=上行"""
    a_col = f"{train}_A"
    node_ids = []
    for _, row in df.iterrows():
        v = row.get(a_col)
        if pd.notna(v) and str(v).strip():
            node_ids.append(int(row["NODE_ID"]))
    if len(node_ids) < 2:
        return None
    return "下行" if node_ids[-1] > node_ids[0] else "上行"


def extract_station_events(df, trains, station, direction):
    """提取指定车站、指定行别下列车的到/发事件。

    返回 (站码, 站名, 到达事件列表, 出发事件列表)
    事件元素: (时刻分钟, 车次, 股道)
    """
    if str(station).strip().isdigit():
        mask = df["NODE_ID"].astype(str).str.strip() == str(station).strip()
    else:
        s = str(station).strip()
        mask = (df["NODE_NAME"].astype(str).str.strip() == s) | \
               (df["NODE_CODE"].astype(str).str.strip() == s)
    hit = df[mask]
    if hit.empty:
        raise ValueError(f"未找到车站: {station}")
    row = hit.iloc[0]
    stn_code = str(row["NODE_CODE"]).strip()
    stn_name = str(row["NODE_NAME"]).strip()

    arrivals, departures = [], []
    for t in trains:
        if direction:
            if train_direction(df, t) != direction:
                continue
        a = parse_time(row.get(f"{t}_A"))
        d = parse_time(row.get(f"{t}_D"))
        trk = str(row.get(f"{t}_G")).strip()
        if a is not None:
            arrivals.append((a, t, trk))
        if d is not None:
            departures.append((d, t, trk))
    arrivals.sort()
    departures.sort()
    return stn_code, stn_name, arrivals, departures


def compute_headways(events):
    """事件列表 -> [(首事件时刻, 间隔分钟), ...]（相邻事件之差）"""
    return [(events[i - 1][0], events[i][0] - events[i - 1][0])
            for i in range(1, len(events))]


def bucket_stats(headway_list, resolution_min, start_t, end_t):
    """按时间分辨率分桶统计间隔。

    每个间隔归属其“首事件”所在的时间桶；
    可选的 [start_t, end_t) 为分析时间段（分钟）。
    返回 [{bucket_start, bucket_end, count, min, max, mean}, ...]
    """
    buckets = defaultdict(list)
    for t0, h in headway_list:
        if start_t is not None and t0 < start_t:
            continue
        if end_t is not None and t0 >= end_t:
            continue
        b = (t0 // resolution_min) * resolution_min
        buckets[b].append(h)
    rows = []
    for b in sorted(buckets):
        hs = np.array(buckets[b], dtype=float)
        rows.append({
            "bucket_start": fmt_time(b),
            "count": int(len(hs)),
            "min": float(hs.min()),
            "max": float(hs.max()),
            "mean": float(hs.mean()),
        })
    return rows


def _bucket_end(start_str, resolution_min):
    """由桶起始时刻字符串 + 分辨率，计算桶结束时刻字符串 'HH:MM'"""
    t = parse_time(start_str)
    return fmt_time(t + resolution_min)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(
        description="车站到达/出发间隔(headway)统计分析")
    ap.add_argument("--csv", required=True, help="时刻表 CSV 文件路径")
    ap.add_argument("--station", default="徐州东",
                    help="车站：中文站名 或 站码(如 徐州东 / XZD)，默认徐州东")
    ap.add_argument("--direction", default="下行", choices=["下行", "上行", ""],
                    help="行别过滤，空串表示全部，默认下行")
    ap.add_argument("--start", default=None, help="分析起始时刻 HH:MM（默认全天）")
    ap.add_argument("--end", default=None, help="分析结束时刻 HH:MM（默认全天）")
    ap.add_argument("--resolution", type=int, default=60,
                    help="时间分辨率（分钟），默认60（即1小时）")
    ap.add_argument("--outdir", default=None,
                    help="输出目录（默认：脚本目录/output）")
    args = ap.parse_args()

    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(outdir, exist_ok=True)

    start_t = parse_time(args.start)
    end_t = parse_time(args.end)
    if start_t is not None and end_t is not None and start_t >= end_t:
        raise ValueError("--start 必须早于 --end")

    # 1) 读取时刻表
    df, trains = read_timetable(args.csv)

    # 2) 提取车站事件
    stn_code, stn_name, arrivals, departures = extract_station_events(
        df, trains, args.station, args.direction)

    # 3) 计算间隔
    arr_hw = compute_headways(arrivals)
    dep_hw = compute_headways(departures)

    # 4) 分桶统计
    arr_stats = bucket_stats(arr_hw, args.resolution, start_t, end_t)
    dep_stats = bucket_stats(dep_hw, args.resolution, start_t, end_t)

    # 5) 合并为一张统计表
    a = pd.DataFrame(arr_stats)
    d = pd.DataFrame(dep_stats)
    a = a.rename(columns={c: f"arr_{c}" for c in a.columns if c != "bucket_start"})
    d = d.rename(columns={c: f"dep_{c}" for c in d.columns if c != "bucket_start"})
    stats = pd.merge(a, d, on="bucket_start", how="outer").sort_values("bucket_start")
    stats = stats.sort_values("bucket_start").reset_index(drop=True)
    stats["bucket_end"] = stats["bucket_start"].apply(
        lambda s: _bucket_end(s, args.resolution) if pd.notna(s) else "")

    # 标注列：每个时间桶的“最大到达间隔”与“最小出发间隔”
    stats["标注_最大到达间隔"] = stats["arr_max"]
    stats["标注_最小出发间隔"] = stats["dep_min"]
    # 判断：到达间隔是否比出发间隔更大（均值比较 / 最大vs最小比较）
    stats["arr_mean_gt_dep_mean"] = stats["arr_mean"] > stats["dep_mean"]
    stats["arr_max_gt_dep_min"] = stats["arr_max"] > stats["dep_min"]

    # 6) 事件明细 CSV
    ev_a = pd.DataFrame([(fmt_time(t), train, trk) for t, train, trk in arrivals],
                        columns=["到达时刻", "车次", "股道"])
    ev_d = pd.DataFrame([(fmt_time(t), train, trk) for t, train, trk in departures],
                        columns=["出发时刻", "车次", "股道"])
    if arr_hw:
        ev_a["到达间隔(min)"] = [h for _, h in arr_hw] + [None]
    if dep_hw:
        ev_d["出发间隔(min)"] = [h for _, h in dep_hw] + [None]

    # 7) 输出文件
    tag = f"{stn_code}_{args.direction or '全部'}"
    csv_stats = os.path.join(outdir, f"{tag}_headway_stats_res{args.resolution}min.csv")
    csv_events_a = os.path.join(outdir, f"{tag}_events_arrival.csv")
    csv_events_d = os.path.join(outdir, f"{tag}_events_departure.csv")
    stats.to_csv(csv_stats, index=False, encoding="utf-8-sig")
    ev_a.to_csv(csv_events_a, index=False, encoding="utf-8-sig")
    ev_d.to_csv(csv_events_d, index=False, encoding="utf-8-sig")

    # 8) 画图
    fig_path = plot_headway(stats, stn_name, stn_code, args.direction,
                            args.resolution, outdir, tag)

    # 9) 控制台汇总
    print("=" * 70)
    print(f"车站: {stn_name}({stn_code})  行别: {args.direction or '全部'}")
    print(f"分辨率: {args.resolution} 分钟   时间段: "
          f"{args.start or '全天'} ~ {args.end or '全天'}")
    print(f"途经列车数: 到达 {len(arrivals)} 列, 出发 {len(departures)} 列")
    print(f"到达间隔: 共 {len(arr_hw)} 个, "
          f"平均 {np.mean([h for _, h in arr_hw]):.1f} min, "
          f"最小 {min(h for _, h in arr_hw)} min, "
          f"最大 {max(h for _, h in arr_hw)} min")
    print(f"出发间隔: 共 {len(dep_hw)} 个, "
          f"平均 {np.mean([h for _, h in dep_hw]):.1f} min, "
          f"最小 {min(h for _, h in dep_hw)} min, "
          f"最大 {max(h for _, h in dep_hw)} min")
    print("-" * 70)
    print("分桶统计表（到达间隔 vs 出发间隔）：")
    show = stats[[
        "bucket_start", "arr_count", "arr_mean", "arr_max",
        "dep_count", "dep_mean", "dep_min",
        "标注_最大到达间隔", "标注_最小出发间隔",
        "arr_mean_gt_dep_mean", "arr_max_gt_dep_min",
    ]].copy()
    for _, r in show.iterrows():
        flag = "★到达>出发" if r["arr_mean_gt_dep_mean"] else ""
        print(f"  {r['bucket_start']:>8s}  到达[n={r['arr_count']:2d} "
              f"均{r['arr_mean']:5.1f} 大{r['arr_max']:4.0f}]  "
              f"出发[n={r['dep_count']:2d} 均{r['dep_mean']:5.1f} "
              f"小{r['dep_min']:4.0f}]  {flag}")
    print("-" * 70)
    big = stats[stats["arr_mean_gt_dep_mean"]]
    if not big.empty:
        print("★ 到达间隔比出发间隔更大的时间段：")
        for _, r in big.iterrows():
            print(f"   {r['bucket_start']}~{r['bucket_end']}  "
                  f"(到达平均{r['arr_mean']:.1f}min > 出发平均{r['dep_mean']:.1f}min)")
    else:
        print("（没有到达平均间隔大于出发平均间隔的时间桶）")
    print(f"\n已输出: {csv_stats}")
    print(f"已输出: {csv_events_a}")
    print(f"已输出: {csv_events_d}")
    print(f"已输出: {fig_path}")


def plot_headway(stats, stn_name, stn_code, direction, resolution, outdir, tag):
    """柱状图：每桶 到达/出发 平均间隔 + 最大到达/最小出发标注"""
    x = np.arange(len(stats))
    labels = stats["bucket_start"].astype(str).tolist()
    width = 0.35

    fig, ax = plt.subplots(figsize=(12, 6))
    b1 = ax.bar(x - width / 2, stats["arr_mean"], width,
                label="到达平均间隔", color="#4C72B0", alpha=0.85)
    b2 = ax.bar(x + width / 2, stats["dep_mean"], width,
                label="出发平均间隔", color="#DD8452", alpha=0.85)

    # 最大到达间隔 / 最小出发间隔 标注
    ax.scatter(x - width / 2, stats["arr_max"], marker="v", s=60,
               color="#C44E52", zorder=5, label="最大到达间隔")
    ax.scatter(x + width / 2, stats["dep_min"], marker="^", s=60,
               color="#55A868", zorder=5, label="最小出发间隔")
    for xi, v in zip(x, stats["arr_max"]):
        ax.annotate(f"{v:.0f}", (xi - width / 2, v), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8, color="#C44E52")
    for xi, v in zip(x, stats["dep_min"]):
        ax.annotate(f"{v:.0f}", (xi + width / 2, v), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8, color="#55A868")

    # 到达平均 > 出发平均 的时间桶高亮
    flag = stats["arr_mean_gt_dep_mean"].fillna(False)
    for xi in x[flag.values]:
        ax.axvspan(xi - 0.5, xi + 0.5, color="gold", alpha=0.25, zorder=0)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("间隔 (min)")
    ax.set_xlabel(f"时间桶（分辨率 {resolution} 分钟，按间隔首事件时刻归类）")
    ax.set_title(f"{stn_name}({stn_code}) {direction or '全部'} 到达/出发间隔统计\n"
                 f"金色背景 = 到达平均间隔 > 出发平均间隔")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", ls="--", alpha=0.4)
    fig.tight_layout()
    fig_path = os.path.join(outdir, f"{tag}_headway_by_bucket.png")
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)
    return fig_path


if __name__ == "__main__":
    main()
