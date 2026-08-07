%% 文件名称：DrawDelayCompare_v3f.m
%  摘    要：对比计划/实际时刻表，按延误情况分段着色
%          - 黑色：全程未延误的列车
%          - 蓝色：延误列车的正常区段（画计划线）
%          - 红色：延误列车的延误区段（画实际线）
%  时间：2026年06月16日

figure;
clc;

DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% ======================= 输入接口 =======================
planFile   = 'plan_TT0 .xlsx';       % 计划时刻表（v3）
actualFile = 'reschedule_TT0.xlsx';  % 实际时刻表（v3）
delayThreshold = 60;   % 延误判定阈值（秒），到发时间差超过此值视为延误
LineID = '';

% =================== 读取并转换 ====================
fprintf('读取计划时刻表: %s\n', planFile);
[~, ~, RAW_v3_plan] = xlsread(planFile);
RAW_plan = DrawTrainDigram.ConvertV3toV3f(RAW_v3_plan);

fprintf('读取实际时刻表: %s\n', actualFile);
[~, ~, RAW_v3_actual] = xlsread(actualFile);
RAW_actual = DrawTrainDigram.ConvertV3toV3f(RAW_v3_actual);

[rawRow, ~] = size(RAW_plan);
stationNum = rawRow - 1;
trainNum_plan = (size(RAW_plan, 2) - 5) / 4;
trainNum_actual = (size(RAW_actual, 2) - 5) / 4;

% ================= 收集车次名映射 ================
planTrainNames = cell(1, trainNum_plan);
actualTrainNames = cell(1, trainNum_actual);

for i = 1:trainNum_plan
    planTrainNames{i} = getTrainName(RAW_plan, i);
end
for i = 1:trainNum_actual
    actualTrainNames{i} = getTrainName(RAW_actual, i);
end

% 建立实际车次名 -> 列索引映射
actualNameMap = containers.Map();
for i = 1:trainNum_actual
    nm = actualTrainNames{i};
    if ~isempty(nm) && ~isKey(actualNameMap, nm)
        actualNameMap(nm) = 6 + (i-1)*4;
    end
end

% ===================== 绘制背景 =========================
[startHour_plan, endHour_plan] = DrawTrainDigram.GetTrainTimeSegment(RAW_plan, trainNum_plan, stationNum);
[startHour_act, endHour_act] = DrawTrainDigram.GetTrainTimeSegment(RAW_actual, trainNum_actual, stationNum);
startHour = min(startHour_plan, startHour_act);
endHour   = max(endHour_plan, endHour_act);

DirectionSign_plan = DrawTrainDigram.JudgeUpOrDown(RAW_plan, trainNum_plan, stationNum);
minTravelTime = DrawTrainDigram.GetStationInterval(RAW_plan, trainNum_plan, stationNum, DirectionSign_plan);
StationPosition = DrawTrainDigram.DrawBackground(RAW_plan, startHour, endHour, stationNum, minTravelTime, LineID);

% ============== 筛选有效车站 ==============
validStations = 1:stationNum;

% =================== 逐车逐段绘制 =======================
fprintf('分析延误并绘图...\n');
totalTrains = 0;
delayedTrains = 0;

for p = 1:trainNum_plan
    planName = planTrainNames{p};
    if isempty(planName), continue; end

    planBase = 6 + (p-1)*4;

    % 在实际表中找同名车次
    if ~isKey(actualNameMap, planName)
        % 实际表中无此车次 → 灰色虚线
        drawTrainLine(RAW_plan, planBase, DirectionSign_plan(p), StationPosition, validStations, [0.5 0.5 0.5], ':');
        continue;
    end
    actualBase = actualNameMap(planName);

    totalTrains = totalTrains + 1;

    % 收集计划时间点
    planPts = collectPoints(RAW_plan, planBase, validStations, StationPosition);
    actualPts = collectPoints(RAW_actual, actualBase, validStations, StationPosition);

    if isempty(planPts) || isempty(actualPts), continue; end

    % 计算每个站点的延误
    hasDelay = false;
    stationDelays = zeros(1, length(validStations));

    for k = 1:length(validStations)
        pt = pointAtY(planPts, StationPosition(k));
        at = pointAtY(actualPts, StationPosition(k));
        if ~isempty(pt) && ~isempty(at)
            d = at - pt;
            stationDelays(k) = d;
            if abs(d) > delayThreshold
                hasDelay = true;
            end
        end
    end

    if ~hasDelay
        % 全程无延误 → 黑色实线
        drawTrainLine(RAW_plan, planBase, DirectionSign_plan(p), StationPosition, validStations, 'k', '-');
    else
        % 有延误 → 逐段画
        delayedTrains = delayedTrains + 1;
        drawDelaySegments(RAW_plan, planBase, RAW_actual, actualBase, ...
            validStations, StationPosition, stationDelays, delayThreshold);
    end
