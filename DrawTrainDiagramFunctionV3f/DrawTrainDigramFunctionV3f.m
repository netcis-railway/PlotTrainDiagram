%% 文件名称：DrawTrainDigramFunctionV3f.m
% 摘    要：基于v3f时刻表格式绘制列车运行图的自功能的实现函数
% 作    者：wurui
% 时间：2026年01月25日

%% 代码功能描述
% 本文件提供基于V3f版Excel列车时刻表绘制列车运行图的函数接口。
% 程序读取车站及列车到发时刻、线路信息和Seq顺序信息，识别列车运行方向，
% 计算各相邻车站间的等效间距，并绘制指定线路的运行图背景、列车运行线及车次标注。
% 横轴为一天内的时刻（秒），纵轴为沿线路排列的车站；下行列车以红色表示，
% 上行列车以蓝色表示。绘图入口通过本文件返回的函数句柄调用。
%
% 核心子程序：
%   DrawTrainDigramFunctionV3f  创建函数接口并注册可调用的子程序。
%   ReadTrainSchedule           读取V3f格式Excel时刻表，返回原始数据及列车、车站数量。
%   GetTrainTimeSegment         根据有效到发时刻确定运行图的起止小时。
%   JudgeUpOrDown               根据相邻车站的时刻先后判断各列车的运行方向。
%   GetStationInterval          统计各相邻车站区间的最小运行时间，供纵轴间距计算使用。
%   DrawBackground              按线路筛选车站，生成车站坐标并绘制运行图网格和坐标轴。
%   DrawDigram                  按时刻绘制全部列车运行线。
%   DrawLineDigram              按指定线路绘制运行线；有Seq时按其排序，否则按时刻排序，并生成图例。
%   MarkTrainNumber             在指定线路的列车起点附近标注车次。
%   parseTime                   将数值或文本格式的时刻转换为秒。
%   IsStationOnLine             判断车站的线路信息是否包含指定线路号。
% 典型调用流程：读取时刻表 -> 确定时间范围及列车方向 -> 计算站间距 ->
% 绘制背景坐标 -> 绘制线路运行线 -> 标注车次。详细参数及返回值见各子程序注释。

%% 接口函数：DrawTrainDigramFunction_v3f
%  接口名称：DrawTrainDigram
%  描    述：绘制列车运行图的所有函数的接口函数
function DrawTrainDigram = DrawTrainDigramFunctionV3f
    %读取列车时刻表的接口
    DrawTrainDigram.ReadTrainSchedule = @ReadTrainSchedule;

    %获取列车时刻表的时间区段
    DrawTrainDigram.GetTrainTimeSegment = @GetTrainTimeSegment;

    %判断上下行
    DrawTrainDigram.JudgeUpOrDown = @JudgeUpOrDown;

    %获取车站间的等效间距
    DrawTrainDigram.GetStationInterval = @GetStationInterval;

    %绘制列车运行图的背景线和坐标轴
    DrawTrainDigram.DrawBackground = @DrawBackground;

    %绘制列车运行图
    DrawTrainDigram.DrawDigram = @DrawDigram;
    
    %根据指定线路号绘制列车运行图
    DrawTrainDigram.DrawLineDigram = @DrawLineDigram;
    
    %标记所有列车车次编号
    DrawTrainDigram.MarkTrainNumber = @MarkTrainNumber;

    %根据基本图和调度图绘制对比运行图
    DrawTrainDigram.DrawLineDigramBasevsRescheduled = @DrawLineDigramBasevsRescheduled;
end

