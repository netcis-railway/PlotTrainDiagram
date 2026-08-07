figure
clc;
clear;

DrawTrainDigram = DrawTrainDigramFunction_v3f_v5;

%=======================输入===============================
% 设置基本信息，输入v3版本时刻表自动转换成v3f，LineID为指定线路号，TargetStr为需要高亮车次号字符串
fileName = 'output.xlsx';
sheetName = 'Sheet1' ;
LineID = '';     % 单线：1   多线：'1,2'  全线：''
TargetStr = '';  % 需要高亮突出的车次号字符串，以,分隔，不需要为''

% 可选：按时间+车站区间重构（输入''表示不限制）
startTimeInput = '';      % 例如 '08:00:00'
endTimeInput = '';        % 例如 '12:00:00'
startStationInput = '';   % 例如 'BJN' 或 '北京南' 或 1
endStationInput = '';     % 例如 'TJN' 或 '天津南' 或 10

%====================时刻表转换=============================
[NUM, ~, RAW_v3] = xlsread(fileName, sheetName);
% 转换成v3f
RAW = DrawTrainDigram.ConvertV3toV3f(RAW_v3);
RAW_date = DrawTrainDigram.RAWtoDateTime(RAW);
% 手动计算尺寸（替代ReadTrainSchedule内部逻辑）
[rawRow, rawColumn] = size(RAW);
stationNum = rawRow - 1;
trainNum = (rawColumn - 5) / 4;

% 可选：按输入区间重构v3f时刻表
[RAW, RAW_date, trainNum, stationNum] = DrawTrainDigram.RebuildV3fByScope( ...
    RAW, trainNum, startTimeInput, endTimeInput, startStationInput, endStationInput);

% ====================== 自动生成输出文件名 ======================
% 拆分路径、文件名、后缀
[pathStr, nameStr, extStr] = fileparts(fileName); %#ok<ASGLU>
% 拼接新文件名：原路径\原文件名_v3f_scope.xlsx
outputFileName = fullfile(pathStr, [nameStr '_v3f_scope.xlsx']);
% 输出v3f时刻表（自动对应输入文件）
writecell(RAW_date, outputFileName);
disp(['转换v3f完成，文件已保存至：' outputFileName]);

%=======================作图===============================
% 读取运行图起始时间和终止时间
[startHour, endHour] = DrawTrainDigram.GetTrainTimeSegment(RAW, trainNum, stationNum);

% 判断上下行
[DirectionSign] = DrawTrainDigram.JudgeUpOrDown(RAW, trainNum, stationNum);

% 读取列车时刻表中所有列车在同一两个站台间的最小运行时间t，作用是获取坐标轴的Y轴：车站间距
[minTravelTime] = DrawTrainDigram.GetStationInterval(RAW, trainNum, stationNum, DirectionSign);

% 绘制列车运行图的背景线和坐标轴
[StationPosition] = DrawTrainDigram.DrawBackground(RAW, startHour, endHour, stationNum, minTravelTime, LineID);

% 根据时刻表的数据，每次外循环绘制一辆车的运行图
[LineHandle, trainName] = DrawTrainDigram.DrawLineDigram(RAW, trainNum, stationNum, DirectionSign, StationPosition, LineID);

% 标记列车车次
DrawTrainDigram.MarkTrainNumber(RAW, trainNum, stationNum, StationPosition, LineID);

% 根据指定车次号字符串高亮对应运行线
DrawTrainDigram.HighlightTrainLines(LineHandle, trainName, TargetStr);

