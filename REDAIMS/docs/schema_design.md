# 独立基本图存储与事务实现

更新：2026-10-25。本页区分当前实际表和后续规划。新表由启动初始化补建，旧基本图只在显式迁移提交时转换。

## 当前实体

| 表 | 已实现字段与职责 |
| --- | --- |
| base_timetables | id UUID 主键、base_tt_no 唯一、owner_category_id 非空且唯一、name、date_base、document JSON、revision；无伪 run |
| base_tt_sources | id、base_tt_id、job_id、filename、digest、managed_name 唯一；独立来源归属 |
| base_tt_jobs | id、文件名/摘要、状态、options/report JSON、base_tt_id、error、created_at；与旧 import_jobs 分离 |
| base_tt_migrations | old_run_id 主键、base_tt_id 唯一、snapshot JSON、created_at；保存旧记录、备份路径和身份映射 |
| run_working_data | run_id 主键、date_base、revision；普通结果工作数据元信息 |
| runs / run_trains / timetable_events | 普通结果身份与事件，现存结构继续使用；旧 base_run_data 标记的记录仅待显式迁移 |
| nodes | node_name / node_name_chn / node_code 全局稳定身份；独立图解析后登记复用 UUID |
| file_cleanup | 提交后的独占受管文件清理队列，失败可恢复 |

当前 BaseTT 四表解析内容放在 document JSON：nodes、trains、events、lines、members、minimum_run_times、issues。节点、列车、访问仍有稳定 ID 和来源坐标。它是独立图的数据集合，不复用普通 run 事件表。计划中的 base_tt_events/base_tt_trains 等规范化子表尚未建立；历史归档、工作区差异草稿表也尚未建立。

内部列名 base_tt_no 对外序列化为 baseTT_no；当前技术默认 `BTT-<UUID hex>`，全局唯一且删除不复用，覆盖/移动保留身份。未来人类可读编号格式属于 D05 的后续配置，不套用 run_no=0。

owner_category_id 有数据库唯一/非空约束，分类存在性及六级类型在持锁事务中校验，分类删除统一阻止未处理的物理图；当前未增加数据库外键。因此业务写入须走服务接口，不能绕过服务直接 SQL 修改关联。

## 回溯与索引

存储即绑定：先查本级，无图逐级向父级回溯，直到研究员；返回 physical/inherited/missing。run 从直属批次开始，未分组则 missing。新模型没有可写绑定表，也不读取旧 base_bindings 作为新图来源。

树只按物理 owner 构造，详情/影响解析才回溯。下级有自己的图时屏蔽祖先图；折叠或筛选树不改变作用范围。当前解析每次读取事务快照，无额外持久绑定缓存。

源 NODE_IND/LINE_IND 保留在图自己的 JSON 数据集合中。位于路网以下的图与该路网已知节点/线路映射、其他独立图及普通结果全局 SEQ 校验；研究员图检查目前所有直接子路网，未创建路网时仍检查全局节点身份。跨路网移动在目标范围重新校验，冲突阻止。没有推测索引重映射、自动跨路网合并或改变源索引。普通 run 含事件时的跨路网移动暂不开放。

## 日期与股道

解析继续保留原始坐标、日期系统、累计秒、日偏移和列车基准日证据；用户确认 date_base/date_mode 后才能保存。rebase 对齐源最早日期并保留日差；preserve 不把 1900 年源日期当现代运行日期。纯时间不猜测午夜翻转，允许累计小时和舍入进位。

新导入Excel的DB_TRACKS/UB_TRACKS采用 `[10,11,12]`（无正线）或 `[5,6,7]/6`（兼用），UP_TRACKS为别名；库内document.members分别保存DB_STOP_TRACKS（数组）、DB_MAIN_TRACK（正整数或null）、UB_STOP_TRACKS、UB_MAIN_TRACK及TRACKS_SCHEMA_VERSION=2。原紧凑文本保留追溯，导出从拆分字段重组为两列，内部字段不进入Excel。_G校验对实际BaseTT本站所有所属线路合并上下行到发线和正线做OR判断；股道绘制仍按所选线路/本站合并去重，二者分别计算。纯列表表示全到发线、正线为null；兼用编号保留两角色但去重计数。旧计数不能恢复真实编号，未知资料不展开；不自动迁移或回写源文件。基础运行图与股道展开图已实现。

