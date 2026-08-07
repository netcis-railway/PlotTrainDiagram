%% 文件名称：DrawTrainDigramFunction.m
% 摘    要：基于v3f时刻表格式绘制列车运行图的自功能的实现函数
% 作    者：rui
% 时间：2026年01月25日

% 2026年03月11日：
% 调整上下行逻辑，修改一些错误，增加异常处理; 对DrawDigram新增输入参数color，以便绘制对比图

% 2026年03月12日：
% 新增DrawLineDigram函数、IsStationOnLine函数，用于画指定线路号的运行图；根据制定线路号LineID修改MarkTrainNumber函数，解决车次号悬浮在空白处问题
% 修改IsStationOnLine函数，使输入单线路和多线路(str型)时都能判断

% 2026年03月13日：
% 修改了DrawBackground、DrawLineDigram、MarkTrainNumber函数，画图时y轴仅显示有效车站；删去输入参数color，固定下行使用红色，上行使用蓝色
% 修改了DrawLineDigram，新增功能：当seq列为空时按照时间顺序画图，当seq列有值时按seq顺序画图

% 2026年4月3日
% 修改了适配后缀_A和_a的两种形式
% 新增函数HighlightTrainLines，作用是输入一个车次号字符串，车次号间以逗号隔开，高亮这些车的运行线，让DrawLineDigram返回对应的句柄和车次名，之后在HighlightTrainLines中用
% 修改DrawBackground函数，使之能够处理LineID为空情况，代表不筛选线路，使用全部车站
% 新增函数ConvertV3toV3f，将v3时刻表自动转换为v3f时刻表，在主函数中增加了v3f时刻表的输出
%% 接口函数：DrawTrainDigramFunction
%  接口名称：DrawTrainDigram
%  描    述：绘制列车运行图的所有函数的接口函数
function DrawTrainDigram = DrawTrainDigramFunction_v3f_v5
    % 将v3时刻表转换为v3f时刻表
    DrawTrainDigram.ConvertV3toV3f = @ConvertV3toV3f;
    % 读取列车时刻表的接口
    DrawTrainDigram.ReadTrainSchedule = @ReadTrainSchedule;
    % 获取列车时刻表的时间区段
    DrawTrainDigram.GetTrainTimeSegment = @GetTrainTimeSegment;
    % 判断上下行
    DrawTrainDigram.JudgeUpOrDown = @JudgeUpOrDown;
    % 获取车站间的等效间距
    DrawTrainDigram.GetStationInterval = @GetStationInterval;
    % 绘制列车运行图的背景线和坐标轴
    DrawTrainDigram.DrawBackground = @DrawBackground;
    % 绘制红色的列车运行图
    DrawTrainDigram.DrawDigram = @DrawDigram;
    % 根据线路号绘制指定颜色的列车运行图
    DrawTrainDigram.DrawLineDigram = @DrawLineDigram;
    % 标记所有列车车次编号
    DrawTrainDigram.MarkTrainNumber = @MarkTrainNumber;
    % 根据指定车次号字符串对对应运行线做高亮处理
    DrawTrainDigram.HighlightTrainLines = @HighlightTrainLines;
    % 将输出excel时的以秒为单位的时间转换回日期时间格式
    DrawTrainDigram.RAWtoDateTime = @RAWtoDateTime;
    % 根据指定颜色绘制列车运行图（不区分上下行颜色）
    DrawTrainDigram.DrawLineDigramColor = @DrawLineDigramColor;
    % 根据指定颜色标记列车车次
    DrawTrainDigram.MarkTrainNumberColor = @MarkTrainNumberColor;
    % 根据时间区间和车站区间重构v3f时刻表
    DrawTrainDigram.RebuildV3fByScope = @RebuildV3fByScope;
end