%% 函数名称：ReadTrainSchedule
%  描    述：读取以Excel形式存储的列车时刻表，时刻表的标准遵循版本V3f
%  输入参数：absoluteAddress:Excell的“绝对路径+文件名”
%  输出参数：RAW存储全部内容的元胞变量, NUM只有数据的元胞变量, trainNum, stationNum
%  调用函数：无
function [RAW, NUM, trainNum, stationNum] = ReadTrainSchedule(absoluteAddress, sheet)
    % [NUM, TXT, RAW] = xlsread('Test.xlsx'); %NUM读取的是数据(文本变为NAN)、TXT读取的是文本、RAW读取的未处理的数据
    % 此处 ~ 表示忽略TXT输出
    % 变量RAW中存储了全部的数据：数据、文本、字符
    [NUM, ~, RAW] = xlsread(absoluteAddress,sheet);
    [rawRow, rawColumn] = size(RAW); % 获取RAW表格的行列数

    stationNum = rawRow - 1; % 去掉第一行表头，其余行数为车站数
    trainNum = (rawColumn - 5) / 4; % 去掉前5列信息，之后每四列为一辆车
end

%% 函数名称：GetTrainTimeSegment
%  描    述：读取运行图起始时间和终止时间
%  输入参数：RAW原始单元格数据, trainNum列车数量, stationNum车站数量
%  输出参数：startHour运行图的起始时间, endHour运行图的终止时间
%  调用函数：无
function [startHour, endHour] = GetTrainTimeSegment(RAW, trainNum, stationNum)  % 由于v3f时刻表新增了seq列表示发车信息，无法直接使用NUM中最大最小值表示起始时间和终止时间
    %获取运行图时间轴的起点时间
    %时间转换的方法1：datestr(maxValue, 'HH:MM');
    %%进行时间转换，转成字符串，使用此方法会将月份打印成字符串，如一月为JAN，不适用于以下写的startHour = startHour(4)
    %时间转换的方法2："datevec”函数可以将数据准换成“[年 月 日 小时 分钟 秒]”6列数据，这是数字
    %测试语句：datevec(maxValue)
    %输出结果：0(年份只能打印出一位数字)     0     0    14    44     0

    times = []; % 初始化一个空数组，用于存储有效的到发时间

    % 得到纯到发时间数组
    for i = 1:trainNum % 遍历每一辆列车
        baseCol = 6 + (i - 1) * 4;  % 基准列为到达时间列
        for j = 2:stationNum+1 % 遍历每一个车站，需要跳过第一行因此从2开始
            t1 = RAW{j, baseCol};       % i车在j站的到达时间
            t2 = RAW{j, baseCol + 1};   % i车在j站的出发时间

            if isnumeric(t1), times(end+1) = t1; end    % t1和t2若是数值，则加入times数组中
            if isnumeric(t2), times(end+1) = t2; end
        end
    end

    % 起始时间为times数组中最小值的小时部分，终止时间为times数组中最大值的小时部分加1
    startHour = datevec(min(times));
    startHour = startHour(4);
    endHour = datevec(max(times));
    endHour = endHour(4) + 1;
end

%% 函数名称：JudgeUpOrDown
%  描    述：判断上下行
%  输入参数：RAW拥有全部内容的元胞变量, trainNum列车数量, stationNum车站数量
%  输出参数：DirectionSign上下行标志, 1表示下行, 2表示上行, 0表示只有一个站
%  调用函数：无

