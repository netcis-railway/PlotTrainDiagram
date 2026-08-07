%% 文件名称：DrawCompare_v3f.m
%  摘    要：将 plan_TT0 和 reschedule_TT0 两张时刻表绘制在同一张运行图上
%           plan 用蓝色线，reschedule 用红色线，便于对比
%  作    者：自动生成
%  时间：2026年06月15日

figure;
clc;

% 加载函数库
DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% ======================= 输入配置 =======================
planFile      = 'plan_TT0 .xlsx';      % 计划时刻表（v3格式）
rescheduleFile = 'reschedule_TT0.xlsx'; % 调整时刻表（v3格式）
LineID = '';       % 单线：1   多线：'1,2'  全线：''

% =================== 读取并转换 plan ====================
fprintf('读取计划时刻表: %s\n', planFile);
[~, ~, RAW_v3_plan] = xlsread(planFile);
RAW_plan = DrawTrainDigram.ConvertV3toV3f(RAW_v3_plan);
[rawRow_plan, rawCol_plan] = size(RAW_plan);
stationNum = rawRow_plan - 1;
trainNum_plan = (rawCol_plan - 5) / 4;
fprintf('  车站数: %d, 列车数: %d\n', stationNum, trainNum_plan);

% 输出 plan 的 v3f 文件
RAW_plan_date = DrawTrainDigram.RAWtoDateTime(RAW_plan);
writecell(RAW_plan_date, 'plan_TT0_v3f.xlsx');
fprintf('  已保存 plan v3f 至: plan_TT0_v3f.xlsx\n');

% ================== 读取并转换 reschedule =================
fprintf('读取调整时刻表: %s\n', rescheduleFile);
[~, ~, RAW_v3_reschedule] = xlsread(rescheduleFile);
RAW_reschedule = DrawTrainDigram.ConvertV3toV3f(RAW_v3_reschedule);
[~, rawCol_reschedule] = size(RAW_reschedule);
trainNum_reschedule = (rawCol_reschedule - 5) / 4;
fprintf('  车站数: %d, 列车数: %d\n', stationNum, trainNum_reschedule);

% 输出 reschedule 的 v3f 文件
RAW_reschedule_date = DrawTrainDigram.RAWtoDateTime(RAW_reschedule);
writecell(RAW_reschedule_date, 'reschedule_TT0_v3f.xlsx');
fprintf('  已保存 reschedule v3f 至: reschedule_TT0_v3f.xlsx\n');

% ============== 获取合并时间轴范围 =================
[startHour_plan, endHour_plan] = DrawTrainDigram.GetTrainTimeSegment(RAW_plan, trainNum_plan, stationNum);
[startHour_res, endHour_res] = DrawTrainDigram.GetTrainTimeSegment(RAW_reschedule, trainNum_reschedule, stationNum);
startHour = min(startHour_plan, startHour_res);
endHour   = max(endHour_plan, endHour_res);
fprintf('时间范围: %02d:00 ~ %02d:00\n', startHour, endHour);

% ============== 绘制背景（以 plan 车站为基础，两者车站相同） ==============
DirectionSign_plan = DrawTrainDigram.JudgeUpOrDown(RAW_plan, trainNum_plan, stationNum);
minTravelTime = DrawTrainDigram.GetStationInterval(RAW_plan, trainNum_plan, stationNum, DirectionSign_plan);
StationPosition = DrawTrainDigram.DrawBackground(RAW_plan, startHour, endHour, stationNum, minTravelTime, LineID);

% ============== 绘制 plan 列车运行线（蓝色） ==============
fprintf('绘制计划时刻表 (蓝色)...\n');
[LineHandle_plan, trainName_plan] = DrawTrainDigram.DrawLineDigramColor( ...
    RAW_plan, trainNum_plan, stationNum, DirectionSign_plan, StationPosition, LineID, 'b');

% ============== 绘制 reschedule 列车运行线（红色） ==============
fprintf('绘制调整时刻表 (红色)...\n');
DirectionSign_res = DrawTrainDigram.JudgeUpOrDown(RAW_reschedule, trainNum_reschedule, stationNum);
% 注意：使用 plan 的 StationPosition（车站相同，Y轴坐标一致）
[LineHandle_res, trainName_res] = DrawTrainDigram.DrawLineDigramColor( ...
    RAW_reschedule, trainNum_reschedule, stationNum, DirectionSign_res, StationPosition, LineID, 'r');

% ============== 标记车次号 ==============
fprintf('标记车次号...\n');
DrawTrainDigram.MarkTrainNumberColor(RAW_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');
DrawTrainDigram.MarkTrainNumberColor(RAW_reschedule, trainNum_reschedule, stationNum, StationPosition, LineID, 'k');

fprintf('\n绘图完成！\n');
fprintf('  蓝色线 = 计划时刻表 (plan_TT0): %d 趟\n', trainNum_plan);
fprintf('  红色线 = 调整时刻表 (reschedule_TT0): %d 趟\n', trainNum_reschedule);