%% 函数名称：ConvertV3toV3f
%  描    述：将v3时刻表转换为v3f时刻表
%  输入参数：absoluteAddress:Excell的“绝对路径+文件名”
%  输出参数：RAW存储全部内容的元胞变量, NUM只有数据的元胞变量, trainNum, stationNum
%  调用函数：无
function RAW_v3f = ConvertV3toV3f(RAW_v3)
    % 读取v3时刻表的所有行与列
    [row, col] = size(RAW_v3);

    % 基于v3时刻表的基础信息
    stationNum = row - 1;       % 第一行表头
    trainNum = (col - 3) / 3;   % 前三列为信息列，之后每三列为一辆车

    % v3f新表大小
    newCol = 5 + trainNum * 4;
    RAW_v3f = cell(row, newCol);    % 行数不变仅改变列数

    % 处理v3f前5列基础信息
    % v3f的前五列表头信息
    RAW_v3f(1,1:5) = {'NODE_NAME_SHORT','NODE_ID','NODE_CODE','LINE_IND','NODE_NAME'};
    % 从第二列开始遍历所有列
    for i = 2:row
        RAW_v3f{i,1} = '';                    % NODE_NAME_SHORT 先置空
        RAW_v3f{i,2} = RAW_v3{i,1};           % NODE_ID 与v3的第一列相同
        RAW_v3f{i,3} = RAW_v3{i,2};           % NODE_CODE 与v3的第二列相同
        RAW_v3f{i,4} = [];                    % LINE_IND 设置为空[]，适配之后的LineID的索引
        RAW_v3f{i,5} = RAW_v3{i,3};           % NODE_NAME 与v3的第三列相同
    end

    % 处理每一辆车的列信息
    for t = 1:trainNum
        oldBase = 4 + (t-1)*3;  % v3时刻表每辆车的基准列（到达时间列）
        newBase = 6 + (t-1)*4;  % v3f时刻表每辆车的基准列（到达时间列）

        % v3车辆信息表头
        nameA = RAW_v3{1, oldBase};
        nameD = RAW_v3{1, oldBase+1};
        nameG = RAW_v3{1, oldBase+2};

        RAW_v3f{1,newBase}   = nameA;
        RAW_v3f{1,newBase+1} = nameD;
        RAW_v3f{1,newBase+2} = nameG;
        RAW_v3f{1,newBase+3} = regexprep(nameA,'[_Aa]$','_SEQ');

        % 到发时间数据复制
        times = [];   % 存储时间
        rows_idx = []; % 对应行号

        for i = 2:row
            A = RAW_v3{i, oldBase};
            D = RAW_v3{i, oldBase+1};
            G = RAW_v3{i, oldBase+2};

            % 写入新v3f表
            RAW_v3f{i,newBase}   = A;
            RAW_v3f{i,newBase+1} = D;
            RAW_v3f{i,newBase+2} = G;

            % 收集有效时间（数值型，优先A，其次D）
            if isnumeric(A) && ~isnan(A)
                times(end+1) = A;
                rows_idx(end+1) = i;
            elseif isnumeric(D) && ~isnan(D)
                times(end+1) = D;
                rows_idx(end+1) = i;
            end
        end

        % 新增SEQ列
        seq_col = nan(row,1);
        if ~isempty(times)
            % 转秒排序
            time_sec = zeros(size(times));

            for k = 1:length(times)
                v = datevec(times(k));
                time_sec(k) = v(4)*3600 + v(5)*60 + v(6);
            end

            [~, order] = sort(time_sec);

            for k = 1:length(order)
                idx = rows_idx(order(k));
                seq_col(idx) = k;
            end
        end

        % 写入SEQ列
        for i = 2:row
            RAW_v3f{i,newBase+3} = seq_col(i);
        end
    end
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
%  输出参数：DirectionSign上下行标志, 1表示下行, 2表示上行, 0表示只有一个站或SEQ值缺失
%  调用函数：无