function [DirectionSign] = JudgeUpOrDown(RAW, trainNum, stationNum)
    DirectionSign = zeros(1, trainNum); % 初始化上下行标志, 默认为0

    for i=1:trainNum
        baseCol = 6 + (i - 1) * 4;  % 基准列为到达时间列

        for j=1:stationNum - 1
            % 获取j站到发时间，先取到达时间
            t1_arr = RAW{j+1, baseCol};       % i车在j站到达时间（第一行为表头需跳过）
            t1_dep = RAW{j+1, baseCol+1};     % i车在j站发车时间
            t1 = t1_arr;
            % 若到达时间为空则取发车时间
            if isnan(t1_arr)
                t1 = t1_dep;
            end

            % 获取j+1站到发时间，先取到达时间
            t2_arr = RAW{j+2, baseCol};       % j+1站到达时间
            t2_dep = RAW{j+2, baseCol+1};     % j+1站发车时间
            t2 = t2_arr;
            % 若到达时间为空则取发车时间
            if isnan(t2_arr)
                t2 = t2_dep;
            end

            if isnumeric(t1) && isnumeric(t2) && ~isnan(t1) && ~isnan(t2)   % t1和t2为数值但不是NAN时，检验时间有效性   
                % 将时间转化为秒数, 方便比较大小
                % datavec(t1)返回[年, 月, 日, 时, 分, 秒], 分别乘上权重转换成秒
                s1 = sum(datevec(t1) .* [0 0 0 3600 60 1]);
                s2 = sum(datevec(t2) .* [0 0 0 3600 60 1]);

                % 判断方向
                % 若s1 < s2, 则表示时间递增为下行, DirectionSign值为1，否则为上行设为2
                if s1 < s2
                    DirectionSign(i) = 1;
                else
                    DirectionSign(i) = 2;
                end

                break;  % 找到有效时间则退出内层循环
            end
        end
    end
end

%% 函数名称：GetStationInterval
%  描    述：读取列车时刻表中所有列车在同一两个站台间的最小运行时间t，作用是获取坐标轴的Y轴：车站间距
%            站台的真实间距可以等价于最小行驶时间乘以列车的行驶速度（330km/h），即s=vt,所以真实的间距的比值，就可以等价于最小行驶时间来代替了
%  输入参数：RAW全部内容的元胞变量, trainNum列车数量, stationNum站台数量, DirectionSign列车上下行方向
%  输出参数：minTravelTime最小行驶时间
%  调用函数：无
function [minTravelTime] = GetStationInterval(RAW, trainNum, stationNum, DirectionSign)
    % 初始化区间最小运行时间
    minTravelTime = zeros(1, stationNum - 1);

    for i = 1:stationNum - 1
        segTime = [];   % 初始化当前区段的列车运行时间

        for j = 1:trainNum
            baseCol = 6 + (j - 1) * 4;  % 基准列为到达时间列

            % 如果是下行列车
            if DirectionSign(j) == 1
                dep = RAW{i+1, baseCol+1};   % 第i站发车时间（第一行表头）
                arr = RAW{i+2, baseCol};     % 第i+1站到达时间

                % 检验时间有效性
                if isnumeric(dep) && isnumeric(arr) && ~isnan(dep) && ~isnan(arr)
                    % 将时间转换为秒
                    s1 = sum(datevec(dep).*[0 0 0 3600 60 1]);
                    s2 = sum(datevec(arr).*[0 0 0 3600 60 1]);
                    % 下行时若i+1站到达时间大于i站发车时间，则用i+1站到达时间减去i站发车时间，为此段区间的运行时间
                    if s2 > s1
                        segTime(end+1) = s2 - s1;
                    end
                end

            % 如果是上行列车
            elseif DirectionSign(j) == 1
                dep = RAW{i+2, baseCol+1};   % i+1站发车时间（第一行表头）
                arr = RAW{i+1, baseCol};     % i站到达时间

                % 检验时间有效性
                if isnumeric(dep) && isnumeric(arr) && ~isnan(dep) && ~isnan(arr)
                    % 将时间转换为秒
                    s1 = sum(datevec(dep).*[0 0 0 3600 60 1]);
                    s2 = sum(datevec(arr).*[0 0 0 3600 60 1]);
                    % 上行时若i站到达时间大于i+1站发车时间，则用i站到达时间减去i+1站发车时间，为此段区间的运行时间
                    if s2 > s1
                        segTime(end+1) = s2 - s1;
                    end
                end
            end

        end

        % 处理空区间
        % segTime不为空，则第i个区间的最小运行时间为所有列车在此区间的运行时间中的最小值
        if ~isempty(segTime)
            minTravelTime(i) = min(segTime);
        % 为空则说明之前出现了区间运行时间为负值的情况
        else
            % 使最小运行时间为一不可能出现的值66.66
            minTravelTime(i) = 66.66;
            % warndlg(['第' num2str(i) '个区间运行时间有误'])
        end

    end