## 导入、覆盖与恢复

上传暂存 → 只读业务预检及类别/影响快照 → confirmed/token/日期等确认 → prepared → 受管复制与摘要核验 → 数据库事务写入 → committed。服务以单机进程 RLock 串行化，连接拥有独立事务。

提交重新核对类别/图修订/范围与关联数据。整体替换 document 与来源，保留 id/baseTT_no 和实际 owner、增加 revision；旧来源在提交后进入清理队列。文件或数据库失败回滚到原图/原文件，清理未提交新副本，任务可重新处理；启动恢复清理中断任务。用户外部 Excel 不被写入。普通覆盖没有历史备份，不能宣称可恢复旧版本。

## 位置、删除与编辑

位置移动保持实体和源文件，只更新 owner/revision；预览和确认检查原、新两侧影响，目标占用阻止。独立删除有依赖则阻止；分类删除须先处置独立图和待迁移旧图。普通 run 删除同时清理 run_working_data 与事件/来源等已有子表。

共用编辑按 kind/id 读取各自实体；revision 摘要包含对象、数据、位置和有效基准上下文。服务验证完整对象加 changes，返回绑定修改集的 validation_token，只读校验不保存。保存事务再次复核，更新当前对象和列车日期/修订，保持事件 ID，不因筛选删数据；不自动归档或反向改写关联 run。前端 sessionStorage 只是本页签草稿，不等同正式持久数据或版本库。

## 显式旧图迁移

迁移预览盘点旧 run/base_run_data/事件/来源/直接绑定和解析变化，由用户选择唯一目标，禁止目标占用。提交锁内先核对来源及预览，再在关闭本服务数据库连接期间备份数据库、可选 WAL 和整个受管文件目录到数据库同级 migration_backups/UUID；备份后复检，再事务转换。

新图保留事件/列车/节点和来源身份，托管文件不重新复制或重命名；旧记录快照与映射落入 base_tt_migrations，旧专用 run/绑定退出，旧任务标记 migrated。失败事务保留旧记录，备份保留。多分支历史绑定不会静默转换为多个物理图，预览明确显示失去来源的分支。

本轮只在临时库验证，无真实数据自动迁移。运行仍要求单实例服务；备份不保证其他进程并发写库时一致，应用尚无在线自动恢复或历史归档能力。未来工作区/历史设计见 [workspace_history_design.md](workspace_history_design.md)。

编辑器弹出时以随机交接标识在浏览器同源 localStorage 暂存对象、修订、修改与显示快照，接收后恢复到目标页签 sessionStorage；显式 Dock 回原窗口时清理交接记录。原窗口无法响应时在独立页原地嵌回，交接记录供原页后续恢复。它们均为临时草稿，不写数据库。


## 基准日保存与选择性Excel导出

EditRequest新增可选date_base，changes允许为空（此时必须有日期变化）。数据库仍以date_base加事件累计秒表示实际日期；保存同步更新BaseTT.date_base或run_working_data.date_base、列车基准日和修订。完整到发日期由读取接口派生，保留原source，不新增冗余绝对日期表列。校验token包含新日期。

导出服务读取同一修订完整工作对象，返回xlsx字节，不修改数据库或受管来源。新导出由现有openpyxl依赖生成；覆盖时仅替换所选worksheet XML并追加所需日期样式，其他OOXML包内容逐字节保留，工作簿日期系统不变。浏览器先选择文件再请求生成，校验源文件指纹后创建写流，写入失败abort，close才提交。文件由用户浏览器授权写回，不开放任意服务端磁盘路径写接口。导出不是事务保存或归档。