function [DirectionSign] = JudgeUpOrDown(RAW, trainNum, stationNum)
%     %使用seq列判断当前时刻表是上行还是下行
%     DirectionSign = zeros(1, trainNum); % 初始化上下行标志, 默认为0
% 
%     for i = 1:trainNum
%         seqCol = 6 + (i - 1) * 4 + 3;
% 
%         for j = 2:stationNum
%             seq1 = RAW{j, seqCol};
%             seq2 = RAW{j + 1, seqCol};
% 
%             if isnumeric(seq1) && isnumeric(seq2) && ~isnan(seq1) && ~isnan(seq2)
%                 if seq2 > seq1
%                     DirectionSign(i) = 2;   % seq从上到下递增属于下行
%                 elseif seq2 < seq1
%                     DirectionSign(i) = 1;   % seq从上到下递减属于上行
%                 end
%                 DirectionSign(i)
%                 break;
%             end
%         end
%     end
% end


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
            elseif DirectionSign(j) == 2
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
% function [ StationPosition ] = DrawBackground(RAW, startHour, endHour, stationNum, minTravelTime)
%     %line(X,Y)——line([1,2],[3,4])将画出（1,3）到(2,4)的一条直线，而不是(1,2)到(3,4)
%     % figure(1); % 打开图像窗口
%     %绘制水平的背景线
%     StationPosition = [0 cumsum(minTravelTime(1:stationNum-1))];
%     StationPosition
% 
%     %绘制竖直的背景线
%     %整1小时
%     for i=1:(endHour - startHour + 1)
%         tempHour = (startHour + i - 1) * 3600;
%         hold on;
%         line([tempHour, tempHour],[0, StationPosition(1, stationNum)],'color','g','LineWidth',1.5);
%     end
%     %整10分钟
%     for i=1:(endHour - startHour + 1)  % （endHour - startHour + 1）条小时线，
%         for j=1:6  % 没两个小时线间6条10分钟线
%             tempHour = (startHour + i - 1) * 3600 + 600*(j - 1);
%             hold on;
%             %30分钟处画虚线
%             if j == 4
%                 line([tempHour, tempHour],[0, StationPosition(1, stationNum)],'LineStyle','--','color','g','LineWidth',0.25);
%             else
%                 line([tempHour, tempHour],[0, StationPosition(1, stationNum)],'color','g','LineWidth',0.25);
%             end
% 
%         end
%     end
%     
%     %动态获取时间刻度
%     AxisXStr = zeros(1, endHour - startHour + 1);
%     for i=1:(endHour - startHour + 1)
%         AxisXStr(1, i) = startHour + i - 1; %获取对应时间刻度的序列
%     end
%     AxisXStr2 = strings(1,endHour - startHour + 1);
%     for i=1:(endHour - startHour + 1)
%         AxisXStr2(1, i) = num2str(AxisXStr(1, i))+":00";
%     end
%     xStart = startHour*3600;
%     xEnd = endHour*3600;
%     set(gca,'XLim',[xStart, xEnd]); %设置X轴的显示范围
%     set(gca,'XTick',xStart:3600:xEnd); %设置要显示的刻度
%     set(gca,'XTickLabel',AxisXStr2(1,:)); %将刻度的标签替换成新的标签
% %     set(gca,'FontSize',15);
% %     xlabel('Time');
% %     ylabel('Station')
% 
%     %动态获取车站刻度
%     AxisYStr = cell(1, stationNum);
%     for i=1:stationNum
%         AxisYStr{i} = RAW{i+1, 5}; %获取对应时间刻度的序列
%     end
%     yStart = 0;
%     yEnd = sum(minTravelTime);
%     set(gca,'YLim',[yStart, yEnd]); %设置Y轴的显示范围
%     set(gca,'YTick',StationPosition); %设置要显示的刻度
%     set(gca,'YTickLabel',AxisYStr(1,:)); %将刻度的标签替换成新的标签
%     
% end


function [ StationPosition ] = DrawBackground(RAW, startHour, endHour, stationNum, minTravelTime, LineID)

    hold on

    % ===== 找出属于该线路的车站 =====
    % 使画图时只画出指定线路号经过的车站作为y轴
    validStations = [];

    % 若输入LineID为空时，有效车站为所有车站
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:stationNum;
    % 若输入LineID不为空，则根据第四列LINEIND筛选
    else
        for i = 1:stationNum
            % 第一行为表头，第二行开始的第四列为LINEIND
            LineInfo = RAW{i+1,4};
            % 若此站在指定的线路号上，加入validStations中
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = i;
            end
        end
    end

    % 计算真正需要画在图中的车站数量
    newStationNum = length(validStations);

    % ===== 保证minTravelTime可用 =====
    minTravelTime = minTravelTime(:)';

    if length(minTravelTime) < stationNum-1
        minTravelTime(end+1:stationNum-1) = 0;
    end

    minTravelTime = minTravelTime(1:stationNum-1);

    % ===== 只提取有效区间 =====
    newTravelTime = [];
    % 此时遍历所有有效经过车站
    for k = 1:newStationNum-1
        i1 = validStations(k);
        i2 = validStations(k+1);
        % 根据之前得到的所有区间的信息计算有效区间的最小运行时间
        newTravelTime(k) = minTravelTime(i1);

    end

    % ===== 处理0时间 =====
    % 更新后使用的车站均为有效车站，应该不会出现0时，但保留此段处理
    nonZeroTimes = newTravelTime(newTravelTime > 0);
    if isempty(nonZeroTimes)
        minInterval = 60;
    else
        minInterval = min(nonZeroTimes);
    end

    newTravelTime(newTravelTime == 0) = minInterval;

    % 绘制y轴坐标和水平线时都应该改为newTravelTime的最小运行时间
    % ===== 生成站点Y坐标 =====
    StationPosition = [0 cumsum(newTravelTime)];

    % ===== 绘制水平站线 =====
    for i = 1:newStationNum
        line([0,endHour*3600], ...
             [StationPosition(i),StationPosition(i)], ...
             'color','g','LineWidth',0.25);
    end

    % ===== 绘制整点竖线 =====
    for i = 1:(endHour-startHour+1)
        tempHour = (startHour+i-1)*3600;
        line([tempHour,tempHour], ...
             [0,StationPosition(end)], ...
             'color','g','LineWidth',1.5);
    end

    % ===== 绘制10分钟线 =====
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

    % ===== X轴刻度 =====
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
    % ===== Y轴刻度 =====
    AxisYStr = cell(1,newStationNum);

    for k = 1:newStationNum
        i = validStations(k);
        AxisYStr{k} = RAW{i+1,5};
    end

    if length(StationPosition) < 2
        set(gca,'YLim',[0,1]);   % 防止崩溃
    else
        set(gca,'YLim',[0,StationPosition(end)]);
    end
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
    % 绘制列车运行轨迹（按上下行区分颜色）
    % 输入：trainNum-列车数, stationNum-站点数, DirectionSign-上下行标识, StationPosition-站点Y坐标, RAW-原始元胞数据
    % 输出：无（绘图）

    hold on;
    colorMap = {'r', 'b'};   % 1=下行(红)，2=上行(蓝)

    for i = 1:trainNum
        baseCol = 6 + (i-1)*4;   % 基准列为到达列

        T = [];   % 时间（秒）
        Y = [];   % 站点坐标

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