end

%% 函数名称：DrawBackgrount
%  描    述：绘制列车运行图的背景线和坐标轴
%  输入参数：startHour运行图的起始时间, endHour运行图的终止时间, stationNum车站的个数， RAW全部内容的元胞变量
%  输出参数：无
%  调用函数：无
function [ StationPosition ] = DrawBackground(RAW, startHour, endHour, stationNum, minTravelTime, LineID)
    hold on

    % 找出属于该线路的车站
    % 使画图时只画出指定线路号经过的车站作为y轴
    validStations = [];
    % 若 LineID 为空，使用全部车站（不筛选线路）
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:stationNum;
    else
        for i = 1:stationNum
            % 第一行为表头，第二行开始的第四列为LineInfo
            LineInfo = RAW{i+1,4};
            % 若此站在指定的线路号上，加入validStations中
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = i;
            end
        end
    end
    % 计算真正需要画在图中的车站数量
    newStationNum = length(validStations);

    % 将minTravelTime转换为列向量
    minTravelTime = minTravelTime(:)';
    % 长度不足补0
    if length(minTravelTime) < stationNum-1
        minTravelTime(end+1:stationNum-1) = 0;
    end
    % 截取对应长度的minTravelTime
    minTravelTime = minTravelTime(1:stationNum-1);

    % 初始化newTravelTime用于保存有效区间
    newTravelTime = [];
    % 此时遍历所有有效经过车站
    for k = 1:newStationNum-1
        i1 = validStations(k);
        i2 = validStations(k+1);
        % 根据之前得到的所有区间的信息计算有效区间的最小运行时间
        newTravelTime(k) = minTravelTime(i1);
    end

    % 更新后使用的车站均为有效车站，应该不会出现0时，但保留此段0时处理处理
    nonZeroTimes = newTravelTime(newTravelTime > 0);
    if isempty(nonZeroTimes)
        minInterval = 60;
    else
        % 出现0用最小运行时间代替
        minInterval = min(nonZeroTimes);
    end

    newTravelTime(newTravelTime == 0) = minInterval;

    % 绘制y轴坐标和水平线时都应该改为newTravelTime的最小运行时间
    % 生成站点Y坐标
    StationPosition = [0 cumsum(newTravelTime)];

    % 绘制水平站线
    for i = 1:newStationNum
        line([0,endHour*3600], ...
             [StationPosition(i),StationPosition(i)], ...
             'color','g','LineWidth',0.25);
    end

    % 绘制整点竖线
    for i = 1:(endHour-startHour+1)
        tempHour = (startHour+i-1)*3600;
        line([tempHour,tempHour], ...
             [0,StationPosition(end)], ...
             'color','g','LineWidth',1.5);
    end

    % 绘制10分钟线
    for i = 1:(endHour-startHour+1)
        for j = 1:6
            tempHour = (startHour+i-1)*3600 + 600*(j-1);
            % j=4时为30分钟
            if j==4
                line([tempHour,tempHour], ...
                     [0,StationPosition(end)], ...
                     'LineStyle','--','color','g','LineWidth',0.25);
            else
                line([tempHour,tempHour], ...
                     [0,StationPosition(end)], ...
                     'color','g','LineWidth',0.25);
            end
        end
    end

    % 计算X轴刻度
    xStart = startHour*3600;
    xEnd   = endHour*3600;

    AxisXStr2 = strings(1,endHour-startHour+1);

    for i = 1:(endHour-startHour+1)
        AxisXStr2(i) = num2str(startHour+i-1) + ":00";
    end

    set(gca,'XLim',[xStart,xEnd]);
    set(gca,'XTick',xStart:3600:xEnd);
    set(gca,'XTickLabel',AxisXStr2);

    % y轴刻度改为有效车站
    % 计算Y轴刻度
    AxisYStr = cell(1,newStationNum);

    for k = 1:newStationNum
        i = validStations(k);
        AxisYStr{k} = RAW{i+1,5};
    end

    set(gca,'YLim',[0,StationPosition(end)]);
    set(gca,'YTick',StationPosition);
    set(gca,'YTickLabel',AxisYStr);
    set(gca,'YDir','reverse');
