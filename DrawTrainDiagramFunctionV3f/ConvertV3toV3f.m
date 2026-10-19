%% 文件名称：ConvertV3toV3f.m
%  摘    要：将 plan_TT0 和 reschedule_TT0 从 v3 格式转换为 v3f 格式（添加SEQ列）
%  作    者：李仁龙
%  时间：2026年08月07日
%  描    述：独立脚本，不依赖 DrawTrainDigramFunctionV3f 函数库
%           将 v3 格式时刻表（每车3列：_A/_D/_G）转换为 v3f 格式（每车4列：_A/_D/_G/_SEQ）

clc;  % 注意：不执行 clear，避免清除调用者变量

% ======================== 输入配置 ========================
% 获取本脚本所在目录
scriptDir = fileparts(mfilename('fullpath'));
% v3 文件所在目录（相对于本脚本的上级目录下的画图新版V3F）
dataDir = fullfile(scriptDir, '..', '画图新版V3F');
% 需要处理的文件列表（v3 格式）
fileNames = {'plan_TT0 .xlsx', 'reschedule_TT0.xlsx'};

% ======================== 执行转换 ========================
for k = 1:length(fileNames)
    fileName = fullfile(dataDir, fileNames{k});
    fprintf('处理文件: %s\n', fileName);

    % 读取 v3 时刻表（默认第一个 sheet）
    [~, ~, RAW_v3] = xlsread(fileName);
    fprintf('  原始 v3 格式: %d 行 x %d 列\n', size(RAW_v3, 1), size(RAW_v3, 2));

    % 转换为 v3f 格式（自动添加SEQ列）
    RAW_v3f = convertV3toV3f_core(RAW_v3);

    % 生成输出文件名（原文件名 + _v3f）
    [pathStr, nameStr, ~] = fileparts(fileNames{k});
    % 去除文件名末尾空格
    nameStr = strtrim(nameStr);
    outFileName = fullfile(pathStr, [nameStr '_v3f.xlsx']);

    % 直接保存数值格式的 v3f（保留 Excel 序列值，方便 xlsread 再次读取）
    writecell(RAW_v3f, outFileName);
    fprintf('  输出 v3f 格式: %d 行 x %d 列\n', size(RAW_v3f, 1), size(RAW_v3f, 2));
    fprintf('  已保存至: %s\n\n', outFileName);
end

disp('全部转换完成！');


%% ======================== 局部函数 ========================

%% 函数名称：convertV3toV3f_core
%  描    述：将 v3 时刻表转换为 v3f 时刻表
%            v3 格式：前3列为信息列(NODE_ID/NODE_CODE/NODE_NAME)，之后每3列为一辆车(_A/_D/_G)
%            v3f格式：前5列为信息列(NODE_NAME_SHORT/NODE_ID/NODE_CODE/LINE_IND/NODE_NAME)，之后每4列为一辆车(_A/_D/_G/_SEQ)
%  输入参数：RAW_v3 - v3格式元胞数组
%  输出参数：RAW_v3f - v3f格式元胞数组
function RAW_v3f = convertV3toV3f_core(RAW_v3)
    % 读取 v3 时刻表的所有行与列
    [row, col] = size(RAW_v3);

    % 基于 v3 时刻表的基础信息
    stationNum = row - 1;       % 第一行表头
    trainNum = (col - 3) / 3;   % 前三列为信息列，之后每三列为一辆车

    % v3f 新表大小
    newCol = 5 + trainNum * 4;
    RAW_v3f = cell(row, newCol);    % 行数不变仅改变列数

    % 处理 v3f 前5列基础信息
    % v3f 的前五列表头信息
    RAW_v3f(1,1:5) = {'NODE_NAME_SHORT','NODE_ID','NODE_CODE','LINE_IND','NODE_NAME'};
    % 从第二行开始遍历所有行
    for i = 2:row
        RAW_v3f{i,1} = '';                    % NODE_NAME_SHORT 先置空
        RAW_v3f{i,2} = RAW_v3{i,1};           % NODE_ID 与 v3 的第一列相同
        RAW_v3f{i,3} = RAW_v3{i,2};           % NODE_CODE 与 v3 的第二列相同
        RAW_v3f{i,4} = [];                    % LINE_IND 设置为空[]，适配之后的LineID的索引
        RAW_v3f{i,5} = RAW_v3{i,3};           % NODE_NAME 与 v3 的第三列相同
    end

    % 处理每一辆车的列信息
    for t = 1:trainNum
        oldBase = 4 + (t-1)*3;  % v3 时刻表每辆车的基准列（到达时间列）
        newBase = 6 + (t-1)*4;  % v3f 时刻表每辆车的基准列（到达时间列）

        % v3 车辆信息表头
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

            % 写入新 v3f 表
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

        % 新增 SEQ 列
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

        % 写入 SEQ 列
        for i = 2:row
            RAW_v3f{i,newBase+3} = seq_col(i);
        end
    end
end


%% 函数名称：rawToDateTime
%  描    述：将 v3f 元胞数组中的到发时间从 Excel 序列值转换为 datetime 格式
%            以便 writecell 输出时保持可读的日期时间格式
%  输入参数：RAW - v3f 格式元胞数组（时间为 Excel 序列值）
%  输出参数：RAW_date - 时间列已转为 datetime 格式的元胞数组
function RAW_date = rawToDateTime(RAW)
    % 完整复制原始 RAW
    RAW_date = RAW;
    [row, col] = size(RAW);

    % 遍历所有列（从第6列开始，前5列为基础信息）
    for j = 6:col
        header = RAW{1,j};

        if ischar(header) || isstring(header)
            header_str = char(header);
            % 只处理 _A/a _D/d _G/g 结尾的列（到发时间列），跳过 _SEQ 列
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
