figure
clc;
clear;

DrawTrainDigram = DrawTrainDigramFunctionV3f;

%=======================输入===============================
% 读取以Excel形式存储的列车时刻表，时刻表的标准遵循版本V3f
[RAW, NUM, trainNum, stationNum] = DrawTrainDigram.ReadTrainSchedule('Train TimeTable final data Metro (version 3)', 'TTT1base_METRO');
% 设置基本信息，LineID为指定线路号，color为画图指定颜色
LineID = 2;     % 单线：1   多线：'1,2'

% 读取运行图起始时间和终止时间
[startHour, endHour] = DrawTrainDigram.GetTrainTimeSegment(RAW, trainNum, stationNum);

% 判断上下行
[DirectionSign] = DrawTrainDigram.JudgeUpOrDown(RAW, trainNum, stationNum);

% 读取列车时刻表中所有列车在同一两个站台间的最小运行时间t，作用是获取坐标轴的Y轴：车站间距
[minTravelTime] = DrawTrainDigram.GetStationInterval(RAW, trainNum, stationNum, DirectionSign);

% 绘制列车运行图的背景线和坐标轴
[StationPosition] = DrawTrainDigram.DrawBackground(RAW, startHour, endHour, stationNum, minTravelTime, LineID);

% 根据时刻表的数据，每次外循环绘制一辆车的运行图
DrawTrainDigram.DrawLineDigram(RAW, trainNum, stationNum, DirectionSign, StationPosition, LineID);

% 标记列车车次
DrawTrainDigram.MarkTrainNumber(RAW, trainNum, StationPosition, LineID);