end

%% 函数名称：DrawDigram
%  描    述：根据时刻表的数据，每次外循环绘制一辆车的运行图
%  输入参数：trainNum列车数量, stationNum站台数量, RAW全部内容的元胞变量, 
%            DirectionSign上下行标识, StationPosition每个站点在y轴的坐标
%  输出参数：无
%  调用函数：无
function [ ] = DrawDigram(RAW, trainNum, stationNum, DirectionSign, StationPosition)
    hold on;
    colorMap = {'r', 'b'};   % 1=下行(红)，2=上行(蓝)

    for i = 1:trainNum
        baseCol = 6 + (i-1)*4;   % 基准列为到达列

        T = [];   % 用于保存时间（秒）
        Y = [];   % 用于保存站点坐标

        for j = 1:stationNum
            row = j + 1;   % 第一行为表头，车站从第二行开始

            if row > size(RAW,1)
                break;
            end

            arr = RAW{row, baseCol};  % 到达时间
            dep = RAW{row, baseCol+1};  % 发车时间

            % 到达时间坐标
            t = parseTime(arr);
            if ~isempty(t)
                T(end+1) = t;
                Y(end+1) = StationPosition(j);
            end

            % 发车时间坐标
            t = parseTime(dep);
            if ~isempty(t)
                T(end+1) = t;
                Y(end+1) = StationPosition(j);
            end
        end

        % 按时间进行排序 
        if numel(T) >= 2
            [T, idx] = sort(T);
            Y = Y(idx);

            % 下行使用红色，上行使用蓝色
            if DirectionSign(i) == 1
                plot(T, Y, colorMap{1}, 'LineWidth', 2); % 下行
            elseif DirectionSign(i) == 2
                plot(T, Y, colorMap{2}, 'LineWidth', 2); % 上行
            else
                plot(T, Y, 'k', 'LineWidth', 2);         % 未判定
            end
        end
    end
end