显示排序不增加数据库表或字段。读取tables时根据源xlsx及既有来源记录提供original_order、node_ind、line_inds；原始顺序读不到时明确回退。前端的排序模式与排序站点放在浏览器视图快照中，随独立编辑页/Dock交接。服务端事件、保存修订、SEQ和导出仍使用正式工作对象，不受当前视图排序影响。


## 普通run单文件导入（2026-10-25）

不新增表或迁移业务数据。import_jobs.options.role=result区分新普通导入与旧基本图任务，report记录预检、回溯基准、覆盖快照、选项、issues、实例日期及token。正式结果只写runs、run_working_data、run_nodes、run_trains、timetable_events和source_files；基础表既不校验上传副本也不写infrastructure_records/base_run_data。global nodes与network_node_maps复用规范化身份；允许无有效图TTT导入，但必须接受基础资料缺失警告。

应用锁内预备副本并验证摘要，然后同一事务复核目标/作用域/修订、写结果/源引用/任务状态。覆盖保留run ID、名称、编号和批次，工作revision递增，旧源入file_cleanup、旧任务superseded；失败回滚旧结果/源引用/清理队列并移除未提交新副本。prepared中断沿用启动恢复机制。序号0也可属于普通run，不依据编号判断图角色。

用户保存后的编辑属于覆盖预览修订；预览后编辑使覆盖失效，不能静默冲掉新修改。全局同日同车SEQ检查在覆盖时只排除自己的旧事件，不能排除其他run或BaseTT。run移动/分类删除转移两入口均对有时刻数据的跨路网操作保留映射确认边界。


## 只读运行图与线路站序元数据（2026-10-25）

第一阶段绘图不增加数据库表、对象绑定或持久轴缓存。服务在同一读取事务中取得当前BaseTT/run及实际继承基本图，轴与叠加使用同一基础集合。axis_revision是基础图身份/修订与members/minimum_run_times的摘要；草稿预览通过既有编辑校验后在内存中派生，不提交编辑事务。

共用编辑响应的line_seqs按线路保存NODE_SEQ_OF_LINE，来源为有效基本图members；共享站有多线路站序，缺失或冲突为null，不把NODE_IND当站序。完整route_nodes保留无当前run访问的基础节点，并优先采用本对象事件身份。

样式读取项目根diagram_styles.json；绘图错误/警告追加到配置logs目录的log_plottraindiagram.md，含时间、operation_id、对象/线路/实际BaseTT上下文。日志及样式属于文件配置，不是归档版本或事件工作数据。详情见[运行图操作指南](train_diagram_guide.md)。

股道展开请求仅产生内存派生点（track_offset、calculated、usage_kind、event.track_usage）和诊断日志，不写事件_G、日期、SEQ或基础轴。空_G且实际集合含1时才允许绘图默认1并警告，不回写。坐标反向只影响站序屏幕投影，股道自下向上保持实际编号升序；插入显示空间不修改PASS→PASS等效间距。

2026-10-25补充：到发线数组非null时，MAIN_TRACK=null是有效的无正线配置；到发线数组和正线同时null才表示方向资料未知。[]为明确空集合，[]/9为仅有正线。正线可同时属于STOP_TRACKS；有效性和总数只按物理编号集合判断，不因角色重叠报错。不新增数据库迁移，现有JSON字段已能存null。

2026-10-25：列车visit_seq允许任意正整数起号、同车唯一连续，数据行位置不参与判断；读取、编辑、导出不自动重编号。导入的SEQ完整性按原始SEQ独立检查，不因其他单元格错误产生伪断号。_G在实际图本站所有NODE_INFO成员资源中采用OR，不使用线路交集。无数据库迁移，现有INTEGER和唯一约束继续使用。


## 股道修复存储