%     for i = 1:trainNum
%         baseCol = 6 + (i - 1) * 4;
%         X = []  % 存储当前列车的时间(秒)
%         Y = []  % 存储当前列车的站点坐标
% 
%         for j = 1:stationNum
%             arr = RAW{j+1, baseCol}; % j+1跳过表头
%             dep = RAW{j+1, baseCol+1};
%            
%             if isnumeric(arr) && ~isnan(arr)
%                 s = sum(datevec(arr) .* [0 0 0 3600 60 1]);
%                 X(end + 1) = s;
%                 
% end

%% 函数名称：DrawLineDigram
%  描    述：根据时刻表的数据与指定的线路号，每次外循环绘制一辆车的运行图
%  输入参数：trainNum列车数量, stationNum站台数量, RAW全部内容的元胞变量, DirectionSign上下行标识, 
%             StationPosition每个站点在y轴的坐标, LineID为指定的线路号
%  输出参数：无
%  调用函数：parseTime()时间转换函数、IsStationOnLine()判断某站是否在指定线路上
function [ LineHandle, trainName ] = DrawLineDigram(RAW, trainNum, stationNum, DirectionSign, StationPosition, LineID)
    % 绘制列车运行轨迹（按上下行区分颜色）
    % 输入：trainNum-列车数, stationNum-站点数, DirectionSign-上下行标识, StationPosition-站点Y坐标, RAW-原始元胞数据
    % 输出：LineHandle-plot语句句柄, trainName-列车的车次号(之后用于高亮指定车次号)

    hold on;
    colorMap = {'r', 'b'};   % 1=下行(红)，2=上行(蓝)

    % 存放plot语句
    LineHandle = {};
    % 存放所有列车的车次号作为图例
    trainName = {};
    % 存放有效车站
    validStations = [];

    % 判断车站是否属于指定线路
    % 若输入LineID为空时，有效车站为所有车站
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:stationNum;
    % 若输入LineID不为空，则根据第四列LINEIND筛选
    else
        for i = 1:stationNum
            % 第一行为表头，第二行开始的第四列为LINEIND
            LineInfo = RAW{i+1,4};
            % 若此站在指定的线路号上，加入validStations中
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = i;
            end
        end
    end

    % 保存所有列车的车次号
    for i = 1:trainNum
        baseCol = 6 + (i-1)*4;   % 基准列为到达列
        
        % 从MarkTrainNumber移植
        header = RAW{1, baseCol}; % 提取车次号(表头行第1行，基准列)

        if ischar(header) || isstring(header)
            % 由于到达时间列以 _A或_a 结尾，将后缀去除只留车次号
            name = regexprep(string(header), '[Aa]$', '');
            name = regexprep(name, '_$', '');
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
            LineHandle{end+1} = h;
            % 保存所有车的车次号
            trainName{end+1} = char(name);
        end
    end

    % 遍历完所有车后生成图例
    if ~isempty(LineHandle)
        % 生成图例，位置选择：'BestOutside'图像外；'NorthEast'图像右上方
        legend([LineHandle{:}], trainName, 'Location', 'BestOutside');
    end
end