%% 函数名称：DrawLineDigram
%  描    述：根据时刻表的数据与指定的线路号，每次外循环绘制一辆车的运行图
%  输入参数：trainNum列车数量, stationNum站台数量, RAW全部内容的元胞变量, DirectionSign上下行标识, 
%             StationPosition每个站点在y轴的坐标, LineID为指定的线路号
%  输出参数：无
%  调用函数：parseTime()时间转换函数、IsStationOnLine()判断某站是否在指定线路上
function [ ] = DrawLineDigram(RAW, trainNum, stationNum, DirectionSign, StationPosition, LineID, colorMap)
    hold on;
    if nargin < 7 || isempty(colorMap)
        colorMap = {'r', 'b'};   % 默认 1=下行(红)，2=上行(蓝)
    end

    % 存放plot语句
    LineHandle = [];
    % 存放所有列车的车次号作为图例
    trainName = {};
    % 存放有效车站
    validStations = [];

    % 判断车站是否属于指定线路（LineID 为空时使用全部车站）
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:stationNum;
    else
        for j = 1:stationNum
            % 第一行为表头，第二行开始的第四列信息为LineInfo
            LineInfo = RAW{j+1,4};
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = j;
            end
        end
    end

    % 保存所有列车的车次号
    for i = 1:trainNum
        baseCol = 6 + (i-1)*4;   % 基准列为到达列
        
        % 从MarkTrainNumber移植，用于做legend
        header = RAW{1, baseCol}; % 提取车次号(表头行第1行，基准列)

        if ischar(header) || isstring(header)
            % 由于到达时间列以 _A 结尾，将_A去除只留车次号
            name = regexprep(string(header), '_A$', '');
        else
            continue; % 表头异常，跳过
        end

        T = [];   % 时间（秒）
        Y = [];   % 站点坐标
        Seq = []; % 保存Seq列信息

        % 只计算有效车站处的到发时间
        for k = 1:length(validStations)

            j = validStations(k);
            row = j + 1;   % 第一行为表头，车站从第二行开始

            if row > size(RAW,1)
                break;
            end

            arr = RAW{row, baseCol};  % 每一辆车的到达时间
            dep = RAW{row, baseCol+1};  % 每一辆车的发车时间
            seq = RAW{row, baseCol+3};  % 每一辆车的seq信息

            % 到达时间转为为秒
            t = parseTime(arr);
            if ~isempty(t)
                T(end+1) = t;
                Y(end+1) = StationPosition(k);

                % 判断seq值是否有效且是否为空
                if isnumeric(seq) && ~isnan(seq)
                    Seq(end+1) = seq;
                else
                    Seq(end+1) = NaN;
                end
            end

            % 发车时间转化为秒
            t = parseTime(dep);
            if ~isempty(t)
                T(end+1) = t;
                Y(end+1) = StationPosition(k);

                % 判断seq值是否有效且是否为空
                if isnumeric(seq) && ~isnan(seq)
                    % +0.1防止与到达时间的seq重复保证发车在前，到达在后
                    Seq(end+1) = seq + 0.1;
                else
                    Seq(end+1) = NaN;
                end
            end
        end

        % 按时间进行排序，根据排序结果得到最终的T(横)和Y(纵)坐标 
        if numel(T) >= 2
            % 若seq列信息全为空，则继续使用原来的对时间进行排序作图
            if all(isnan(Seq))
                [T, idx] = sort(T);
                Y = Y(idx);
            % 否则使用seq列信息进行排序
            else
                [~, idx] = sort(Seq);
                T = T(idx);
                Y = Y(idx);
            end

            % 画图，使用h存放plot句柄
            if DirectionSign(i) == 1
                h = plot(T, Y, colorMap{1}, 'LineWidth', 2); % 下行
            elseif DirectionSign(i) == 2
                h = plot(T, Y, colorMap{2}, 'LineWidth', 2); % 上行
            else
                h = plot(T, Y, 'k', 'LineWidth', 2);         % 未判定
            end

            % 保存plot语句
            LineHandle(end+1) = h;
            % 保存所有车的车次号
            trainName{end+1} = char(name);
        end
    end

    % 遍历完所有车后生成图例
    if ~isempty(LineHandle)
        % 生成图例，位置选择：'BestOutside'图像外；'NorthEast'图像右上方
        legend(LineHandle, trainName, 'Location', 'BestOutside');
    end
end


