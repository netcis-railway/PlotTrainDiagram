%% 文件名称：DrawPlanOnly_v3f.m
%  摘    要：绘制计划时刻表 (plan_TT0) 运行图，蓝色线
%  时间：2026年06月16日

figure;
clc;

DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% ======================= 输入配置 =======================
planFile = 'plan_TT0 .xlsx';
LineID   = '';   % 单线：1   多线：'1,2'  全线：''

% =================== 读取并转换 plan ====================
fprintf('读取计划时刻表: %s\n', planFile);
[~, ~, RAW_v3] = xlsread(planFile);
RAW = DrawTrainDigram.ConvertV3toV3f(RAW_v3);
[rawRow, rawCol] = size(RAW);
stationNum = rawRow - 1;
trainNum = (rawCol - 5) / 4;
fprintf('  车站数: %d, 列车数: %d\n', stationNum, trainNum);

% ===================== 获取时间轴范围 ====================
[startHour, endHour] = DrawTrainDigram.GetTrainTimeSegment(RAW, trainNum, stationNum);
fprintf('  时间范围: %02d:00 ~ %02d:00\n', startHour, endHour);

% ====================== 绘制背景 =========================
DirectionSign = DrawTrainDigram.JudgeUpOrDown(RAW, trainNum, stationNum);
minTravelTime = DrawTrainDigram.GetStationInterval(RAW, trainNum, stationNum, DirectionSign);
StationPosition = DrawTrainDigram.DrawBackground(RAW, startHour, endHour, stationNum, minTravelTime, LineID);

% =================== 绘制列车运行线 ======================
% 全部使用蓝色，不区分上下行
[LineHandle, trainName] = DrawTrainDigram.DrawLineDigramColor( ...
    RAW, trainNum, stationNum, DirectionSign, StationPosition, LineID, 'b');

% ===================== 标记车次号 =========================
DrawTrainDigram.MarkTrainNumberColor(RAW, trainNum, stationNum, StationPosition, LineID, 'k');

fprintf('绘图完成！\n');
