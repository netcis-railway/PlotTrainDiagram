%% 文件名称：test_DrawLineDigramBasevsRescheduled.m
%  摘    要：测试 DrawLineDigramBasevsRescheduled 函数的对比画图功能
%  作    者：李仁龙
%  时间：2026年08月07日
%  描    述：读取 v3 格式的计划和调度时刻表，转换为 v3f 后，
%            调用 DrawLineDigramBasevsRescheduled 在同一张图上对比绘制

clc;
figure;

% 获取本脚本所在目录
scriptDir = fileparts(mfilename('fullpath'));
cd(scriptDir);

% ==================== Step 1: 读取 v3 时刻表并转换为 v3f ====================
fprintf('========== Step 1: 读取 v3 文件并转换为 v3f ==========\n');

% v3 源文件目录
dataDir = fullfile(scriptDir, '..', '画图新版V3F');

planFile      = fullfile(dataDir, 'plan_TT0 .xlsx');
rescheduleFile = fullfile(dataDir, 'reschedule_TT0.xlsx');

fprintf('读取计划时刻表: %s\n', planFile);
[~, ~, RAW_v3_plan] = xlsread(planFile);
RAW_plan = ConvertV3toV3f_core(RAW_v3_plan);
[rawRow, rawCol_plan] = size(RAW_plan);
stationNum = rawRow - 1;
trainNum_plan = (rawCol_plan - 5) / 4;
fprintf('  车站数: %d, 列车数: %d\n', stationNum, trainNum_plan);

fprintf('读取调度时刻表: %s\n', rescheduleFile);
[~, ~, RAW_v3_res] = xlsread(rescheduleFile);
RAW_res = ConvertV3toV3f_core(RAW_v3_res);
[~, rawCol_res] = size(RAW_res);
trainNum_res = (rawCol_res - 5) / 4;
fprintf('  车站数: %d, 列车数: %d\n', stationNum, trainNum_res);

% ==================== Step 2: 加载函数库 ====================
fprintf('\n========== Step 2: 加载函数库 ==========\n');
DrawTrainDigram = DrawTrainDigramFunctionV3f;

% ==================== Step 3: 对比画图 ====================
fprintf('\n========== Step 3: 绘制对比运行图 ==========\n');
LineID = '';  % '' 表示全线

% 调用对比画图函数（直接传入 RAW 数据，不读文件）
StationPosition = DrawTrainDigram.DrawLineDigramBasevsRescheduled( ...
    RAW_plan, trainNum_plan, ...
    RAW_res,  trainNum_res, ...
    stationNum, LineID);

% ==================== Step 4: 保存图片 ====================
title('列车运行图对比：基本计划（黑色）vs 调度计划（红/蓝）', 'FontSize', 14);

outputPNG = fullfile(scriptDir, 'CompareResult.png');
saveas(gcf, outputPNG);
fprintf('\n运行图已保存至: %s\n', outputPNG);

fprintf('\n========== 测试完成！ ==========\n');
fprintf('  黑色线 = 基本计划时刻表 (%d 趟)\n', trainNum_plan);
fprintf('  红色线 = 调度计划下行列车\n');
fprintf('  蓝色线 = 调度计划上行列车 (%d 趟)\n', trainNum_res);


%% ======================== 局部函数 ========================

function RAW_v3f = ConvertV3toV3f_core(RAW_v3)
    % 将 v3 时刻表转换为 v3f 时刻表（在内存中完成，不写文件）
    [row, col] = size(RAW_v3);
    stationNum = row - 1;
    trainNum = (col - 3) / 3;
    newCol = 5 + trainNum * 4;
    RAW_v3f = cell(row, newCol);

    % 前5列表头
    RAW_v3f(1,1:5) = {'NODE_NAME_SHORT','NODE_ID','NODE_CODE','LINE_IND','NODE_NAME'};
    for i = 2:row
        RAW_v3f{i,1} = '';
        RAW_v3f{i,2} = RAW_v3{i,1};
        RAW_v3f{i,3} = RAW_v3{i,2};
        RAW_v3f{i,4} = [];    % LINE_IND 置空
        RAW_v3f{i,5} = RAW_v3{i,3};
    end

    % 每辆车：3列 → 4列（添加SEQ）
    for t = 1:trainNum
        oldBase = 4 + (t-1)*3;
        newBase = 6 + (t-1)*4;

        RAW_v3f{1,newBase}   = RAW_v3{1, oldBase};
        RAW_v3f{1,newBase+1} = RAW_v3{1, oldBase+1};
        RAW_v3f{1,newBase+2} = RAW_v3{1, oldBase+2};
        RAW_v3f{1,newBase+3} = regexprep(RAW_v3{1, oldBase}, '[_Aa]$', '_SEQ');

        times = [];
        rows_idx = [];
        for i = 2:row
            RAW_v3f{i,newBase}   = RAW_v3{i, oldBase};
            RAW_v3f{i,newBase+1} = RAW_v3{i, oldBase+1};
            RAW_v3f{i,newBase+2} = RAW_v3{i, oldBase+2};

            A = RAW_v3{i, oldBase};
            D = RAW_v3{i, oldBase+1};
            if isnumeric(A) && ~isnan(A)
                times(end+1) = A; rows_idx(end+1) = i;
            elseif isnumeric(D) && ~isnan(D)
                times(end+1) = D; rows_idx(end+1) = i;
            end
        end

        seq_col = nan(row,1);
        if ~isempty(times)
            time_sec = zeros(size(times));
            for k = 1:length(times)
                v = datevec(times(k));
                time_sec(k) = v(4)*3600 + v(5)*60 + v(6);
            end
            [~, order] = sort(time_sec);
            for k = 1:length(order)
                seq_col(rows_idx(order(k))) = k;
            end
        end
        for i = 2:row
            RAW_v3f{i,newBase+3} = seq_col(i);
        end
    end
end