%     for i = 1:trainNum
%         baseCol = 6 + (i - 1) * 4;
%         X = []  % 存储当前列车的时间(秒)
%         Y = []  % 存储当前列车的站点坐标
% 
%         for j = 1:stationNum
%             arr = RAW{j+1, baseCol}; % j+1跳过表头
%             dep = RAW{j+1, baseCol+1};
%            
%             if isnumeric(arr) && ~isnan(arr)
%                 s = sum(datevec(arr) .* [0 0 0 3600 60 1]);
%                 X(end + 1) = s;
%                 
% end

%% 函数名称：MarkTrainNumber
%  描    述：标记列车车次
%  输入参数：RAW, trainNum, StationPosition, LineID
%  输出参数：
%  调用函数：
function [ ] = MarkTrainNumber(RAW, trainNum, stationNum, StationPosition, LineID)
    % 存放有效车站
    validStations = [];
    % 若输入LineID为空时，有效车站为所有车站
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:stationNum;
    % 若输入LineID不为空，则根据第四列LINEIND筛选
    else
        for i = 1:stationNum
            % 第一行为表头，第二行开始的第四列为LINEIND
            LineInfo = RAW{i+1,4};
            % 若此站在指定的线路号上，加入validStations中
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = i;
            end
        end
    end

    for i = 1:trainNum
        baseCol = 6 + (i - 1) * 4;  % 基准列为到达时间列
        header = RAW{1, baseCol}; % 提取车次号(表头行第1行，基准列)

        if ischar(header) || isstring(header)
            % 由于到达时间列以 _A 结尾，将_A去除只留车次号
            name = regexprep(string(header), '[Aa]$', '');
            name = regexprep(name, '_$', '');
        else
            continue; % 表头异常，跳过
        end
            
        times = []; % 存储该列车到达时间
        rows = [];  % 存储到达时间对应行号

    
        % 遍历RAW的所有行(跳过表头从第二行开始)
        for j = 2:size(RAW, 1)
            % 新增：判断车站是否属于当前线路，找到当前线路最早的到达站
            LineInfo = RAW{j, 4};    % 第4列第j行为j站的LineInfo信息

            % 若不在指定线路号，则直接判断下一个车站
            if ~(isempty(LineID) || (ischar(LineID) && strlength(LineID)==0))
                if ~IsStationOnLine(LineInfo, LineID)
                    continue;
                end
            end

            if isnumeric(RAW{j, baseCol}) && ~isnan(RAW{j, baseCol})
                times(end+1) = RAW{j, baseCol};
                rows(end+1) = j;
            end
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


%% 函数名称：HighlightTrainLines
%  描    述：根据指定车次号字符串targetStr高亮对应运行线
%  输入参数：LineHandle, trainName, targetStr
%  输出参数：
%  调用函数：
function [ ] = HighlightTrainLines(LineHandle, trainName, targetStr)
    % 解析字符串，以,进行分隔
    targetList = strsplit(targetStr, ',');
    targetList = strtrim(targetList);

    % 遍历所有列车
    for i = 1:length(trainName)
        % 若解析出的车次号为当前遍历车次号
        if any(strcmp(trainName{i}, targetList))
            % 修改图形属性
            if isgraphics(LineHandle{i})
                % 线宽3.0，颜色为黑色
                set(LineHandle{i}, ...
                    'Color', 'k', ...
                    'LineWidth', 3.0);
            end
        end
    end
end

