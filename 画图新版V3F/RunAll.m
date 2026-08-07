%% 文件名称：RunAll.m
%  摘    要：一键完成 v3->v3f 转换 + 绘制三张运行图
%          1) 计划时刻表（蓝色）
%          2) 实际时刻表（红色）
%          3) 计划+实际对比图
%  时间：2026年06月16日

clc;

% ======================= 输入接口（修改这里即可） =======================
% 计划时刻表文件（v3 格式）
planFile = 'plan.xlsx';
% 实际时刻表文件（v3 格式）
actualFile = 'reschedule_TT0.xlsx';
% 线路筛选：单线填 1，多线填 '1,2'，全线留空 ''
LineID = '';

% ========================= 步骤1：v3 -> v3f 转换 ========================
fprintf('========== 步骤1：格式转换 ==========\n');

DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% 转换计划时刻表
fprintf('[1/2] 转换计划时刻表: %s\n', planFile);
[~, ~, RAW_v3_plan] = xlsread(planFile);
RAW_v3f_plan = DrawTrainDigram.ConvertV3toV3f(RAW_v3_plan);
writecell(DrawTrainDigram.RAWtoDateTime(RAW_v3f_plan), 'plan_TT0_v3f.xlsx');
fprintf('      -> plan_TT0_v3f.xlsx\n');

% 转换实际时刻表
fprintf('[2/2] 转换实际时刻表: %s\n', actualFile);
[~, ~, RAW_v3_actual] = xlsread(actualFile);
RAW_v3f_actual = DrawTrainDigram.ConvertV3toV3f(RAW_v3_actual);
writecell(DrawTrainDigram.RAWtoDateTime(RAW_v3f_actual), 'actual_v3f.xlsx');
fprintf('      -> actual_v3f.xlsx\n');

% ========================= 步骤2：绘制三张图 ============================
fprintf('\n========== 步骤2：绘图 ==========\n');

% --- 图1：仅计划时刻表（蓝色） ---
fprintf('[1/3] 绘制计划运行图...\n');
figure('Name', '计划时刻表', 'NumberTitle', 'off');
[rawRow, rawCol] = size(RAW_v3f_plan);
stationNum = rawRow - 1;
trainNum = (rawCol - 5) / 4;
[startHour, endHour] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_plan, trainNum, stationNum);
DirectionSign = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_plan, trainNum, stationNum);
minTravelTime = DrawTrainDigram.GetStationInterval(RAW_v3f_plan, trainNum, stationNum, DirectionSign);
StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_plan, startHour, endHour, stationNum, minTravelTime, LineID);
DrawTrainDigram.DrawLineDigramColor(RAW_v3f_plan, trainNum, stationNum, DirectionSign, StationPosition, LineID, 'b');
DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_plan, trainNum, stationNum, StationPosition, LineID, 'k');
set(gcf, 'Position', [100, 100, 1800, 1200]);
exportgraphics(gcf, '01_plan.png', 'Resolution', 96);
fprintf('      -> 01_plan.png\n');

% --- 图2：仅实际时刻表（红色） ---
fprintf('[2/3] 绘制实际运行图...\n');
figure('Name', '实际时刻表', 'NumberTitle', 'off');
[rawRow, rawCol] = size(RAW_v3f_actual);
stationNum = rawRow - 1;
trainNum = (rawCol - 5) / 4;
[startHour, endHour] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_actual, trainNum, stationNum);
DirectionSign = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_actual, trainNum, stationNum);
minTravelTime = DrawTrainDigram.GetStationInterval(RAW_v3f_actual, trainNum, stationNum, DirectionSign);
StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_actual, startHour, endHour, stationNum, minTravelTime, LineID);
DrawTrainDigram.DrawLineDigramColor(RAW_v3f_actual, trainNum, stationNum, DirectionSign, StationPosition, LineID, 'r');
DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_actual, trainNum, stationNum, StationPosition, LineID, 'k');
set(gcf, 'Position', [100, 100, 1800, 1200]);
exportgraphics(gcf, '02_actual.png', 'Resolution', 96);
fprintf('      -> 02_actual.png\n');

% --- 图3：计划+实际对比图 ---
fprintf('[3/3] 绘制对比运行图...\n');
figure('Name', '计划 vs 实际', 'NumberTitle', 'off');

% 以计划时刻表为基准画背景
[rawRow, ~] = size(RAW_v3f_plan);
stationNum = rawRow - 1;
trainNum_plan = (size(RAW_v3f_plan, 2) - 5) / 4;
trainNum_actual = (size(RAW_v3f_actual, 2) - 5) / 4;

% 合并时间范围
[startHour_plan, endHour_plan] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_plan, trainNum_plan, stationNum);
[startHour_act, endHour_act] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_actual, trainNum_actual, stationNum);
startHour = min(startHour_plan, startHour_act);
endHour   = max(endHour_plan, endHour_act);

DirectionSign_plan = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_plan, trainNum_plan, stationNum);
minTravelTime = DrawTrainDigram.GetStationInterval(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan);
StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_plan, startHour, endHour, stationNum, minTravelTime, LineID);

% 计划（蓝）
DrawTrainDigram.DrawLineDigramColor(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan, StationPosition, LineID, 'b');
% 实际（红）
DirectionSign_act = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_actual, trainNum_actual, stationNum);
DrawTrainDigram.DrawLineDigramColor(RAW_v3f_actual, trainNum_actual, stationNum, DirectionSign_act, StationPosition, LineID, 'r');

% 车次号（黑色）
DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');
DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_actual, trainNum_actual, stationNum, StationPosition, LineID, 'k');

set(gcf, 'Position', [100, 100, 1800, 1200]);
exportgraphics(gcf, '03_compare.png', 'Resolution', 96);
fprintf('      -> 03_compare.png\n');

% ========================= 完成 ============================
fprintf('\n========== 全部完成！==========\n');
fprintf('输出文件：\n');
fprintf('  plan_TT0_v3f.xlsx  - 计划时刻表 v3f 格式\n');
fprintf('  actual_v3f.xlsx    - 实际时刻表 v3f 格式\n');
fprintf('  01_plan.png        - 计划运行图（蓝色）\n');
fprintf('  02_actual.png      - 实际运行图（红色）\n');
fprintf('  03_compare.png     - 对比运行图（蓝+红）\n');