end

% =================== 标记车次号 =======================
DrawTrainDigram.MarkTrainNumberColor(RAW_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');

fprintf('绘图完成！总车次: %d, 延误车次: %d, 正常车次: %d\n', ...
    totalTrains, delayedTrains, totalTrains - delayedTrains);


% ====================== 局部函数 =========================

function nm = getTrainName(RAW, trainIdx)
    baseCol = 6 + (trainIdx-1)*4;
    header = RAW{1, baseCol};
    if ischar(header) || isstring(header)
        nm = regexprep(string(header), '[Aa]$', '');
        nm = regexprep(nm, '_$', '');
        nm = char(nm);
    else
        nm = '';
    end
end

function pts = collectPoints(RAW, baseCol, validStations, StationPosition)
    pts = [];
    for k = 1:length(validStations)
        j = validStations(k);
        row = j + 1;
        if row > size(RAW,1), break; end
        arr = RAW{row, baseCol};
        dep = RAW{row, baseCol+1};
        seq = RAW{row, baseCol+3};

        t = parseTimeVal(arr);
        if ~isempty(t)
            pts(end+1, :) = [t, StationPosition(k), 0, checkSeqVal(seq)];
        end
        t = parseTimeVal(dep);
        if ~isempty(t)
            pts(end+1, :) = [t, StationPosition(k), 1, checkSeqVal(seq, 0.1)];
        end
    end
end

function t = pointAtY(pts, yPos)
    idx = find(abs(pts(:,2) - yPos) < 0.01, 1);
    if ~isempty(idx), t = pts(idx, 1); else, t = []; end
end

function drawTrainLine(RAW, baseCol, dirSign, StationPosition, validStations, color, style)
    T = []; Y = []; Seq = [];
    for k = 1:length(validStations)
        j = validStations(k);
        row = j + 1;
        if row > size(RAW,1), break; end
        arr = RAW{row, baseCol};
        dep = RAW{row, baseCol+1};
        seq = RAW{row, baseCol+3};

        t = parseTimeVal(arr);
        if ~isempty(t), T(end+1) = t; Y(end+1) = StationPosition(k); Seq(end+1) = checkSeqVal(seq); end
        t = parseTimeVal(dep);
        if ~isempty(t), T(end+1) = t; Y(end+1) = StationPosition(k); Seq(end+1) = checkSeqVal(seq, 0.1); end
    end
    if numel(T) >= 2
        if all(isnan(Seq)), [T, idx] = sort(T); Y = Y(idx);
        else, [~, idx] = sort(Seq); T = T(idx); Y = Y(idx); end
        plot(T, Y, style, 'Color', color, 'LineWidth', 2);
    end
end

function drawDelaySegments(RAW_plan, planBase, RAW_actual, actualBase, ...
        validStations, StationPosition, stationDelays, threshold)
    for k = 1:length(validStations)-1
        y1 = StationPosition(k);
        y2 = StationPosition(k+1);

        planT1 = getStationTime(RAW_plan, planBase, validStations(k));
        planT2 = getStationTime(RAW_plan, planBase, validStations(k+1));
        actualT1 = getStationTime(RAW_actual, actualBase, validStations(k));
        actualT2 = getStationTime(RAW_actual, actualBase, validStations(k+1));

        d1 = abs(stationDelays(k));
        d2 = abs(stationDelays(k+1));
        isDelayed = (d1 > threshold) || (d2 > threshold);

        if isDelayed
            % 红色：画实际运行线
            if ~isempty(actualT1) && ~isempty(actualT2)
                plot([actualT1, actualT2], [y1, y2], 'r-', 'LineWidth', 2);
            end
        else
            % 蓝色：画计划运行线
            if ~isempty(planT1) && ~isempty(planT2)
                plot([planT1, planT2], [y1, y2], 'b-', 'LineWidth', 2);
            end
        end
    end
end

function t = getStationTime(RAW, baseCol, stationIdx)
    row = stationIdx + 1;
    if row > size(RAW,1), t = []; return; end
    dep = RAW{row, baseCol+1};
    arr = RAW{row, baseCol};
    t = parseTimeVal(dep);
    if isempty(t), t = parseTimeVal(arr); end
end

function s = checkSeqVal(seq, offset)
    if nargin < 2, offset = 0; end
    if isnumeric(seq) && ~isnan(seq), s = seq + offset; else, s = NaN; end
end

function tsec = parseTimeVal(x)
    tsec = [];
    if isnumeric(x) && ~isnan(x)
        v = datevec(x);
    elseif ischar(x) || isstring(x)
        try, v = datevec(x); catch, return; end
    else
        return;
    end
    tsec = v(4)*3600 + v(5)*60 + v(6);
end