%% 函数名称：RebuildV3fByScope
%  描    述：根据用户输入的起止时间和起止车站重构v3f时刻表，仅保留区间内出现的车辆信息
%  输入参数：
%      RAW: v3f格式元胞数据
%      trainNum: 车辆数量（可传空[]，函数内部自动计算）
%      startTimeInput: 起始时间，支持''/char/string/datetime/Excel序列值
%      endTimeInput:   结束时间，支持''/char/string/datetime/Excel序列值
%      startStationInput: 起始车站，支持''/NODE_CODE/NODE_NAME/NODE_ID(数值或字符串)
%      endStationInput:   结束车站，支持''/NODE_CODE/NODE_NAME/NODE_ID(数值或字符串)
%  输出参数：
%      RAW_filtered: 重构后的v3f时刻表（时间仍为Excel序列值）
%      RAW_filtered_date: 重构后的v3f时刻表（到发时间为datetime）
%      trainNum_filtered: 重构后车辆数
%      stationNum_filtered: 重构后车站数
function [RAW_filtered, RAW_filtered_date, trainNum_filtered, stationNum_filtered] = ...
    RebuildV3fByScope(RAW, trainNum, startTimeInput, endTimeInput, startStationInput, endStationInput)

    [rawRow, rawCol] = size(RAW);
    stationNum = rawRow - 1;

    if nargin < 2 || isempty(trainNum)
        trainNum = floor((rawCol - 5) / 4);
    end

    % ---------- 计算车站区间 ----------
    startStationIdx = 1;
    endStationIdx = stationNum;

    if ~(ischar(startStationInput) && isempty(startStationInput)) && ...
       ~(isstring(startStationInput) && strlength(startStationInput)==0) && ...
       ~isempty(startStationInput)
        startStationIdx = locateStationIndex(RAW, stationNum, startStationInput);
    end

    if ~(ischar(endStationInput) && isempty(endStationInput)) && ...
       ~(isstring(endStationInput) && strlength(endStationInput)==0) && ...
       ~isempty(endStationInput)
        endStationIdx = locateStationIndex(RAW, stationNum, endStationInput);
    end

    if startStationIdx > endStationIdx
        temp = startStationIdx;
        startStationIdx = endStationIdx;
        endStationIdx = temp;
    end

    selectedStationRows = (startStationIdx + 1):(endStationIdx + 1); % +1跳过表头

    % ---------- 获取全表时间边界 ----------
    allTimes = [];
    for i = 1:trainNum
        baseCol = 6 + (i - 1) * 4;
        for r = 2:stationNum+1
            arr = RAW{r, baseCol};
            dep = RAW{r, baseCol + 1};

            if isnumeric(arr) && ~isnan(arr)
                allTimes(end+1) = arr; %#ok<AGROW>
            end
            if isnumeric(dep) && ~isnan(dep)
                allTimes(end+1) = dep; %#ok<AGROW>
            end
        end
    end

    if isempty(allTimes)
        error('RebuildV3fByScope:NoValidTime', '原始时刻表中未找到有效到发时间。');
    end

    minTime = min(allTimes);
    maxTime = max(allTimes);

    % ---------- 解析用户输入时间（统一转换为当天秒数比较） ----------
    startSec = parseTimeInputToSecondOfDay(startTimeInput, excelSerialToSecondOfDay(minTime));
    endSec = parseTimeInputToSecondOfDay(endTimeInput, excelSerialToSecondOfDay(maxTime));

    % ---------- 选车：车站区间内有任一到发时间落入时间区间则保留 ----------
    selectedTrainIdx = [];
    for i = 1:trainNum
        baseCol = 6 + (i - 1) * 4;
        keepThisTrain = false;

        for r = selectedStationRows
            arr = RAW{r, baseCol};
            dep = RAW{r, baseCol + 1};

            arrValid = false;
            depValid = false;

            if isnumeric(arr) && ~isnan(arr)
                arrSec = excelSerialToSecondOfDay(arr);
                arrValid = isSecondInWindow(arrSec, startSec, endSec);
            end
            if isnumeric(dep) && ~isnan(dep)
                depSec = excelSerialToSecondOfDay(dep);
                depValid = isSecondInWindow(depSec, startSec, endSec);
            end

            if arrValid || depValid
                keepThisTrain = true;
                break;
            end
        end

        if keepThisTrain
            selectedTrainIdx(end+1) = i; %#ok<AGROW>
        end
    end

    % ---------- 重构新v3f ----------
    trainNum_filtered = length(selectedTrainIdx);
    stationNum_filtered = length(selectedStationRows);
    newCol = 5 + 4 * trainNum_filtered;

    RAW_filtered = cell(stationNum_filtered + 1, newCol);

    % 基础信息列
    RAW_filtered(1,1:5) = RAW(1,1:5);
    RAW_filtered(2:end,1:5) = RAW(selectedStationRows,1:5);

    % 车辆列（每车4列整体拷贝）
    for k = 1:trainNum_filtered
        oldTrainIdx = selectedTrainIdx(k);
        oldBase = 6 + (oldTrainIdx - 1) * 4;
        newBase = 6 + (k - 1) * 4;

        RAW_filtered(1,newBase:newBase+3) = RAW(1,oldBase:oldBase+3);
        RAW_filtered(2:end,newBase:newBase+3) = RAW(selectedStationRows,oldBase:oldBase+3);
    end

    % 输出日期时间版本（A/D/G列转datetime，SEQ保留数值）
    RAW_filtered_date = RAWtoDateTime(RAW_filtered);
end

