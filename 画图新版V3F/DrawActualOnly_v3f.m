%% 文件名称：DrawActualOnly_v3f.m
%  摘    要：绘制实际时刻表 (reschedule_TT0_v3f) 运行图，红色线
%  时间：2026年06月16日

figure;
clc;

DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% ======================= 输入配置 =======================
fileName = 'reschedule_TT0.xlsx';
LineID   = '';   % 单线：1   多线：'1,2'  全线：''

% =================== 读取并转换 v3 -> v3f ====================
fprintf('读取实际时刻表: %s\n', fileName);
[~, ~, RAW_v3] = xlsread(fileName);
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

% =================== 绘制列车运行线（红色） ======================
[LineHandle, trainName] = DrawTrainDigram.DrawLineDigramColor( ...
    RAW, trainNum, stationNum, DirectionSign, StationPosition, LineID, 'r');

% ===================== 标记车次号（黑色） =======================
DrawTrainDigram.MarkTrainNumberColor(RAW, trainNum, stationNum, StationPosition, LineID, 'k');

fprintf('绘图完成！\n');
