# AEAssist AOE Skill Extractor

从 AEAssist BattleLog 日志中提取 AOE 技能。脚本会把技能读条、`AbilityEffect`、派生技能命中和命中目标串起来，输出更接近“真实可选中施法 ID”的结果。

当前提取器版本：`1.4.0`

## 现有功能

- 识别 `AbilityEffect` 短时间内命中多个玩家目标的确认 AOE。
- 在 `-all` 模式下分类输出：`确认的aoe`、`高度疑似的Aoe`、`疑似Aoe`。
- 默认只接受可选中来源的真实技能使用，并过滤不可选中的 `AbilityEffect` 目标。
- 对父技能和派生技能做归并，例如输出父技能 ID，同时保留实际命中的 `AbilityEffect` 名称/ID。
- 同名不同 ID 的技能会分别输出，不按技能名合并。
- 对链接后的派生命中继续收集目标，避免只记录到单个中间目标。
- 输出技能使用到 `AbilityEffect` 的延迟、实际命中 ID、命中目标数量和目标列表。
- 支持使用 `AoeActions.json` 校验当前提取结果中尚未收录的技能 ID。
- 支持 `txt`、`csv`、`json` 三种输出格式。

## 环境要求

- Python 3.10 或更新版本。
- 不需要额外第三方依赖。

## 快速开始

在脚本所在目录运行：

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" -o aoe_skills.txt
```

输出文本第一行会包含提取器版本：

```text
来自[1.4.0]提取器
```

## 常用命令

### 分类输出所有 AOE 和疑似 AOE

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" -o aoe_skills.txt
```

### 只分析指定技能 ID

多个 ID 使用英文逗号分隔：

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" --action-ids 49975,50029,50035,50040 -o selected_aoe.txt
```

### 输出 CSV 或 JSON

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" --output-format csv -o aoe_skills.csv
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" --output-format json -o aoe_skills.json
```

### 使用 AoeActions.json 校验

`AoeActions.json` 是已确认但不完整的 AOE ID 列表。校验模式会输出当前提取结果中未被该列表收录的条目。

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" --validate-actions AoeActions.json -o validate_actions.txt
```

### 从技能读条提取

```bash
python extract_aoe_skills.py --from-casts "Log-2354965 - 副本.log" -o cast_skills.txt
```

### 包含派生读条判断

```bash
python extract_aoe_skills.py "Log-2354965 - 副本.log" --include-derived-casts -o aoe_skills.txt
```

## 输出字段

`-all` 的文本输出按分类分块，每行包含：

| 字段 | 说明 |
| --- | --- |
| 技能名 | 归并后的真实技能名 |
| ID | 归并后的真实技能 ID |
| 数量 | 该技能识别到的来源数或命中目标数 |
| 技能使用到AbilityEffect耗时ms | 可选中技能读条到实际命中的延迟 |
| AbilityEffect名称/ID | 实际产生命中的技能名和 ID |
| 命中目标 | `目标数量:目标1,目标2,...` |

CSV/JSON 会输出等价字段：`category`、`source_name`、`skill_name`、`skill_id`、`count`、`delay_ms`、`ability_name`、`ability_id`、`hit_targets`。

## 分类规则

### 确认的aoe

同一 `AbilityEffect` 在短时间窗口内命中至少 `--min-targets` 个唯一玩家目标，默认阈值为 2。

### 高度疑似的Aoe

可选中父技能读条后，在派生窗口内出现多个派生读条来源，并且补全后能确认至少 `--min-targets` 个玩家命中目标。

### 疑似Aoe

多个可选中来源使用同名同 ID 技能，并且补全后能确认至少 `--min-targets` 个玩家命中目标。

去重优先级为：`确认的aoe` > `高度疑似的Aoe` > `疑似Aoe`。

## 真实施法与派生命中

有些日志中实际造成伤害或效果的 `AbilityEffect` ID 不是玩家或 Boss 读条的技能 ID。脚本会尽量保留真实可选中施法 ID，并在 `AbilityEffect名称/ID` 中显示实际命中 ID。

示例：

```text
无光的世界    50029    ...    无光的世界/50030    8:...
极限炫技      46497    ...    极限炫技/46499      8:...
```

这表示输出主 ID 仍是可选中的真实施法，后面的 `AbilityEffect` 字段说明最终命中的派生 ID。

## 玩家与目标过滤

脚本会先扫描 `Unit创建` / `Unit消失` 建立玩家候选列表：

- 优先把 `DataId: 0` 的 `EntityId` 视为玩家实体。
- 如果日志缺少玩家候选信息，会自动退化为不过滤。
- 可用 `--no-player-prefilter` 关闭该预过滤。

所有模式还会过滤 `AbilityEffect Target 可选中: False` 的命中，避免机制单位或不可选中目标污染结果。疑似类输出还会检查补全后的 `hit_targets` 数量，只有达到 `--min-targets` 才输出。

## 常用参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `-all`, `--all` | 关闭 | 分类输出确认 AOE、高度疑似 AOE、疑似 AOE |
| `--from-casts` | 关闭 | 从技能读条记录输出技能列表 |
| `--include-derived-casts` | 关闭 | 在普通 AOE 输出中合并派生读条判断 |
| `--action-ids` | 空 | 只保留指定技能 ID，多个 ID 用逗号分隔 |
| `--source-name` | 空 | 只保留指定来源名称 |
| `--output-format` | `txt` | 输出格式：`txt`、`csv`、`json` |
| `--min-targets` | `2` | 判断 AOE 需要的最少唯一玩家目标数 |
| `--event-window-ms` | `500` | 聚合同一 `AbilityEffect` 多目标命中的窗口 |
| `--derived-window-ms` | `8000` | 父技能后查找派生读条的窗口 |
| `--min-derived-casts` | `2` | 判定派生读条疑似 AOE 的最少来源数 |
| `--max-effect-delay-ms` | `15000` | 技能读条到命中的最大补全延迟 |
| `--target-window-ms` | `500` | 收集同一次命中目标的窗口 |
| `--linked-target-window-ms` | `1500` | 收集派生后续链接命中目标的窗口 |
| `--validate-actions` | 空 | 使用 AoeActions JSON 数组校验输出 |
| `--no-player-prefilter` | 关闭 | 关闭玩家 EntityId 预过滤 |
| `--encoding` | `auto` | 日志编码，自动尝试 `utf-8-sig` 和 `gb18030` |

## 仓库内容

本仓库只应包含：

- `extract_aoe_skills.py`
- `README.md`

战斗日志、验证 CSV/TXT、`AoeActions.json` 和 `__pycache__` 不应提交到仓库。