无需新增表或迁移。缺_G的BaseTT使用base_tt_jobs，普通run使用import_jobs；修复从未提交任务的源副本生成新文件后重新预检，原任务/暂存不改写。编辑修复仅返回track_code的Change，由既有版本校验和事务保存持久化；不保存单独的伪_G列状态，Excel导出统一生成完整四列组。详细规则、占用区间边界与限制见[股道修复指南](track_repair_guide.md)。


## 2026-10-26：SEQ缺列修复与整车平移

SEQ修复只返回内存文件副本重新预检，不更新原任务/正式对象，不新增字段。时间平移返回到发Change并按现有版本校验、事务保存持久化；不单独保存偏移命令，Excel源副本不变。 详见[SEQ修复](sequence_repair_guide.md)与[整车平移](time_shift_guide.md)。


## run 求解日志附件（2026-10-27）

新增 `run_solver_logs`，由数据库初始化使用 CREATE TABLE IF NOT EXISTS 创建，可兼容已有数据库。

| 字段 | 类型 / 约束 |
| --- | --- |
| id | VARCHAR PRIMARY KEY |
| run_id | VARCHAR NOT NULL，所属普通 run |
| filename | VARCHAR NOT NULL，原始文件名末段 |
| size_bytes | BIGINT NOT NULL |
| digest | VARCHAR NOT NULL，SHA-256 |
| content | BLOB NOT NULL，原始日志字节 |
| created_at | TIMESTAMP NOT NULL DEFAULT current_timestamp |

唯一键为 (run_id, filename, digest)。日志正文和元数据在同一数据库事务保存；普通 run 的存在性在同一事务检查。分类删除的 run 删除事务同步清理该表；移动和取消分组保留记录。旧版 role=base 不接受日志附件，不参与基本图迁移快照。时刻表修订号不包含日志附件。


## run 保存的运行图视图（2026-10-27）

新增run_diagram_views，由初始化CREATE TABLE IF NOT EXISTS兼容创建。

| 字段 | 类型 / 约束 |
| --- | --- |
| id | VARCHAR PRIMARY KEY |
| run_id | VARCHAR NOT NULL |
| name | VARCHAR NOT NULL |
| state | JSON NOT NULL，version=1显示选择与坐标范围 |
| snapshot | JSON NOT NULL，绘图上下文与绘图数据快照 |
| created_at | TIMESTAMPTZ NOT NULL DEFAULT current_timestamp |

唯一键(run_id,name)。不创建真实catalog_nodes分类，以viewReference虚拟叶节点挂在所属run下。摘要查询不返回快照正文；详情按run_id/id读取。视图状态、快照、名称在一个事务保存；run删除事务清理该表，转移/取消分组不改记录。快照不依赖当前基本图和事件ID再解析，不回写run数据或修订，不参与旧基本图迁移。

## run统一分析节点

新增run_analysis_nodes，初始化CREATE TABLE IF NOT EXISTS兼容已有数据库。字段id VARCHAR PRIMARY KEY、run_id VARCHAR NOT NULL、node_type VARCHAR NOT NULL（view/solver-log/delay）、name VARCHAR NOT NULL、state JSON NOT NULL、created_at TIMESTAMPTZ DEFAULT current_timestamp。唯一键(run_id,node_type,name)。

state.version=1，记录三个小节的展开状态、运行图选择与快照、日志附件ID及展示配置、延误展示配置及结果快照。求解日志正文继续存run_solver_logs，节点引用本run附件；日志原文件不因文本编码选择而改变。run删除事务同步清理run_analysis_nodes，移动/取消分组保留。旧run_diagram_views不迁移或删除，前端兼容显示为视图子节点。analysisReference/logReference与旧viewReference均为前端虚拟叶节点，parent_id为所属run，不写入真实catalog_nodes。

分析节点和日志不参与时刻表修订号。详情按run_id+node_id隔离，目录仅返回摘要。保存事务校验run及日志归属。运行图/延误快照与日后源数据修订分离。
