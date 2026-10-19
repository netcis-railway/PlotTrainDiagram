%% 文件名称：DrawFinalDataCompare.m
%  摘    要：绘制"最终数据"文件夹的两组对比运行图，基线为计划时刻表
%          1) 基线(计划，蓝色) + 有平行(求解，红色)
%          2) 基线(计划，蓝色) + 无平行(求解，红色)
%  输    出：前台显示图窗，并保存 .fig 源文件与 .png 图片到"最终数据"文件夹
%  时    间：2026年10月10日

clc;

% 自动把脚本所在目录加入 MATLAB 路径（保证能找到函数库 DrawTrainDigramFunction_v3f_v5）
scriptDir = fileparts(mfilename('fullpath'));
addpath(scriptDir);

% ======================= 配置 =======================
% 数据在脚本所在目录的"最终数据"子文件夹
dataDir   = fullfile(scriptDir, '最终数据');
LineID = '';   % 单线：1   多线：'1,2'  全线：''

% 两组图配置：{计划文件, 求解文件, 图名, fig保存路径, png保存路径}
figs = {
    { fullfile(dataDir, '基线.xlsx'),   fullfile(dataDir, '有平行.xlsx'), ...
      '最终数据：基线(计划) vs 有平行', ...
      fullfile(dataDir, '对比运行图_基线_有平行.fig'), fullfile(dataDir, '对比运行图_基线_有平行.png') }; ...
    { fullfile(dataDir, '基线.xlsx'),   fullfile(dataDir, '无平行.xlsx'), ...
      '最终数据：基线(计划) vs 无平行', ...
      fullfile(dataDir, '对比运行图_基线_无平行.fig'), fullfile(dataDir, '对比运行图_基线_无平行.png') }; ...
    };

DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

for k = 1:size(figs, 1)
    planFile = figs{k}{1};
    solFile  = figs{k}{2};
    figName  = figs{k}{3};
    figPath  = figs{k}{4};
    pngPath  = figs{k}{5};

    fprintf('===== 绘制：%s =====\n', figName);

    % ---- 读取并转换 计划/求解 时刻表 v3 -> v3f ----
    [~, ~, RAW_v3_plan] = xlsread(planFile);
    RAW_v3f_plan = DrawTrainDigram.ConvertV3toV3f(RAW_v3_plan);
    [~, ~, RAW_v3_sol] = xlsread(solFile);
    RAW_v3f_sol = DrawTrainDigram.ConvertV3toV3f(RAW_v3_sol);

    stationNum = size(RAW_v3f_plan, 1) - 1;
    trainNum_plan = (size(RAW_v3f_plan, 2) - 5) / 4;
    trainNum_sol  = (size(RAW_v3f_sol, 2) - 5) / 4;

    % ---- 合并时间范围（两表取并集） ----
    [startHour, endHour] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_plan, trainNum_plan, stationNum);
    [sh, eh] = DrawTrainDigram.GetTrainTimeSegment(RAW_v3f_sol, trainNum_sol, stationNum);
    startHour = min(startHour, sh);
    endHour   = max(endHour, eh);

    % ---- 新建可见图窗，以计划(基线)为基准画背景 ----
    figure('Name', figName, 'NumberTitle', 'off', 'Visible', 'on');
    DirectionSign_plan = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_plan, trainNum_plan, stationNum);
    minTravelTime = DrawTrainDigram.GetStationInterval(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan);
    StationPosition = DrawTrainDigram.DrawBackground(RAW_v3f_plan, startHour, endHour, stationNum, minTravelTime, LineID);

    % ---- 计划(基线)：蓝色，画在最底层 ----
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_plan, trainNum_plan, stationNum, DirectionSign_plan, StationPosition, LineID, 'b');

    % ---- 求解结果：红色 ----
    DirectionSign_sol = DrawTrainDigram.JudgeUpOrDown(RAW_v3f_sol, trainNum_sol, stationNum);
    DrawTrainDigram.DrawLineDigramColor(RAW_v3f_sol, trainNum_sol, stationNum, DirectionSign_sol, StationPosition, LineID, 'r');

    % ---- 车次号（黑色，按计划表标注一次） ----
    DrawTrainDigram.MarkTrainNumberColor(RAW_v3f_plan, trainNum_plan, stationNum, StationPosition, LineID, 'k');

    legend({'计划(基线)', '求解结果'}, 'Location', 'northeast');

    set(gcf, 'Position', [100, 100, 1800, 1200]);

    % ---- 保存 .fig 源文件与 png ----
    savefig(gcf, figPath);
    exportgraphics(gcf, pngPath, 'Resolution', 96);
    fprintf('      -> 已保存：%s\n      -> 已保存：%s\n', figPath, pngPath);
end

fprintf('\n两组对比图已前台显示，.fig 源文件与 .png 图片已保存。\n');
fprintf('提示：可在图中直接缩放/编辑，双击 .fig 文件可随时重新打开。\n');