% 辅助函数：根据车站输入定位车站索引（返回1~stationNum）
function idx = locateStationIndex(RAW, stationNum, stationInput)
    idx = [];

    % 优先按NODE_ID匹配
    if isnumeric(stationInput) && isscalar(stationInput)
        targetId = stationInput;
        for i = 1:stationNum
            curId = RAW{i+1,2};
            if isnumeric(curId) && isequal(curId, targetId)
                idx = i;
                return;
            end
        end
    else
        stationStr = strtrim(char(string(stationInput)));
        idNum = str2double(stationStr);

        % stationInput是数字字符串时，尝试按NODE_ID匹配
        if ~isnan(idNum)
            for i = 1:stationNum
                curId = RAW{i+1,2};
                if isnumeric(curId) && isequal(curId, idNum)
                    idx = i;
                    return;
                end
            end
        end

        % 按NODE_CODE匹配
        for i = 1:stationNum
            codeVal = RAW{i+1,3};
            if ischar(codeVal) || isstring(codeVal)
                if strcmpi(strtrim(char(codeVal)), stationStr)
                    idx = i;
                    return;
                end
            end
        end

        % 按NODE_NAME匹配
        for i = 1:stationNum
            nameVal = RAW{i+1,5};
            if ischar(nameVal) || isstring(nameVal)
                if strcmp(strtrim(char(nameVal)), stationStr)
                    idx = i;
                    return;
                end
            end
        end
    end

    if isempty(idx)
        error('RebuildV3fByScope:StationNotFound', ...
            '未找到车站输入：%s。可使用NODE_ID/NODE_CODE/NODE_NAME。', char(string(stationInput)));
    end
end

% 辅助函数：将输入时间解析为当天秒数；输入为空时返回默认值
function secValue = parseTimeInputToSecondOfDay(timeInput, defaultValue)
    if (ischar(timeInput) && isempty(timeInput)) || ...
       (isstring(timeInput) && strlength(timeInput)==0) || ...
       isempty(timeInput)
        secValue = defaultValue;
        return;
    end

    if isnumeric(timeInput) && isscalar(timeInput) && ~isnan(timeInput)
        % 若传入的是Excel序列值（如2.34）或天内小数（如0.34），统一按时间解析
        secValue = excelSerialToSecondOfDay(timeInput);
        return;
    end

    if isdatetime(timeInput)
        v = datevec(timeInput);
        secValue = v(4)*3600 + v(5)*60 + v(6);
        return;
    end

    if ischar(timeInput) || isstring(timeInput)
        s = char(timeInput);
        v = datevec(s); % 支持 'yyyy/MM/dd HH:mm:ss' 或仅 'HH:mm:ss'
        secValue = v(4)*3600 + v(5)*60 + v(6);
        return;
    end

    error('RebuildV3fByScope:InvalidTimeInput', '无法识别的时间输入类型。');
end

% 辅助函数：Excel序列值转当天秒数
function secValue = excelSerialToSecondOfDay(excelSerial)
    v = datevec(excelSerial);
    secValue = v(4)*3600 + v(5)*60 + v(6);
end

% 辅助函数：判断某个秒值是否位于时间窗内（支持跨午夜）
function flag = isSecondInWindow(targetSec, startSec, endSec)
    if startSec <= endSec
        flag = (targetSec >= startSec) && (targetSec <= endSec);
    else
        % 例如 23:00 到 02:00
        flag = (targetSec >= startSec) || (targetSec <= endSec);
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
% 被MarkTrainNumber和DrawLineDigram调用
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


