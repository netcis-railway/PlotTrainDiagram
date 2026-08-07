%% 文件名称：BatchS1.m
%  摘    要：批量处理 S1 场景十个测试案例，对每个案例生成三张图
%          1) 计划时刻表（蓝色） → 01_plan.png
%          2) 实际时刻表（红色） → 02_actual.png
%          3) 计划+实际对比   → 03_compare.png
%  时间：2026年06月16日

clc;

% ======================= 输入接口 =======================
dataDir  = 'S1_data';               % 数据文件夹
planFile = 'plan_TT0.xlsx';         % 计划时刻表（相对于 dataDir）
caseDirs = {'S1_t1','S1_t2','S1_t3','S1_t4','S1_t5', ...
            'S1_t6','S1_t7','S1_t8','S1_t9','S1_t10'};
actualFileName = 'reschedule_TT0.xlsx';  % 每个案例的实际时刻表文件名
LineID = '';

% ======================= 加载函数库 =======================
DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% ======================= 读取并转换计划 ===================
planPath = fullfile(dataDir, planFile);
fprintf('读取计划时刻表: %s\n', planPath);
[~, ~, RAW_v3_plan] = xlsread(planPath);
RAW_v3f_plan = DrawTrainDigram.ConvertV3toV3f(RAW_v3_plan);
planDate = DrawTrainDigram.RAWtoDateTime(RAW_v3f_plan);

% 计划时刻表的公共参数
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

    % ----- 读取并转换实际时刻表 -----
    [~, ~, RAW_v3_actual] = xlsread(actualPath);
    RAW_v3f_actual = DrawTrainDigram.ConvertV3toV3f(RAW_v3_actual);
    actualDate = DrawTrainDigram.RAWtoDateTime(RAW_v3f_actual);

    [~, rawCol_actual] = size(RAW_v3f_actual);
    trainNum_actual = (rawCol_actual - 5) / 4;
    [startHour_act, endHour_act] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_actual, trainNum_actual, stationNum);

    % 合并时间范围
    startHour = min(startHour_plan, startHour_act);
    endHour   = max(endHour_plan, endHour_act);

    % 保存 v3f 文件
    writecell(planDate,  fullfile(casePath, 'plan_v3f.xlsx'));
    writecell(actualDate, fullfile(casePath, 'actual_v3f.xlsx'));

    % ========== 图1：仅计划时刻表（蓝色） ==========
    fig = figure('Visible', 'off');
    StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_plan, startHour, endHour, stationNum, minTravelTime_plan, LineID);
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan, StationPosition, LineID, 'b');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');
    set(fig, 'Position', [100, 100, 1800, 1200]);
    exportgraphics(fig, fullfile(casePath, '01_plan.png'), 'Resolution', 96);
    close(fig);

    % ========== 图2：仅实际时刻表（红色） ==========
    fig = figure('Visible', 'off');
    DirectionSign_act = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_actual, trainNum_actual, stationNum);
    minTravelTime_act = DrawTrainDigram.GetStationInterval(RAW_v3f_actual, trainNum_actual, stationNum, DirectionSign_act);
    StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_actual, startHour, endHour, stationNum, minTravelTime_act, LineID);
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_actual, trainNum_actual, stationNum, DirectionSign_act, StationPosition, LineID, 'r');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_actual, trainNum_actual, stationNum, StationPosition, LineID, 'k');
    set(fig, 'Position', [100, 100, 1800, 1200]);
    exportgraphics(fig, fullfile(casePath, '02_actual.png'), 'Resolution', 96);
    close(fig);

    % ========== 图3：计划+实际对比 ==========
    fig = figure('Visible', 'off');
    StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_plan, startHour, endHour, stationNum, minTravelTime_plan, LineID);
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan, StationPosition, LineID, 'b');
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_actual, trainNum_actual, stationNum, DirectionSign_act, StationPosition, LineID, 'r');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_actual, trainNum_actual, stationNum, StationPosition, LineID, 'k');
    set(fig, 'Position', [100, 100, 1800, 1200]);
    exportgraphics(fig, fullfile(casePath, '03_compare.png'), 'Resolution', 96);
    close(fig);

    fprintf('  ✓ 计划:%d车次  实际:%d车次  时间:%02d:00~%02d:00 → %s/\n\n', ...
        trainNum_plan, trainNum_actual, startHour, endHour, caseName);
end

fprintf('========== 全部完成！共处理 %d 个案例 ==========\n', nCases);
fprintf('每个案例文件夹中包含：\n');
fprintf('  plan_v3f.xlsx | actual_v3f.xlsx\n');
fprintf('  01_plan.png | 02_actual.png | 03_compare.png\n');
