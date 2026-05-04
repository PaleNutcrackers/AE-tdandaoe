# AEAssist AOE Skill Extractor

用于从 AEAssist BattleLog 日志中提取 AOE 技能、疑似 AOE 技能，以及技能读条到实际 `AbilityEffect` 命中的对应关系。

## 功能

- 从 `AbilityEffect` 多目标命中中识别确认 AOE。
- 从父技能读条与派生读条中识别高度疑似 AOE。
- 从多个可选中来源的同技能读条中识别疑似 AOE。
- 输出技能 ID、命中延迟、实际 AbilityEffect 名称/ID、命中目标列表。
- 支持 `txt`、`csv`、`json` 输出格式。

## 使用示例

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" -o aoe_skills.txt
```

只分析指定技能 ID：

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" --action-ids 49975,50033,50035 -o aoe_skills.txt
```

输出 JSON：

```bash
python extract_aoe_skills.py -all "Log-2354965 - 副本.log" --output-format json -o aoe_skills.json
```

## 常用参数

- `-all`, `--all`：输出确认 AOE、高度疑似 AOE、疑似 AOE 三类结果。
- `--from-casts`：从技能读条记录输出技能列表。
- `--action-ids`：只保留指定技能 ID，多个 ID 用逗号分隔。
- `--source-name`：只保留指定来源名称。
- `--output-format`：输出格式，支持 `txt`、`csv`、`json`。
- `--target-window-ms`：同一命中目标聚合窗口，默认 `500`。
- `--linked-target-window-ms`：派生命中后续链接目标收集窗口，默认 `1500`。

## 目标过滤

所有模式只保留命中到可选中目标的 `AbilityEffect` 记录，避免不可选中目标进入结果。

## 输出说明

`--all` 模式按优先级去重输出：

1. `确认的aoe`
2. `高度疑似的Aoe`
3. `疑似Aoe`

文本输出首行包含提取器版本，例如：

```text
来自[1.3.6]提取器
```

## 注意

本仓库只包含提取脚本和说明文档，不包含任何战斗日志或验证输出文件。
