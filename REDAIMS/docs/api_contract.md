# API 契约：独立基本图与共用编辑

更新：2026-10-25。以下为已接入的代码接口，前缀 `/api/v1`。生成快照见 [openapi.json](openapi.json)，运行服务以 `/openapi.json` 为准。当前本地登录不执行鉴权；后端仍仅面向本机开发使用。

## 基本图与解析

分类名称和备注通过 `PATCH /api/v1/catalog/{id}` 编辑。请求可包含 `name`、`notes` 中一个或两个字段，至少一个；未提供的字段保持原值，不接受null。名称1–200字符，首尾空白去除后不能为空；备注最多20000字符，空字符串清空备注。成功返回完整分类 `{id, kind, parent_id, name, notes}`。同一父分类（根级父ID为null）下同类型同名返回409，节点不存在404，无效字段或空提交422。名称和备注在同一事务内更新，重名失败不会部分保存备注。原仅提交notes的客户端继续兼容，接口不修改ID、kind或parent_id。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /base-timetables | 独立基本图列表，含 id、baseTT_no、owner_category_id、路径、日期、摘要、来源、修订 |
| GET | /base-timetables/{id} | 实际基本图详情 |
| GET | /catalog/{id}/base-timetable | 返回 requested_category_id、effective、local_base；effective 含 physical/inherited/missing、实际所有者与路径 |
| GET | /source-files/{id} | 下载受管源文件；同时支持仍待迁移的旧来源 |
| POST | /base-timetables/import/preview | 二进制 xlsx 请求体；query 为 owner_category_id、name、filename、date_base、date_mode、可选 sheet；上限 32 MB |
| POST | /base-timetables/import/{job_id}/commit | 确认导入或按类别整体覆盖 |
| GET | /ingest/jobs、/ingest/jobs/{id} | 新独立导入任务列表/详情 |
| DELETE | /ingest/jobs/{id} | 清理未提交暂存 |
| POST | /base-timetables/{id}/move-preview | target_category_id，返回原/新路径、can_move、issues、impact、preview_token |
| POST | /base-timetables/{id}/move | target_category_id、confirmed=true、preview_token；占用目标禁止移动 |
| GET | /base-timetables/{id}/deletion-preview | 依赖、影响、can_delete、preview_token |
| DELETE | /base-timetables/{id} | JSON confirmed=true、preview_token；有继承依赖则阻止 |

预检返回 job_id、state、report。report 包含 options、四表解析结果及 previews、issues、summary、trains、replacement（本级占用或 null）、effective_before、impact、preview_token、can_commit。导入设置问题可无 sheet/row；不得伪显示为 Excel 第 0 行。预览错误条目数即页面阻断项数。

提交字段为 confirmed=true、preview_token、date_confirmed=true、train_dates_confirmed=true；存在 warning 时要求 warnings_confirmed，存在 replacement 时另要求 replace_confirmed。提交重新检查文件摘要、类别和上下文；新建不能因目标后来被占用而静默转为覆盖。覆盖保留 id/baseTT_no，增加 revision，替换工作四表与受管来源；不保留历史版本。已成功的同一导入任务可幂等返回现存结果，被后续覆盖替代的任务不能再次回放。

树只消费列表的真实 owner_category_id，不按 effective 结果为子类别复制条目。解析只读，不提供任意跨旁支绑定写入。

## 共用编辑与普通 run

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /runs、/runs/{id} | 普通结果列表/详情，排除未迁移旧基本图 |
| GET | /base-timetables/{id}/tables、/runs/{id}/tables | 返回 object、revision、nodes、trains、events、infrastructure；当前一次读取整个对象，前端筛选 |
| POST | /base-timetables/{id}/events/validate、/runs/{id}/events/validate | 只读校验完整当前工作数据加 changes |
| POST | /base-timetables/{id}/events/edit、/runs/{id}/events/edit | 复检后事务保存当前对象 |
| POST | /runs/{id}/move-preview、/runs/{id}/move | 重新归属批次，结构同基本图移动；有事件的 run 跨路网转移暂阻止 |

编辑请求：revision 是读取时返回的上下文摘要；changes 为 `{event_id, field, value}` 列表，field 仅允许 arrival、departure、track_code、visit_seq。时间为累计 HH:MM:SS 或无时区完整日期时刻；股道和 SEQ 为正整数，合法空到发/股道允许 null。不能提交外部对象的事件，不能凭空白格创建不经过车站的访问。