%% 函数名称：DrawLineDigramBasevsRescheduled
%  开发者： 李仁龙
%  描    述：根据基本计划时刻表和调度计划时刻表（均为 v3f 格式 RAW 数据），
%           在同一张图上对比绘制运行图 —— 基本图黑色，调度图红/蓝（下行红，上行蓝）
%  输入参数：RAW_base, trainNum_base — 基本计划时刻表 v3f 数据
%            RAW_res,  trainNum_res  — 调度计划时刻表 v3f 数据
%            stationNum             — 车站数量
%            LineID                 — 指定线路号（默认=1，'' 表示全线）
%  输出参数：StationPosition        — 站点 Y 轴坐标
%  调用函数：GetTrainTimeSegment, JudgeUpOrDown,
%            GetStationInterval, DrawBackground, DrawLineDigram, MarkTrainNumber
function [StationPosition] = DrawLineDigramBasevsRescheduled(RAW_base, trainNum_base, ...
                                                              RAW_res, trainNum_res, ...
                                                              stationNum, LineID)

    % 设置默认线路号（仅未传入时默认=1；空字符串''表示全线不筛选，保留原值）
    if nargin < 6
        LineID = 1;
    end

    % ============ (1) 获取合并时间范围 ============
    [startHour_base, endHour_base] = GetTrainTimeSegment(RAW_base, trainNum_base, stationNum);
    [startHour_res, endHour_res] = GetTrainTimeSegment(RAW_res, trainNum_res, stationNum);
    startHour = min(startHour_base, startHour_res);
    endHour   = max(endHour_base, endHour_res);

    % ============ (2) 判断上下行 ============
    DirectionSign_base = JudgeUpOrDown(RAW_base, trainNum_base, stationNum);
    DirectionSign_res  = JudgeUpOrDown(RAW_res, trainNum_res, stationNum);

    % ============ (3) 以基本图为基准计算站间距 ============
    minTravelTime = GetStationInterval(RAW_base, trainNum_base, stationNum, DirectionSign_base);

    % ============ (4) 以基本图为基准绘制背景网格和坐标轴 ============
    StationPosition = DrawBackground(RAW_base, startHour, endHour, stationNum, minTravelTime, LineID);

    % ============ (5) 绘制基本计划运行图（黑色） ============
    colorMap_base = {'k', 'k'};   % 基本图全部采用黑色
    DrawLineDigram(RAW_base, trainNum_base, stationNum, DirectionSign_base, StationPosition, LineID, colorMap_base);

    % ============ (6) 绘制调度计划运行图（下行红色，上行蓝色） ============
    colorMap_res = {'r', 'b'};   % 1=下行(红)，2=上行(蓝)
    DrawLineDigram(RAW_res, trainNum_res, stationNum, DirectionSign_res, StationPosition, LineID, colorMap_res);

    % ============ (7) 标记车次号（只标注一次） ============
    MarkTrainNumber(RAW_base, trainNum_base, StationPosition, LineID);
end

%% 函数名称：MarkTrainNumber
%  描    述：标记列车车次
%  输入参数：RAW, trainNum, StationPosition, LineID
%  输出参数：
%  调用函数：
function [ ] = MarkTrainNumber(RAW, trainNum, StationPosition, LineID)
    % 存放有效车站
    validStations = [];
    % 判断某站是否处于指定线路（LineID 为空时使用全部车站）
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:size(RAW,1)-1;
    else
        for j = 2:size(RAW,1)
            LineInfo = RAW{j,4};
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = j-1;
            end
        end
    end

    for i = 1:trainNum
        baseCol = 6 + (i - 1) * 4;  % 基准列为到达时间列
        header = RAW{1, baseCol}; % 提取车次号(表头行第1行，基准列)

        if ischar(header) || isstring(header)
            % 由于到达时间列以 _A 结尾，将_A去除只留车次号
            name = regexprep(string(header), '_A$', '');
        else
            continue; % 表头异常，跳过
        end

        times = []; % 存储该列车到达时间
        rows = [];  % 存储到达时间对应行号


        % 遍历RAW的所有行(跳过表头从第二行开始)
        for j = 2:size(RAW, 1)

            % 判断车站是否属于当前线路（LineID 为空时不过滤）
            if ~(isempty(LineID) || (ischar(LineID) && strlength(LineID)==0))
                LineInfo = RAW{j, 4};    % 第4列第j行为j站的LineInfo信息
                % 若不在指定线路号，则直接判断下一个车站
                if ~IsStationOnLine(LineInfo, LineID)
                    continue;
                end
            end

            if isnumeric(RAW{j, baseCol}) && ~isnan(RAW{j, baseCol})
                times(end+1) = RAW{j, baseCol};
                rows(end+1) = j;
            end
        end

        % 若无有效到达时间则跳过该车次
        if isempty(times)
            continue;
        end
        [~, idx] = min(times);  % 获得最早的到达时间的索引值
        t = datevec(times(idx));
        x = t(4) * 3600 + t(5) * 60 + t(6) - 50;    % 计算x坐标并左移50, 防止重合

        % rows(idx)-2：行号转站点序号（行2=站点1，行3=站点2…）
        % StationPosition(end - 站点序号)：反向匹配站点Y坐标
        stationIdx = rows(idx) - 1; % 第2行为第1站
        % 只记录有效站的信息
        k = find(validStations == stationIdx);
        
        if isempty(k)
            continue;
        end

        % ↓此处进行了修改，因为此前将车站名反转 y = StationPosition(end - stationIdx + 1) + 80;
        % 且只使用有效站位置作为y坐标，防止无关车次的车次号悬空
        y = StationPosition(k) - 80;
                % 在(x,y)位置标注列车名称，字号15
                text(x, y, name, 'FontSize', 15);
            end
        end

