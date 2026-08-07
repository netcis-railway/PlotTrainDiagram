%% 文件名称：BatchS2.m
%  摘    要：批量处理 S2 场景十个测试案例，对每个案例生成三张图
%  时间：2026年07月06日

clc;

% ======================= 输入接口 =======================
dataDir  = 'S2_data';
planFile = 'plan_TT0.xlsx';
caseDirs = {'S2_t1','S2_t2','S2_t3','S2_t4','S2_t5', ...
            'S2_t6','S2_t7','S2_t8','S2_t9','S2_t10'};
actualFileName = 'reschedule_TT0.xlsx';
LineID = '';

% ======================= 加载函数库 =======================
DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% ======================= 读取并转换计划 ===================
planPath = fullfile(dataDir, planFile);
fprintf('读取计划时刻表: %s\n', planPath);
[~, ~, RAW_v3_plan] = xlsread(planPath);
RAW_v3f_plan = DrawTrainDigram.ConvertV3toV3f(RAW_v3_plan);
planDate = DrawTrainDigram.RAWtoDateTime(RAW_v3f_plan);

[rawRow_plan, rawCol_plan] = size(RAW_v3f_plan);
stationNum = rawRow_plan - 1;
trainNum_plan = (rawCol_plan - 5) / 4;
[startHour_plan, endHour_plan] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_plan, trainNum_plan, stationNum);
DirectionSign_plan = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_plan, trainNum_plan, stationNum);
minTravelTime_plan = DrawTrainDigram.GetStationInterval(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan);

fprintf('计划: %d 车站, %d 车次, 时间 %02d:00~%02d:00\n\n', ...
    stationNum, trainNum_plan, startHour_plan, endHour_plan);

% ======================= 逐案例处理 =======================
nCases = length(caseDirs);
for c = 1:nCases
    caseName = caseDirs{c};
    casePath = fullfile(dataDir, caseName);
    actualPath = fullfile(casePath, actualFileName);

    fprintf('[%d/%d] 处理 %s ...\n', c, nCases, caseName);

    if ~exist(actualPath, 'file')
        fprintf('  ⚠ 跳过：找不到 %s\n\n', actualPath);
        continue;
    end

    [~, ~, RAW_v3_actual] = xlsread(actualPath);
    RAW_v3f_actual = DrawTrainDigram.ConvertV3toV3f(RAW_v3_actual);
    actualDate = DrawTrainDigram.RAWtoDateTime(RAW_v3f_actual);

    [~, rawCol_actual] = size(RAW_v3f_actual);
    trainNum_actual = (rawCol_actual - 5) / 4;
    [startHour_act, endHour_act] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_actual, trainNum_actual, stationNum);

    startHour = min(startHour_plan, startHour_act);
    endHour   = max(endHour_plan, endHour_act);

    writecell(planDate,  fullfile(casePath, 'plan_v3f.xlsx'));
    writecell(actualDate, fullfile(casePath, 'actual_v3f.xlsx'));

    % 图1：计划（蓝）
    fig = figure('Visible', 'off');
    StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_plan, startHour, endHour, stationNum, minTravelTime_plan, LineID);
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan, StationPosition, LineID, 'b');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');
    set(fig, 'Position', [100, 100, 1800, 1200]);
    exportgraphics(fig, fullfile(casePath, '01_plan.png'), 'Resolution', 96);
    close(fig);

    % 图2：实际（红）
    fig = figure('Visible', 'off');
    DirectionSign_act = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_actual, trainNum_actual, stationNum);
    minTravelTime_act = DrawTrainDigram.GetStationInterval(RAW_v3f_actual, trainNum_actual, stationNum, DirectionSign_act);
    StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_actual, startHour, endHour, stationNum, minTravelTime_act, LineID);
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_actual, trainNum_actual, stationNum, DirectionSign_act, StationPosition, LineID, 'r');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_actual, trainNum_actual, stationNum, StationPosition, LineID, 'k');
    set(fig, 'Position', [100, 100, 1800, 1200]);
    exportgraphics(fig, fullfile(casePath, '02_actual.png'), 'Resolution', 96);
    close(fig);

    % 图3：对比
    fig = figure('Visible', 'off');
    StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_plan, startHour, endHour, stationNum, minTravelTime_plan, LineID);
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan, StationPosition, LineID, 'b');
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_actual, trainNum_actual, stationNum, DirectionSign_act, StationPosition, LineID, 'r');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_actual, trainNum_actual, stationNum, StationPosition, LineID, 'k');
    set(fig, 'Position', [100, 100, 1800, 1200]);
    exportgraphics(fig, fullfile(casePath, '03_compare.png'), 'Resolution', 96);
    close(fig);

    fprintf('  ✓ 计划:%d车次  实际:%d车次  时间:%02d:00~%02d:00\n\n', ...
        trainNum_plan, trainNum_actual, startHour, endHour);
end

fprintf('========== 全部完成！共处理 %d 个案例 ==========\n', nCases);