校验返回 can_save、issues、train_date_changes、validation_token、change_count。issues 尽可能含 event_id/field；校验不写事件或列车基准日。保存另传 validation_token、适用 warnings_confirmed/train_dates_confirmed；服务端重新检查全量约束和 token，不信任前端通过状态。版本、位置、有效基准或修改集变化须复检；未显示且未修改的数据保留。保存不归档、不写源 Excel。普通 run 需要 run_working_data 的正式基准日，结果导入已通过下述普通run专用入口接通。

## 显式旧图迁移

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /base-timetable-migrations | 列出仍在旧 run 模型中的基本图 |
| POST | /base-timetable-migrations/{old_id}/preview | target_category_id，盘点旧来源/绑定与新继承变化，返回 can_migrate、preview_token |
| POST | /base-timetable-migrations/{old_id}/commit | target_category_id、confirmed=true、preview_token；备份后再次复核，再事务转换 |

提交返回新 base 和 backup_path。保存 old_run_id→base_tt_id 映射及旧记录快照；来源丢失、摘要改变、目标占用或预览过期均不迁移。启动不会自动迁移。`/ingest/base/preview`、旧 `/ingest/jobs/{id}/commit`、PUT `/bindings/{id}` 返回 410；旧读取/绑定路由已退出主路由，旧代码仅为迁移兼容保留，不能继续混用。

分类 CRUD、分类递归删除预览/执行、未分组 run 查询、结构检查和健康接口保留。分类删除额外返回 physical_base_timetables、legacy_base_ids、can_delete；须先处理其中基本图。

## 错误与边界

404：对象/来源不存在；409：预览、上下文或校验凭证过期、业务冲突；422：参数/数据/确认不合法；413：上传过大；503：文件操作失败。预检的可定位数据错误通常在 201 响应 report.issues 中，而不是整体请求失败。

JSON 配置导入导出、归档、历史工作区、experiment、多文件/片段合并及特定 SEQ 强制提交接口尚未提供。当前 OpenAPI 已列出路径和请求模型，部分字典响应尚未细化为响应模型；集成需以此契约和返回字段为准。

独立编辑为前端 hash 地址 `#timetable?kind=base|run&id=<ID>&transfer=<交接标识>`；Dock 目标为 `#workspace?...`，刷新仍使用同一静态入口，无需新增服务端路由。以上显示控制与标签页交接不改变 API 契约或服务端保存目标。


## 基准日保存与导出接口（2026-10-25，当前已实现）

编辑validate/edit请求新增date_base（可选）；changes可空，但须有日期变化，否则422。返回新增date_base_change（before/after或null），保存新增date_base_confirmed确认标记；已有train_dates_confirmed仍独立适用。验证完整对象与所有修改，令牌包含日期。tables响应事件新增arrival_datetime/departure_datetime派生字段（ISO无时区或null）。

| 方法 | 路径 | 请求/结果 |
| --- | --- | --- |
| GET | /base-timetables/{id}/export-options、/runs/{id}/export-options | 返回revision、sheets(key/name/label/rows)、defaults、建议filename；基本图默认四表，run默认TTT |
| POST | /base-timetables/{id}/export、/runs/{id}/export | query:revision、sheets（逻辑key逗号分隔）、replace（默认false）；返回xlsx字节及UTF-8 Content-Disposition |