%% 函数名称：parseTime
%  描    述：时间转换函数，将RAW中时间转换为秒
%  输入参数：x RAW中的到发时间
function tsec = parseTime(x)
    tsec = [];

    if isnumeric(x) && ~isnan(x)
        %时间转换的方法2："datevec”函数可以将数据准换成“[年 月 日 小时 分钟 秒]”6列数据，这是数字
        %测试语句：datevec(maxValue)
        %输出结果：0(年份只能打印出一位数字)     0     0    14    44     0
        v = datevec(x);
    elseif ischar(x) || isstring(x)
        try
            v = datevec(x);
        catch
            return;
        end
    else
        return;
    end

    % 将时、分、秒对应乘系数相加得到秒为单位时间
    tsec = v(4)*3600 + v(5)*60 + v(6);
end
  

%% 函数名称：IsStationOnLine
%  描    述：根据LineInfo信息判断某站是否属于指定线路号LineID
%  输入参数：时刻表第四列线路号信息LineInfo, 指定线路号LineID

% ↓旧版，只能够输入整数型LineID
% function flag = IsStationOnLine(LineInfo, LineID)
%     % 从RAW读取的LineInfo有两种形式：单独一条线时为整数型1或2，共线时为字符串型'1,2'
%     flag = false;
% 
%     % 若是整数型则直接判断是否与给定的LindID相同，若相同标志位设为True
%     if isnumeric(LineInfo)
%         if LineInfo == LineID
%             flag = true;
%         end
% 
%     % 若是字符串型
%     elseif ischar(LineInfo) || isstring(LineInfo)
% 
%         lineStr = char(LineInfo);
%         % 按照','进行分割
%         parts = strsplit(lineStr,',');
% 
%         % 遍历分割后得到的所有字符，与LineID进行比较
%         for k = 1:length(parts)
% 
%             if str2double(parts{k}) == LineID
%                 flag = true;
%                 return
%             end
%         end
%     end
% end

% ↓新版，能够输入整数型也能够输入字符串型
% 将LineInfo和LineID都解析为列表，两个列表有交集则说明此站属于指定线路
function flag = IsStationOnLine(LineInfo, LineID)
    flag = false;

    % 将LineInfo转化为列表
    if isnumeric(LineInfo)
        InfoList = LineInfo;

    elseif ischar(LineInfo) || isstring(LineInfo)
        % 按照','进行分割
        parts = strsplit(char(LineInfo),',');
        InfoList = str2double(parts);

    else
        InfoList = [];
    end

    % 相同方法将LineID转化为列表
    if isnumeric(LineID)
        IdList = LineID;

    elseif ischar(LineID) || isstring(LineID)
        % 按照','进行分割
        parts = strsplit(char(LineID),',');
        IdList = str2double(parts);

    else
        IdList = [];
    end

    % 判断两列表是否有交集
    if ~isempty(intersect(InfoList, IdList))
        flag = true;
    end
end


