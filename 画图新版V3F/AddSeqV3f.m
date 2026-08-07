%% 文件名称：AddSeqV3f.m
%  摘    要：将 plan_TT0 和 reschedule_TT0 从 v3 格式转换为 v3f 格式（添加SEQ列）
%  作    者：自动生成
%  时间：2026年06月15日

clc; clear;

% 加载函数库
DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

% 需要处理的文件列表
fileNames = {'plan_TT0 .xlsx', 'reschedule_TT0.xlsx'};

for k = 1:length(fileNames)
    fileName = fileNames{k};
    fprintf('处理文件: %s\n', fileName);

    % 读取v3时刻表
    [~, ~, RAW_v3] = xlsread(fileName);
    fprintf('  原始 v3 格式: %d 行 x %d 列\n', size(RAW_v3, 1), size(RAW_v3, 2));

    % 转换为v3f格式（自动添加SEQ列）
    RAW_v3f = DrawTrainDigram.ConvertV3toV3f(RAW_v3);

    % 转换为日期时间格式以便输出
    RAW_date = DrawTrainDigram.RAWtoDateTime(RAW_v3f);

    % 生成输出文件名
    [pathStr, nameStr, ~] = fileparts(fileName);
    % 去除文件名末尾空格
    nameStr = strtrim(nameStr);
    outFileName = fullfile(pathStr, [nameStr '_v3f.xlsx']);

    % 保存
    writecell(RAW_date, outFileName);
    fprintf('  输出 v3f 格式: %d 行 x %d 列\n', size(RAW_v3f, 1), size(RAW_v3f, 2));
    fprintf('  已保存至: %s\n\n', outFileName);
end

disp('全部转换完成！');