另存请求体为空；replace=true时请求体为用户选定源xlsx二进制，上限32MB、解压上限128MB。选中表单必须在原文件存在同名sheet，否则422；支持TTT、LINE_INFO、NODE_INFO、MINIMUM_RUN_TIME。未选sheet及其他包内容保留，1904日期系统受测试覆盖。修订变化409；没有正式数据、无效选择、缺失索引或非无损宽表情形422。接口不接受任意磁盘路径、不在服务器覆盖文件，实际写回/另存由浏览器文件选择与写入API负责，缺少该能力时明确下载并由用户手动替换。参考 [Chrome本地文件API](https://developer.chrome.com/docs/capabilities/web-apis/file-system-access)。


## 显示顺序元数据（2026-10-25）

BaseTT/run的tables响应新增original_order：nodes、trains为稳定ID按源Excel行/列排序的数组，source为excel/provenance，notice提示源文件缺失或未能读取时的回退。nodes新增node_ind（整数或null）与line_inds（整数数组）；run优先补齐自己的节点资料，再用有效基本图/源表资料。该元数据只供排序，不写入时刻工作数据，不改变读取revision或现有校验token。

源表排序读取受管xlsx，TTT表按工作簿表序、数据行序和列车列组位置读取；未在TTT中的基础节点追加到后方。节点/列车来源记录作为读取失败时的后备，不以SQL返回顺序或UUID顺序代替Excel顺序。页面排序由前端完成，无新写入接口。


### 线路显示元数据（2026-10-25）

BaseTT/run的tables响应增加只读display_lines数组，字段line_ind、line_code、line_name_chn；BaseTT来自自有LINE_INFO，run来自回溯解析的有效基本图。节点line_inds合并NODE_INFO成员关系与原TTT/事件线路信息，避免共用站在某条线路筛选时遗漏。无名称的事件线路由前端按编号补充。新增字段不参与数据修订、不改变校验token，无数据库迁移或写入；原infrastructure字段保持原契约。


### 三级列车排序的完整线路上下文（2026-10-25）

tables新增只读route_nodes数组，字段与nodes中的id/node_name/node_name_chn/node_ind/line_inds一致。包含BaseTT或run有效基本图的全部线路节点，以及当前对象自身节点；同站按NODE_NAME合并并使用当前对象事件对应node_id，保留没有任何本对象访问的线路节点位置。该数组仅供邻站搜索，不扩充车站选择、可编辑事件或保存范围；无数据写入、不参与revision或校验token。原nodes、infrastructure和接口路径保持原义。前端以完整线路列表进行双向最近可用站检索，不从过滤后的可见行推导距离。


## 普通run单文件TTT导入（2026-10-25）

| 方法 | /api/v1路径 | 行为 |
| --- | --- | --- |
| POST | /runs/import/preview | 原始xlsx字节；返回201预检任务，不写正式run |
| GET | /runs/import/jobs | 最近50条普通结果任务，仅options.role=result |
| GET / DELETE | /runs/import/jobs/{job_id} | 读取预检 / 取消并清理未提交暂存 |
| POST | /runs/import/{job_id}/commit | 确认并事务提交；返回普通run对象元信息 |

preview查询参数：batch_id、name（1至200字符）、filename、可选run_no（非负整数，未传自动max+1，从1开始）、date_base（默认2026-01-01，须>=2020）、date_mode=rebase/preserve、可选sheet、write_mode=create/replace、覆盖时target_run_id。replace须明确原run_no，且目标必须是同批次/同名/同编号普通run；不得覆盖独立或旧基本图。新建不得指定覆盖目标。每文件一个run，默认选所有TTT表或明确指定一个Sheet；同车跨表片段目前阻断，不默默合并。

任务含job_id、filename、state、run_id、error和report。report含options、classification_path、effective_base（真实基准/归属路径）、replacement（原对象/当前修订/数量）、preview_token、summary、issues（Sheet/行/单元格）、previews、trains和available_sheets。run预检只解析TTT，基础表来自回溯图且不存入run；没有有效图时警告后可导入。全局节点/路网索引、同日同车全局SEQ、日期和有效股道集合仍校验。0作为普通编号不表达基本图身份。

commit沿用Confirmation：confirmed/date_confirmed/train_dates_confirmed必须true；传preview_token，适用warnings_confirmed和replace_confirmed。提交复核有效基本图、分类路径、原run内容修订、暂存摘要及全局约束；旧预检/编号竞争/源文件变更409，设置或确认不全422，文件操作失败503。成功保留覆盖目标身份和归属，增加run_working_data修订；来源/事件/任务同一事务，失败回滚且保留原副本，旧提交任务标记superseded。用户原Excel不变；不归档。任务与旧基本图任务隔离，旧写入接口仍410。

导入后的run使用现有/runs/{id}/tables、events/validate、events/edit、export-options、export和move等接口。前端直接复用TimetableEditor，线路/车站/列车筛选、三级排序、固定行列、股道/SEQ、基准日、保存、导出和独立页/Dock行为相同。分类删除的批次转移也阻止有事件run未经映射跨路网移动。


### 导入问题的节点定位信息（2026-10-25）

节点相关issues增加可选node_ind、node_name和node_name_chn，保留源行原值（包括无效编号0/文本），不以其他有效记录覆盖错误行的编号。NODE_INFO/TTT行级问题带站点上下文；同路网NODE_IND冲突按具体节点返回来源Sheet/行及身份。表头、缺表和纯线路问题无对应节点时不补造字段。该字段仅诊断显示，不改变预检阻断规则、业务数据或提交token。旧任务可能没有这些字段，重新预检生成完整定位信息。


## 运行图只读接口（2026-10-25，第一阶段）

| 方法 | 路径 | 请求与结果 |
| --- | --- | --- |
| GET | /diagram/lines | query:object_type=base或run、object_id；返回object、revision、实际base、lines（available/station_count/issues）、overlay_available、issues |
| POST | /diagram/data | JSON:object_type、object_id、revision、line_ind；可选overlay_base（默认false）、changes（默认空）、date_base；返回当前线路完整只读绘图集 |
| GET | /diagram/styles | 返回styles、revision、source、issues、log_written；页面每4秒读取并应用有效样式，保留当前视图 |
| GET | /diagram/warnings | 返回固定绘图日志filename、最后至多64KB的text；不接受任意文件路径 |

绘图集包含object、revision、实际base、line_ind、axis_revision、axis（stations/intervals/total/unit/order_field）、series、time_extent、preview/preview_changes、comparison_mode、can_plot、styles/style_source、issues、operation_id/log_written。站轴由有效BaseTT的NODE_SEQ_OF_LINE与正向相邻PASS→PASS主最小运行时间生成，计量单位秒；站序须唯一连续1至N，区间须唯一且正值。缺失/矛盾时返回can_plot=false和原因，不回退NODE_IND、源行序或实际里程。

series以对象种类/ID/列车ID形成key，保留train_course_id/train_base_date、方向、events的稳定身份与来源、points（event_id/field/seconds/y）及segments（from/to点下标、dwell或travel、anomaly）。仅连接完整SEQ中的相邻访问；缺必要时刻、离开线路或SEQ缺口保留断点。时间倒置不重排原数据，返回警告和异常线段。前端筛选不重算轴或跨隐藏站搭线。

revision必须匹配最新对象/归属/有效BaseTT上下文，否则409。changes/date_base通过共用编辑校验后仅用于只读草稿预览，错误阻止绘图；不写时刻、日期、修订或归属。run叠加仅使用其实际有效BaseTT，两者date_base及同名列车实例日期须相同；当前不开放跨基准、多run比较。诊断写入配置日志目录的log_plottraindiagram.md，样式错误同时进入管理日志；实际日志写入失败明确返回log_written=false。

样式配置为项目根diagram_styles.json，支持方向/基本图/网格/高亮颜色、线宽、点半径、字体、网格分钟及train_styles[key]颜色/线宽/虚线。未知字段或非法值拒绝，保留本进程上次有效配置。此接口不提供文件写入或完整工作区JSON导入导出。

共用tables的nodes及route_nodes新增line_seqs（以LINE_IND字符串为键，值为NODE_SEQ_OF_LINE正整数或null），供第3级列车到发排序。共享站逐线路保留不同站序，冲突标记null；只读元数据不改变对象修订或原Excel。


## 到发线/正线格式与股道占用扩展（2026-10-25）

新BaseTT预检校验DB_TRACKS/UB_TRACKS的 `[到发线编号]/正线号`，报告tracks_schema_version=2；错误定位具体字段、源行/单元格及节点名称。纯列表合法，表示全部为到发线、正线为null；正线可同时出现在到发线列表中。空单元格保持未知警告。UP_TRACKS兼容，但与UB同时出现须分别比较到发线集合及正线号。旧版本未提交任务读取时增加tracks_format阻断问题，要求重新上传预检；已提交对象不自动迁移。

新成员持久字段为TRACKS_SCHEMA_VERSION=2、DB_STOP_TRACKS:number[]|null、DB_MAIN_TRACK:number|null、UB_STOP_TRACKS:number[]|null、UB_MAIN_TRACK:number|null。成员仍归BaseTT document与原线路，原紧凑字段保留追溯。tables的infrastructure.members包含拆分字段；Excel导出只重组DB_TRACKS/UB_TRACKS，不输出内部拆分字段。_G校验按同一BaseTT本站全部NODE_INFO所属线路的上下行到发线和非空正线做并集，采用OR，按本站隔离。无斜杠的纯列表可直接校验和展开，无正线时导出不输出后缀，图中正线显示“无”。STOP_TRACKS和MAIN_TRACK同号保留双重角色、合并只计一次。

POST /diagram/data请求新增expanded_stations（可选，默认[]，最多500个本站稳定node_id）。不属于当前有效线路的节点422；资料无效的车站不展开，返回警告并记录日志，其余基础运行图可继续显示。新增响应track_stations（每站line_ind、节点身份、can_expand、track_count、tracks[{number,roles}]、directions{down/up:{stop_tracks,main_track}}、issues），expanded_stations为实际成功展开的节点ID。资源只来自当前有效BaseTT对应线路成员，重复/缺失不借用其他线路。

展开系列沿用真实到发点并附track_offset（以股道间距为单位的屏幕竖直偏移，与站轴逆序无关），计算进路点新增calculated=true、usage_kind=track_entry/track_exit/pass_track/track_unassigned；field仍指原arrival/departure。segments.kind新增track_enter、track_occupancy、track_leave、track_pass，移除被展开事件原合并dwell段。event.track_usage返回direction、passing、original_track、adopted_track、defaulted、start_seconds、end_seconds、can_occupy，原track_code与arrival/departure不变。停站列车由真实k与系数计算A+k×yita、D−k×yita；倒置不画伪有效占用，缺时刻仅保留可确定部分，零长占用保留。停站列车空_G默认1仅限真实集合有1并警告，不回写。通过事件passing=true（到发同秒），使用track_pass连接原始到发点，并增加一个pass_track点标记实际股道；其start_seconds=end_seconds=通过秒，can_occupy=true。未指定/不能定位股道时改用track_unassigned红色三角形，位置为所选线路上下行正线位置中点，adopted_track=null、can_occupy=false，不回写源数据；共用/单方向正线使用该正线位置，无正线时在展开区中心并返回track_main_missing警告。

styles新增track_gap（默认1，范围0.5—12，单位5px）和track_yita_seconds（默认1，范围0—3600秒）。前端修改间距只重排显示空间，修改进路系数重新请求几何并保留视窗；均不改变基础axis/axis_revision或正式数据。日志保留原值、采用值、公式时刻、列车实例、节点/线路及来源。

2026-10-25补充：directions.down/up.main_track允许null，配合非null stop_tracks表示无正线的有效配置；两方向均可省略，只有一个方向省略也有效。_G可使用任一已知到发线或非空正线号。[]是明确空集合，与未知空单元格区分；[10]/仍错误。更新不提高tracks_schema_version（仍2），不改请求结构；此前被严格规则阻断的任务需重新预检。


## _G的OR关系与任意起号SEQ（2026-10-25）

基本图预检、普通run导入与共用events/validate、events/edit统一规则：_G为正整数或合法空值，非空须属于实际BaseTT中该站任意所属线路的DB/UB到发线或非空正线，命中一项即可，不逐条线路取交集，也不限制编号顺序。该站所属线路以NODE_INFO为准，不因TTT行的多线路声明要求同时符合所有股道场。诊断显示实际_G字段、单元格和值，确实越界时附该站已知股道和所属线路；资源无法完整核对时按既有未知资料处理提示。

列车_SEQ允许任意正整数起号、任意Excel行序，检查唯一且无中间缺号。导入独立收集原_SEQ后校验，不因为_G或时刻错误丢失编号而产生派生断号；真实SEQ错误单独定位_SEQ单元格。保存/导出保留实际编号，列车基准日和绘图仍按最小有效SEQ/完整访问次序处理。全局实例SEQ一致性约束和NODE_SEQ_OF_LINE线路轴规则保持原业务要求。请求结构与OpenAPI路径数不变。

图窗仍按选中线路构造本站股道集合T；_G在另一所属线路有效但不在当前T时，仅提示当前图无法定位占用，保留确定到发点，不跨线补股道。


## 股道修复

新增4条路径，当前OpenAPI共49条路径。均为显式修复；读取/生成结果不会提交业务修改。

| 方法 | 路径 | 请求与返回 |
| --- | --- | --- |
| POST | /track-repair/{kind}/{object_id}/context | kind=base/run，EditRequest（revision、changes、可选date_base）；返回repair_token、全trains与lines，包含默认方向、related_lines、missing_g、empty_count |
| POST | /track-repair/{kind}/{object_id}/apply | EditRequest加repair_token、selections；返回can_apply、changes（仅track_code）、issues、warnings；成功结果仍需走已有validate/edit |
| GET | /ingest/jobs/{job_id}/track-repair/context | 同时支持base_tt_jobs和普通run的import_jobs未提交预检，返回同一修复上下文；不要求原预检通过 |
| POST | /ingest/jobs/{job_id}/track-repair/apply | repair_token及selections；成功返回XLSX二进制副本与X-Repair-Warnings计数，客户端以副本重新预检；分配失败返回JSON can_apply=false、空changes及issues |

selections为[{train_id, lines:[{line_ind, directions:["UB"]}]}]，只列勾选的列车和线路；每车至少一线路，每线路必须且仅能有一个方向（["UB"]或["DB"]），双方向/重复方向/空方向返回422；未知/重复列车或线路拒绝。上下文变化返回409；其他不可修复的结构/时刻问题返回422。结构/必要时刻等阻断错误不应用修改；容量不足等分配问题进入warnings并保留成功的部分；所选线路/方向股道资料未知则进入warnings，有其他已知候选时继续使用，无候选时跳过该访问并保留原股道。跳过访问有效的既有占用参与避让，changes仅包含可修复访问；仅有告警时can_apply=true（changes可为空）。只补选中列车的_G，其他缺列保持阻断。

分配范围、占用时间边界、未知数据及搜索限额详见[股道修复指南](track_repair_guide.md)。不新增数据库字段，不改变既有保存确认机制。


## 2026-10-26：SEQ修复与整车平移

新增3条路径，OpenAPI现为52条路径。

| 方法 | 路径 | 请求及结果 |
| --- | --- | --- |
| GET | /ingest/jobs/{job_id}/sequence-repair/context | 支持BaseTT与普通run未提交预检，返回repair_token、trains（按表单/列组标识id，含missing_seq、missing_g、有A/D的visits、first_row/last_row）；源文件只读 |
| POST | /ingest/jobs/{job_id}/sequence-repair/apply | repair_token、train_ids；仅允许缺SEQ列车，返回修复XLSX副本；客户端自动重新预检，原任务不改。旧上下文409，无效选择/无时刻/其它结构错误422 |
| POST | /time-shift/{kind}/{object_id}/preview | kind=base/run；EditRequest加train_ids、offset_seconds（非零有符号整数秒）；返回can_apply、仅到发changes、issues、各列车visits/cells、train_date_changes；完整列车、含隐藏站，在现有草稿叠加，仍需validate/edit保存 |

SEQ只按源行A/D有值从1补新列，已有列保留；不会绕过全局SEQ。平移不接受显示站点范围，防止缩减整车范围；未知/重复列车、早于基准日、零/非整数偏移拒绝。原草稿或结果存在阻断错误时can_apply=false、changes为空，不应用部分修改。平移未做可行性冲突检查。请求最大变化条数沿用100000，修改数据/归属/基本图后旧revision返回409。


2026-10-26更正：股道修复context的direction默认为奇数DB（下行）、偶数UB（上行），带/仅看首个车次。表头整列取消在前端清除全部行的线路与方向，selections排除该线路；重新勾选恢复默认方向。不改变请求模型或52条路径。


## 2026-10-27：只补缺失股道与可选既有冲突修复

两类股道修复apply请求增加可选repair_conflicts:boolean，默认false。默认只对所选列车缺少股道的访问生成changes；非空股道保留。context新增warnings（既有冲突/无法核查占用）和每车conflict_count，顺序与窗口列车列表一致。前端开启选项后自动选中涉及冲突的列车，最终修改范围仍受selections限制。

repair_conflicts=true时，按context列车顺序保留先出现的既有占用，对仍冲突的后续已选访问逐个尝试重分配，并保护其他全部已有占用。容量不足、已知无资源和未知资源均返回warnings，保留失败访问，can_apply仍可为true且返回其余成功changes；无法修复时changes可为空。缺失访问的非法时刻等阻断校验仍返回can_apply=false且不应用修改。接口均只生成结果，业务持久化继续由原编辑/导入提交完成。原有X-Repair-Warnings计数保留。取消操作中止客户端保存请求并忽略延迟结果，不发送业务保存请求。


## run 求解日志附件（2026-10-27）

- `GET /api/v1/runs/{run_id}/solver-logs`：按导入时间倒序返回附件元数据列表。
- `POST /api/v1/runs/{run_id}/solver-logs?filename=文件名`：请求体为原始二进制文件（application/octet-stream），成功返回 201 和附件元数据。非空、最大 32 MB；同一 run 下相同文件名及 SHA-256 内容返回已有附件。路径形式的文件名只保留末段。
- `GET /api/v1/runs/{run_id}/solver-logs/{log_id}/download`：以附件下载原始内容，提供 UTF-8 文件名和 nosniff 响应头。

元数据字段：id、run_id、filename、size_bytes、digest（SHA-256）、created_at。不存在的 run、旧版 role=base 对象、其他 run 的附件或不存在的附件返回 404；空文件/无效文件名返回 422，超限返回 413。

接口只附加日志，不解析求解指标、不修改时刻表、基础设施、分类或时刻表修订号。日志跟随 run 转移或取消分组，随 run 删除。


## run 运行图保存视图（2026-10-27）

- GET /api/v1/diagram/views：分类树使用的全部普通run视图摘要，排除旧版role=base对象，不返回快照。
- GET /api/v1/runs/{run_id}/diagram-views：当前run的视图摘要列表。
- POST /api/v1/runs/{run_id}/diagram-views：提交name、state、snapshot，成功201，返回视图摘要；不会修改时刻表或修订号。
- GET /api/v1/runs/{run_id}/diagram-views/{view_id}：按run及视图ID读取完整保存状态及快照，不读取当前时刻表重新绘图。

摘要为id、run_id、name、created_at、line_ind、station_count、train_count、highlight_count。state.version=1，包含line_ind、overlay_base、reverse、station_ids、train_keys、highlighted_keys、expanded_station_ids、track_station、viewport（x0/x1/y0/y1）、from_time、to_time、detail_open和chart_height（340—4000px）。

snapshot.context与snapshot.data分别采用保存时的PlotContext和PlotData；data.series只保留显示或高亮的系列，系列key包含对象类型、对象及列车身份，以区分同车次的基本图和run。快照与状态以同一事务写入，JSON合计最多32 MB。run/线路、车站、系列及基本图归属必须与快照一致，范围须有限且递增。

同一run下同名返回409；无效状态/快照返回422；超限返回413；读取不存在或属于其他run的视图返回404。快照保存后独立于后续数据编辑/基本图绑定变化；run移动/取消分组保留，删除run时同步删除。详见运行图指南及OpenAPI。

## run统一分析节点（2026-10-27）

| 方法/路径 | 行为 |
| --- | --- |
| GET /api/v1/analysis/nodes | 所有普通run的分析节点摘要，不含快照 |
| POST /api/v1/runs/{run_id}/analysis-nodes | 创建view、solver-log或delay节点，201 |
| GET /api/v1/runs/{run_id}/analysis-nodes/{node_id} | 读取完整工作区配置与快照 |
| GET /api/v1/analysis/logs | 日志附件摘要，供分类树直接显示TXT子节点 |
| GET /api/v1/runs/{run_id}/solver-logs/{log_id}/text?encoding=utf-8 | 严格解码日志文本；另支持gb18030 |
| GET /api/v1/runs/{run_id}/delay-analysis | 按当前有效基本图计算已保存run的到发延误秒数 |

保存请求：node_type（view/solver-log/delay）、name、state。state.version=1，含expanded_sections（diagram/log/delay，可同时或全折叠）、可空diagram（现有CreateDiagramView）、log配置、可空delay（state+snapshot）。主类型view须有可绘图快照，solver-log须有本run日志，delay须有本run延误快照。整个已加载工作区一起保存；未来日志可视化的JSON参数放入log.visualization_state。所有名称去首尾空白，同run/类型重名409；状态或快照非法422，正文合计超32MB为413，不存在run/跨run读取404。保存不更新时刻表。

日志文本返回id/filename/digest/encoding/text，原始文件仍由download接口提供。无法按指定编码解码422，支持UTF-8 BOM和GB18030/GBK。延误返回object/base/revision/stations/trains/rows/cells/issues/method，cells到发值为带正负的秒数或null，并附逐字段reason；缺失值不按0计。具体口径见[统一分析指南](run_analysis_guide.md)。旧diagram-views API保留兼容。

运行图series补充可空run_no：普通run为所属方案的数字编号，基本图为null，用于前端绘图列车选项的同车次方案排序。旧绘图快照继续兼容，前端可从同一对象的snapshot.data.object.run_no补足。