%% 函数名称：DrawLineDigramColor
%  描    述：根据时刻表的数据与指定的线路号和颜色，绘制列车运行图（不区分上下行，全部使用指定颜色）
%  输入参数：trainNum列车数量, stationNum站台数量, RAW全部内容的元胞变量, DirectionSign上下行标识,
%            StationPosition每个站点在y轴的坐标, LineID为指定的线路号, lineColor指定的颜色字符
%  输出参数：LineHandle-plot语句句柄, trainName-列车的车次号
%  调用函数：parseTime()时间转换函数、IsStationOnLine()判断某站是否在指定线路上
function [ LineHandle, trainName ] = DrawLineDigramColor(RAW, trainNum, stationNum, DirectionSign, StationPosition, LineID, lineColor)
    hold on;

    LineHandle = {};
    trainName = {};
    validStations = [];

    % 判断车站是否属于指定线路
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:stationNum;
    else
        for i = 1:stationNum
            LineInfo = RAW{i+1,4};
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = i;
            end
        end
    end

    for i = 1:trainNum
        baseCol = 6 + (i-1)*4;

        header = RAW{1, baseCol};
        if ischar(header) || isstring(header)
            name = regexprep(string(header), '[Aa]$', '');
            name = regexprep(name, '_$', '');
        else
            continue;
        end

        T = []; Y = []; Seq = [];

        for k = 1:length(validStations)
            j = validStations(k);
            row = j + 1;
            if row > size(RAW,1)
                break;
            end

            arr = RAW{row, baseCol};
            dep = RAW{row, baseCol+1};
            seq = RAW{row, baseCol+3};

            t = parseTime(arr);
            if ~isempty(t)
                T(end+1) = t;
                Y(end+1) = StationPosition(k);
                if isnumeric(seq) && ~isnan(seq), Seq(end+1) = seq;
                else, Seq(end+1) = NaN; end
            end

            t = parseTime(dep);
            if ~isempty(t)
                T(end+1) = t;
                Y(end+1) = StationPosition(k);
                if isnumeric(seq) && ~isnan(seq), Seq(end+1) = seq + 0.1;
                else, Seq(end+1) = NaN; end
            end
        end

        if numel(T) >= 2
            if all(isnan(Seq))
                [T, idx] = sort(T);
                Y = Y(idx);
            else
                [~, idx] = sort(Seq);
                T = T(idx);
                Y = Y(idx);
            end

            % 全部使用指定颜色（不区分上下行）
            h = plot(T, Y, lineColor, 'LineWidth', 2);

            LineHandle{end+1} = h;
            trainName{end+1} = char(name);
        end
    end

    % 不显示图例（车次号已标注在图上）
end


%% 函数名称：MarkTrainNumberColor
%  描    述：根据指定颜色标记列车车次
%  输入参数：RAW, trainNum, stationNum, StationPosition, LineID, textColor
function [ ] = MarkTrainNumberColor(RAW, trainNum, stationNum, StationPosition, LineID, textColor)
    validStations = [];
    if isempty(LineID) || (ischar(LineID) && strlength(LineID)==0)
        validStations = 1:stationNum;
    else
        for i = 1:stationNum
            LineInfo = RAW{i+1,4};
            if IsStationOnLine(LineInfo,LineID)
                validStations(end+1) = i;
            end
        end
    end

    for i = 1:trainNum
        baseCol = 6 + (i - 1) * 4;
        header = RAW{1, baseCol};

        if ischar(header) || isstring(header)
            name = regexprep(string(header), '[Aa]$', '');
            name = regexprep(name, '_$', '');
        else
            continue;
        end

        times = [];
        rows  = [];

        for j = 2:size(RAW, 1)
            LineInfo = RAW{j, 4};
            if ~(isempty(LineID) || (ischar(LineID) && strlength(LineID)==0))
                if ~IsStationOnLine(LineInfo, LineID)
                    continue;
                end
            end

            if isnumeric(RAW{j, baseCol}) && ~isnan(RAW{j, baseCol})
                times(end+1) = RAW{j, baseCol};
                rows(end+1) = j;
            end
        end

        if isempty(times)
            continue;
        end

        [~, idx] = min(times);
        t = datevec(times(idx));
        x = t(4) * 3600 + t(5) * 60 + t(6) - 50;

        stationIdx = rows(idx) - 1;
        k = find(validStations == stationIdx);

        if isempty(k)
            continue;
        end

        y = StationPosition(k) - 80;
        % 使用指定颜色标记车次号
        text(x, y, name, 'FontSize', 15, 'Color', textColor);
    end
end


%% 函数名称：RAWtoDateTime
%  描    述：由于输出excel时会自动转换成秒，需要转换为原始日期时间格式
%  输入参数：根据v3转换成v3f后的RAW
function RAW_date = RAWtoDateTime(RAW)
    % 完整复制原始RAW
    RAW_date = RAW;
    [row, col] = size(RAW);

    % 遍历所有列（从第6列开始）
    for j = 6:col
        header = RAW{1,j};

        if ischar(header) || isstring(header)
            header_str = char(header);
            % 只处理 _A/a _D/d _G/g 结尾
            if endsWith(header_str, '_A') || ...
               endsWith(header_str, '_D') || ...
               endsWith(header_str, '_G') || ...
               endsWith(header_str, '_a') || ...
               endsWith(header_str, '_d') || ...
               endsWith(header_str, '_g')

                for i = 2:row
                    val = RAW{i,j};

                    if isnumeric(val) && ~isnan(val)
                        dt = datetime(val, 'ConvertFrom', 'excel');
                        dt.Format = 'yyyy/MM/dd HH:mm:ss';
                        RAW_date{i,j} = dt;
                    end
                end
            end
        end
    end
end



