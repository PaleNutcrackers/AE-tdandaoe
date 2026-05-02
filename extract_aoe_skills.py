#!/usr/bin/env python3
"""Extract skills from AEAssist BattleLog files.

The script looks for BattleLog lines like:

    AbilityEffect ActionId: 48896 Name: 凶眼注目 ... Target: Name: ...
    技能使用 50040 核心熔毁 读条时间:3.7 来源于: Name: 恩欧 ...

Repeated AbilityEffect records with the same action id, name, source, and close
timestamps are treated as one skill event. Events hitting at least two unique
targets are considered AOE by default.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TypedDict, TypeVar


EXTRACTOR_VERSION = "1.3.4"
T = TypeVar("T")


TIMESTAMP_RE = re.compile(
    r"(?=\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [+-]\d{2}:\d{2} \[[A-Z]+\])"
)

ABILITY_RE = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}(?:\s+[+-]\d{2}:\d{2})?)"
    r".*?AbilityEffect\s+ActionId:\s*(?P<action_id>\d+)"
    r"\s+Name:\s*(?P<name>.*?)"
    r"\s+Source:\s*(?P<source>.*?)"
    r"\s+Target:\s*Name:\s*(?P<target_name>.*?)"
    r"\s+DataId:\s*(?P<target_data_id>\d+)"
    r"\s+EntityId:\s*(?P<target_entity_id>\d+)",
    re.DOTALL,
)

CAST_RE = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}(?:\s+[+-]\d{2}:\d{2})?)"
    r".*?\[BattleLog\]\s+\[[^\]]+\]"
    r"\s+\S+\s+(?P<action_id>\d+)"
    r"\s+(?P<name>.*?)"
    r"\s+读条时间:\s*[\d.]+"
    r"\s+来源\S*:\s*Name:\s*(?P<source_name>.*?)"
    r"\s+DataId:\s*(?P<source_data_id>\d+)"
    r"\s+EntityId:\s*(?P<source_entity_id>\d+)"
    r"\s+可选中:\s*(?P<source_selectable>True|False)",
    re.DOTALL,
)


def new_target_set() -> set[str]:
    return set()


def new_bool_set() -> set[bool]:
    return set()


@dataclass(slots=True)
class AbilityEvent:
    timestamp: str
    timestamp_ms: int
    action_id: str
    name: str
    source_name: str
    source_entity_id: str
    source_selectable: bool
    source_entity_ids: set[str] = field(default_factory=new_target_set)
    source_selectable_values: set[bool] = field(default_factory=new_bool_set)
    targets: set[str] = field(default_factory=new_target_set)

    def add_target(self, target_entity_id: str) -> None:
        self.targets.add(target_entity_id)

    def add_source(self, source_entity_id: str, source_selectable: bool) -> None:
        self.source_entity_ids.add(source_entity_id)
        self.source_selectable_values.add(source_selectable)


@dataclass(slots=True)
class CastEvent:
    timestamp: str
    timestamp_ms: int
    action_id: str
    name: str
    source_name: str
    source_data_id: str
    source_entity_id: str
    source_selectable: bool


@dataclass(slots=True)
class AbilityHit:
    timestamp: str
    timestamp_ms: int
    action_id: str
    name: str
    source_name: str
    source_data_id: str
    source_entity_id: str
    source_selectable: bool
    target_name: str
    target_entity_id: str


@dataclass(slots=True)
class OutputDetail:
    count: int
    delay_ms: str
    ability_name: str
    ability_id: str
    hit_targets: str


def new_cast_list() -> list[CastEvent]:
    return []


def new_hit_list() -> list[AbilityHit]:
    return []


def new_cast_index() -> dict[str, list[CastEvent]]:
    return {}


def new_hit_index() -> dict[str, list[AbilityHit]]:
    return {}


def new_cast_action_name_index() -> dict[tuple[str, str], list[CastEvent]]:
    return {}


def new_hit_action_name_index() -> dict[tuple[str, str], list[AbilityHit]]:
    return {}


class OutputRecord(TypedDict):
    category: str
    source_name: str
    skill_name: str
    skill_id: str
    count: int
    delay_ms: str
    ability_name: str
    ability_id: str
    hit_targets: str


@dataclass(slots=True)
class ParsedLogData:
    casts: list[CastEvent] = field(default_factory=new_cast_list)
    hits: list[AbilityHit] = field(default_factory=new_hit_list)


@dataclass(slots=True)
class EventIndex:
    casts_by_action: dict[str, list[CastEvent]] = field(default_factory=new_cast_index)
    casts_by_name: dict[str, list[CastEvent]] = field(default_factory=new_cast_index)
    casts_by_action_name: dict[tuple[str, str], list[CastEvent]] = field(default_factory=new_cast_action_name_index)
    hits_by_action: dict[str, list[AbilityHit]] = field(default_factory=new_hit_index)
    hits_by_name: dict[str, list[AbilityHit]] = field(default_factory=new_hit_index)
    hits_by_action_name: dict[tuple[str, str], list[AbilityHit]] = field(default_factory=new_hit_action_name_index)


def read_log_text(path: Path, encoding: str) -> str:
    """Read a log, supporting UTF-8 and Chinese Windows-codepage logs."""
    raw = path.read_bytes()
    if encoding != "auto":
        return raw.decode(encoding, errors="replace")

    for candidate in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(candidate)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8-sig", errors="replace")


def iter_records(text: str) -> list[str]:
    """Split records even when multiple timestamped logs are stuck together."""
    # 部分日志会把两条时间戳记录粘在同一行，先按时间戳前瞻切开再逐条解析。
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [record.strip() for record in TIMESTAMP_RE.split(normalized) if record.strip()]


def parse_actor_fields(actor_text: str) -> tuple[str, str, str, bool]:
    actor_match = re.search(
        r"Name:\s*(?P<name>.*?)"
        r"\s+DataId:\s*(?P<data_id>\d+)"
        r"\s+EntityId:\s*(?P<entity_id>\d+)"
        r"\s+可选中:\s*(?P<selectable>True|False)",
        actor_text,
        re.DOTALL,
    )
    if not actor_match:
        return "", "", "", False

    return (
        actor_match.group("name").strip(),
        actor_match.group("data_id"),
        actor_match.group("entity_id"),
        actor_match.group("selectable") == "True",
    )


def timestamp_to_ms(timestamp: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            parsed = datetime.strptime(timestamp, fmt)
            return int(parsed.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"Invalid timestamp: {timestamp}")


def parse_action_ids(raw_action_ids: str) -> set[str]:
    if not raw_action_ids:
        return set()
    return {action_id.strip() for action_id in raw_action_ids.split(",") if action_id.strip()}


def parse_log_data(log_paths: list[Path], encoding: str) -> ParsedLogData:
    # 统一入口：日志只解析一次，后续分类、补全、输出都复用 casts/hits。
    parsed = ParsedLogData()
    for log_path in log_paths:
        for record in iter_records(read_log_text(log_path, encoding)):
            if "读条时间:" in record:
                match = CAST_RE.search(record)
                if match:
                    name = match.group("name").strip()
                    if name:
                        parsed.casts.append(
                            CastEvent(
                                timestamp=match.group("timestamp"),
                                timestamp_ms=timestamp_to_ms(match.group("timestamp")),
                                action_id=match.group("action_id"),
                                name=name,
                                source_name=match.group("source_name").strip(),
                                source_data_id=match.group("source_data_id"),
                                source_entity_id=match.group("source_entity_id"),
                                source_selectable=match.group("source_selectable") == "True",
                            )
                        )
            if "AbilityEffect" in record:
                match = ABILITY_RE.search(record)
                if match:
                    source_name, source_data_id, source_entity_id, source_selectable = parse_actor_fields(match.group("source"))
                    parsed.hits.append(
                        AbilityHit(
                            timestamp=match.group("timestamp"),
                            timestamp_ms=timestamp_to_ms(match.group("timestamp")),
                            action_id=match.group("action_id"),
                            name=match.group("name").strip(),
                            source_name=source_name,
                            source_data_id=source_data_id,
                            source_entity_id=source_entity_id,
                            source_selectable=source_selectable,
                            target_name=match.group("target_name").strip(),
                            target_entity_id=match.group("target_entity_id"),
                        )
                    )
    return parsed


def build_event_index(casts: list[CastEvent], hits: list[AbilityHit]) -> EventIndex:
    # 索引只按技能 ID/名称缩小候选范围，不在这里改变原始事件顺序。
    index = EventIndex()
    for cast in casts:
        index.casts_by_action.setdefault(cast.action_id, []).append(cast)
        index.casts_by_name.setdefault(cast.name, []).append(cast)
        index.casts_by_action_name.setdefault((cast.action_id, cast.name), []).append(cast)
    for hit in hits:
        index.hits_by_action.setdefault(hit.action_id, []).append(hit)
        index.hits_by_name.setdefault(hit.name, []).append(hit)
        index.hits_by_action_name.setdefault((hit.action_id, hit.name), []).append(hit)
    return index


def passes_filter(name: str, action_id: str, source_name: str, source_selectable: bool, source_name_filter: str, action_id_filter: set[str]) -> bool:
    if action_id_filter and action_id not in action_id_filter:
        return False
    if source_name_filter and source_name != source_name_filter:
        return False
    if not source_selectable:
        return False
    if not name:
        return False
    return True


def collect_cast_skills(
    casts: list[CastEvent],
    source_name_filter: str,
    action_id_filter: set[str],
) -> dict[tuple[str, str, str], int]:
    skills: dict[tuple[str, str, str], int] = {}

    for cast in casts:
        if not passes_filter(cast.name, cast.action_id, cast.source_name, cast.source_selectable, source_name_filter, action_id_filter):
            continue
        key = (cast.source_name, cast.name, cast.action_id)
        skills[key] = skills.get(key, 0) + 1

    return skills


def group_cast_suspicion(
    casts: list[CastEvent],
    source_name_filter: str,
    action_id_filter: set[str],
) -> dict[tuple[str, str], int]:
    grouped: dict[tuple[str, str], set[str]] = {}

    for cast in casts:
        if not passes_filter(cast.name, cast.action_id, cast.source_name, cast.source_selectable, source_name_filter, action_id_filter):
            continue

        # 同一技能由多个可选中来源施放过，说明可能是机制技能，但还没有多人命中证据。
        key = (cast.name, cast.action_id)
        grouped.setdefault(key, set()).add(cast.source_entity_id)

    suspected: dict[tuple[str, str], int] = {}
    for key, source_ids in grouped.items():
        if len(source_ids) >= 2:
            suspected[key] = len(source_ids)

    return suspected


def iter_cast_events(log_paths: list[Path], encoding: str) -> list[CastEvent]:
    return parse_log_data(log_paths, encoding).casts


def iter_ability_hits(log_paths: list[Path], encoding: str) -> list[AbilityHit]:
    return parse_log_data(log_paths, encoding).hits


def collect_parent_skills_with_derived_casts(
    casts: list[CastEvent],
    index: EventIndex,
    source_name_filter: str,
    action_id_filter: set[str],
    derived_name_filter: str,
    derived_window_ms: int,
    min_derived_casts: int,
) -> dict[tuple[str, str], int]:
    skills: dict[tuple[str, str], int] = {}
    candidate_children = index.casts_by_name.get(derived_name_filter, []) if derived_name_filter else casts
    # TODO(仅需关注,无任何实质性证据): 后续如需依赖下面的 break 提前退出，先按 timestamp_ms 排序。
    # 说明：多日志文件目前按文件名顺序解析，不保证等同于时间顺序；如果同名子施法跨文件乱序，
    # 先遇到 delta_ms > derived_window_ms 的未来事件时，理论上可能跳过后面仍在窗口内的事件。

    for parent in casts:
        if not passes_filter(parent.name, parent.action_id, parent.source_name, parent.source_selectable, source_name_filter, action_id_filter):
            continue

        derived_sources_by_name: dict[str, set[str]] = {}
        for child in candidate_children:
            delta_ms = child.timestamp_ms - parent.timestamp_ms
            if delta_ms <= 0:
                continue
            if delta_ms > derived_window_ms:
                break
            if derived_name_filter and child.name != derived_name_filter:
                continue
            if child.action_id == parent.action_id and child.source_entity_id == parent.source_entity_id:
                continue
            if child.name == parent.name:
                continue

            derived_sources_by_name.setdefault(child.name, set()).add(child.source_entity_id)

        derived_count = max((len(source_ids) for source_ids in derived_sources_by_name.values()), default=0)
        if derived_count >= min_derived_casts:
            key = (parent.name, parent.action_id)
            skills[key] = max(skills.get(key, 0), derived_count)

    return skills


def collect_aoe_skills(
    hits: list[AbilityHit],
    index: EventIndex,
    min_targets: int,
    event_window_ms: int,
    include_blank_names: bool,
    action_id_filter: set[str],
) -> dict[tuple[str, str], int]:
    events: dict[tuple[str, str], list[AbilityEvent]] = {}

    for hit in hits:
        if not hit.name and not include_blank_names:
            continue

        # 同一技能在短窗口内命中多个唯一目标，直接视为确认 AOE。
        key = (hit.action_id, hit.name)
        event_group = events.setdefault(key, [])
        event = next(
            (
                candidate
                for candidate in reversed(event_group)
                if 0 <= hit.timestamp_ms - candidate.timestamp_ms <= event_window_ms
            ),
            None,
        )
        if event is None:
            event = AbilityEvent(
                hit.timestamp,
                hit.timestamp_ms,
                hit.action_id,
                hit.name,
                hit.source_name,
                hit.source_entity_id,
                hit.source_selectable,
            )
            event_group.append(event)
        event.add_source(hit.source_entity_id, hit.source_selectable)
        event.add_target(hit.target_entity_id)

    skills: dict[tuple[str, str], int] = {}
    for event_group in events.values():
        for event in event_group:
            target_count = len(event.targets)
            if target_count < min_targets:
                continue

            skill_key = confirmed_skill_key(event, index)
            if action_id_filter and event.action_id not in action_id_filter and skill_key[1] not in action_id_filter:
                continue
            skills[skill_key] = max(skills.get(skill_key, 0), target_count)

    return skills


def confirmed_skill_key(event: AbilityEvent, index: EventIndex) -> tuple[str, str]:
    if event.source_selectable_values == {True}:
        return (event.name, event.action_id)
    if event.source_selectable_values != {False} or len(event.source_entity_ids) != 1:
        return (event.name, event.action_id)

    source_entity_id = next(iter(event.source_entity_ids))
    parent_cast = find_selectable_parent_cast(event, source_entity_id, index)
    if parent_cast is None:
        return (event.name, event.action_id)
    return (parent_cast.name, parent_cast.action_id)


def find_selectable_parent_cast(event: AbilityEvent, source_entity_id: str, index: EventIndex, parent_window_ms: int = 15000) -> CastEvent | None:
    child_cast: CastEvent | None = None
    for cast in index.casts_by_name.get(event.name, []):
        if cast.source_selectable:
            continue
        if cast.source_entity_id != source_entity_id:
            continue
        delay_ms = event.timestamp_ms - cast.timestamp_ms
        if not 0 <= delay_ms <= parent_window_ms:
            continue
        if child_cast is None or cast.timestamp_ms > child_cast.timestamp_ms:
            child_cast = cast

    if child_cast is None:
        return None

    for cast in reversed(index.casts_by_name.get(event.name, [])):
        if not cast.source_selectable:
            continue
        if cast.timestamp_ms > child_cast.timestamp_ms:
            continue
        if child_cast.timestamp_ms - cast.timestamp_ms > 1000:
            continue
        return cast
    return None


def merge_skill_counts(
    base: dict[tuple[str, str], int],
    extra: dict[tuple[str, str], int],
) -> dict[tuple[str, str], int]:
    for key, count in extra.items():
        base[key] = max(base.get(key, 0), count)
    return base


def unique_by_identity(items: list[T]) -> list[T]:
    seen: set[int] = set()
    unique: list[T] = []
    for item in items:
        item_id = id(item)
        if item_id in seen:
            continue
        seen.add(item_id)
        unique.append(item)
    return unique


def candidate_casts_for_skill(name: str, action_id: str, index: EventIndex) -> list[CastEvent]:
    return unique_by_identity(index.casts_by_action.get(action_id, []) + index.casts_by_name.get(name, []))


def candidate_hits_for_skill(name: str, action_id: str, index: EventIndex) -> list[AbilityHit]:
    return unique_by_identity(index.hits_by_action.get(action_id, []) + index.hits_by_name.get(name, []))


def count_window_targets(hit: AbilityHit, index: EventIndex, target_window_ms: int) -> int:
    targets: set[str] = set()
    for candidate in index.hits_by_action_name.get((hit.action_id, hit.name), []):
        if candidate.source_entity_id != hit.source_entity_id:
            continue
        if abs(candidate.timestamp_ms - hit.timestamp_ms) > target_window_ms:
            continue
        targets.add(candidate.target_entity_id)
    return len(targets)


def score_confirmation_candidate(
    action_id: str,
    expected_count: int,
    direct_target_count: int,
    cast: CastEvent,
    hit: AbilityHit,
    has_derived_cast: bool,
    delay_ms: int,
) -> tuple[int, int, int, int, int, int]:
    # 元组越小越优先：真实玩家目标 > 目标数足够/更多 > ID 精确匹配 > 有派生读条证据 > 延迟更短。
    prefer_non_self_target = 0 if hit.target_entity_id != hit.source_entity_id else 1
    prefer_enough_targets = 0 if direct_target_count >= expected_count else 1
    prefer_more_targets = -direct_target_count
    prefer_exact_hit_id = 0 if hit.action_id == action_id else 1
    prefer_exact_cast_id = 0 if cast.action_id == action_id else 1
    prefer_derived_cast_match = 0 if has_derived_cast else 1
    return (
        prefer_non_self_target,
        prefer_enough_targets,
        prefer_more_targets,
        prefer_exact_hit_id + prefer_exact_cast_id,
        prefer_derived_cast_match,
        delay_ms,
    )


def find_skill_confirmation(
    name: str,
    action_id: str,
    expected_count: int,
    hits: list[AbilityHit],
    index: EventIndex,
    max_delay_ms: int,
    target_window_ms: int,
    linked_target_window_ms: int,
) -> OutputDetail | None:
    best_score: tuple[int, int, int, int, int, int] | None = None
    best_detail: OutputDetail | None = None
    best_cast: CastEvent | None = None
    best_hit: AbilityHit | None = None

    def has_matching_derived_cast(hit: AbilityHit, parent_cast: CastEvent) -> bool:
        for child_cast in index.casts_by_action_name.get((hit.action_id, hit.name), []):
            if child_cast.source_selectable:
                continue
            if child_cast.timestamp_ms < parent_cast.timestamp_ms:
                continue
            if child_cast.timestamp_ms > hit.timestamp_ms:
                continue
            return True
        return False

    candidate_casts = candidate_casts_for_skill(name, action_id, index)
    candidate_hits = candidate_hits_for_skill(name, action_id, index)

    for cast in candidate_casts:
        if not cast.source_selectable:
            continue
        if cast.action_id != action_id and cast.name != name:
            continue

        for hit in candidate_hits:
            delay_ms = hit.timestamp_ms - cast.timestamp_ms
            if not 0 <= delay_ms <= max_delay_ms:
                continue
            if hit.action_id != action_id and hit.name != name:
                continue

            direct_target_count = count_window_targets(hit, index, target_window_ms)
            score = score_confirmation_candidate(
                action_id,
                expected_count,
                direct_target_count,
                cast,
                hit,
                has_matching_derived_cast(hit, cast),
                delay_ms,
            )
            if best_score is None or score < best_score:
                best_score = score
                best_detail = OutputDetail(
                    count=0,
                    delay_ms=str(delay_ms),
                    ability_name=hit.name,
                    ability_id=hit.action_id,
                    hit_targets="",
                )
                best_cast = cast
                best_hit = hit

    if best_detail is not None and best_cast is not None and best_hit is not None:
        targets: dict[str, str] = {}
        # 先收集最佳 AbilityEffect 同一时间窗内的直接命中目标。
        for hit in index.hits_by_action_name.get((best_hit.action_id, best_hit.name), []):
            if hit.action_id != best_hit.action_id or hit.name != best_hit.name:
                continue
            if abs(hit.timestamp_ms - best_hit.timestamp_ms) > target_window_ms:
                continue

            targets[hit.target_entity_id] = hit.target_name or hit.target_entity_id

        should_include_linked_targets = best_hit.action_id != action_id or len(targets) < expected_count
        if should_include_linked_targets:
            # 派生技能可能先命中单人，再由后续非可选中来源打出真正的群体命中。
            for hit in hits:
                delay_from_best_hit = hit.timestamp_ms - best_hit.timestamp_ms
                if not 0 < delay_from_best_hit <= linked_target_window_ms:
                    continue
                if hit.source_selectable:
                    continue
                if hit.target_entity_id == hit.source_entity_id:
                    continue

                targets[hit.target_entity_id] = hit.target_name or hit.target_entity_id

        best_detail.hit_targets = f"{len(targets)}:{','.join(targets.values())}"

    return best_detail


def enrich_skill_rows(
    rows: dict[tuple[str, str], int],
    casts: list[CastEvent],
    hits: list[AbilityHit],
    index: EventIndex,
    max_delay_ms: int,
    target_window_ms: int,
    linked_target_window_ms: int,
) -> dict[tuple[str, str], OutputDetail]:
    enriched: dict[tuple[str, str], OutputDetail] = {}

    for (name, action_id), count in rows.items():
        detail = find_skill_confirmation(
            name,
            action_id,
            count,
            hits,
            index,
            max_delay_ms,
            target_window_ms,
            linked_target_window_ms,
        )
        if detail is None:
            continue

        detail.count = count
        enriched[(name, action_id)] = detail

    return enriched


def format_output_line(name: str, action_id: str, detail: OutputDetail, with_count: bool = True) -> str:
    common = f"{name}\t{action_id}"
    if with_count:
        common = f"{common}\t{detail.count}"
    return f"{common}\t{detail.delay_ms}\t{detail.ability_name}/{detail.ability_id}\t{detail.hit_targets}"


def format_category_block(title: str, rows: dict[tuple[str, str], OutputDetail]) -> list[str]:
    lines = [f"[{title}]"]
    lines.append("技能名\tID\t数量\t技能使用到AbilityEffect耗时ms\tAbilityEffect名称/ID\t命中目标")
    for (name, action_id), detail in rows.items():
        lines.append(format_output_line(name, action_id, detail))
    lines.append("")
    return lines


def detail_record(category: str, name: str, action_id: str, detail: OutputDetail, source_name: str = "") -> OutputRecord:
    return {
        "category": category,
        "source_name": source_name,
        "skill_name": name,
        "skill_id": action_id,
        "count": detail.count,
        "delay_ms": detail.delay_ms,
        "ability_name": detail.ability_name,
        "ability_id": detail.ability_id,
        "hit_targets": detail.hit_targets,
    }


def category_records(category: str, rows: dict[tuple[str, str], OutputDetail]) -> list[OutputRecord]:
    return [detail_record(category, name, action_id, detail) for (name, action_id), detail in rows.items()]


def write_structured_output(output_path: Path, version: str, records: list[OutputRecord], output_format: str) -> None:
    if output_format == "json":
        with output_path.open("w", encoding="utf-8", newline="\n") as output:
            json.dump({"version": version, "records": records}, output, ensure_ascii=False, indent=2)
            output.write("\n")
        return

    if output_format == "csv":
        fieldnames = ["category", "source_name", "skill_name", "skill_id", "count", "delay_ms", "ability_name", "ability_id", "hit_targets"]
        with output_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            _ = writer.writeheader()
            writer.writerows(records)
        return

    raise ValueError(f"Unsupported output format: {output_format}")


def default_log_paths(workdir: Path) -> list[Path]:
    return sorted(workdir.glob("Log-*.log"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract AOE skill Name/ID pairs from AEAssist BattleLog logs."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"extract_aoe_skills {EXTRACTOR_VERSION}",
    )
    parser.add_argument(
        "logs",
        nargs="*",
        type=Path,
        help="Log files to parse. Defaults to Log-*.log in the script folder.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("aoe_skills.txt"),
        help="Output txt path. Default: aoe_skills.txt",
    )
    parser.add_argument(
        "--output-format",
        choices=("txt", "csv", "json"),
        default="txt",
        help="Output format. Default: txt",
    )
    parser.add_argument(
        "--min-targets",
        type=int,
        default=2,
        help="Minimum unique targets in one AbilityEffect event to count as AOE. Default: 2",
    )
    parser.add_argument(
        "--with-count",
        action="store_true",
        help="Also write the maximum target count seen for that skill.",
    )
    parser.add_argument(
        "--event-window-ms",
        type=int,
        default=500,
        help="Merge same skill/source hits within this many ms as one event. Default: 500",
    )
    parser.add_argument(
        "--include-blank-names",
        action="store_true",
        help="Keep AbilityEffect records whose Name field is blank.",
    )
    parser.add_argument(
        "--encoding",
        default="auto",
        help="Log encoding. Default: auto; useful values: utf-8-sig, gb18030.",
    )
    parser.add_argument(
        "--from-casts",
        action="store_true",
        help="Extract cast lines instead of multi-target AbilityEffect AOE lines.",
    )
    parser.add_argument(
        "--source-name",
        default="",
        help="Only keep cast lines from this source name, for example: 恩欧.",
    )
    parser.add_argument(
        "--action-ids",
        default="",
        help="Comma-separated action IDs to keep, for example: 50040,50032,49972.",
    )
    parser.add_argument(
        "--include-derived-casts",
        action="store_true",
        help="Also count parent casts that spawn multiple later BattleLog cast lines.",
    )
    parser.add_argument(
        "--derived-name",
        default="",
        help="Only count later derived cast lines with this skill name, for example: 奔流.",
    )
    parser.add_argument(
        "--derived-window-ms",
        type=int,
        default=8000,
        help="Window after a parent cast for derived cast detection. Default: 8000",
    )
    parser.add_argument(
        "--min-derived-casts",
        type=int,
        default=2,
        help="Minimum later cast sources needed to count a parent cast as AOE. Default: 2",
    )
    parser.add_argument(
        "--max-effect-delay-ms",
        type=int,
        default=15000,
        help="Maximum delay from selectable cast to related AbilityEffect. Default: 15000",
    )
    parser.add_argument(
        "--target-window-ms",
        type=int,
        default=500,
        help="Window for grouping AbilityEffect targets into one hit list. Default: 500",
    )
    parser.add_argument(
        "--linked-target-window-ms",
        type=int,
        default=1500,
        help="Window after a derived AbilityEffect for linked follow-up hit targets. Default: 1500",
    )
    parser.add_argument(
        "-all",
        "--all",
        action="store_true",
        help="Export confirmed AOE, high-suspicion AOE, and suspected AOE into one txt file.",
    )
    return parser.parse_args()


def resolve_log_paths(log_args: list[Path], script_dir: Path) -> list[Path]:
    log_paths = log_args or default_log_paths(script_dir)
    return [path if path.is_absolute() else script_dir / path for path in log_paths]


def validate_args(args: argparse.Namespace) -> None:
    if args.min_targets < 1:
        raise ValueError("--min-targets must be >= 1")
    if args.event_window_ms < 0:
        raise ValueError("--event-window-ms must be >= 0")
    if args.derived_window_ms < 0:
        raise ValueError("--derived-window-ms must be >= 0")
    if args.min_derived_casts < 1:
        raise ValueError("--min-derived-casts must be >= 1")
    if args.max_effect_delay_ms < 0:
        raise ValueError("--max-effect-delay-ms must be >= 0")
    if args.target_window_ms < 0:
        raise ValueError("--target-window-ms must be >= 0")
    if args.linked_target_window_ms < 0:
        raise ValueError("--linked-target-window-ms must be >= 0")
    if args.all and args.from_casts:
        raise ValueError("--all cannot be combined with --from-casts")
    if args.all and args.with_count:
        raise ValueError("--all always includes the count column; do not combine it with --with-count")


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    log_paths = resolve_log_paths(args.logs, script_dir)

    missing = [str(path) for path in log_paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Log file not found: " + ", ".join(missing))

    validate_args(args)

    action_id_filter = parse_action_ids(args.action_ids)

    parsed_logs = parse_log_data(log_paths, args.encoding)
    event_index = build_event_index(parsed_logs.casts, parsed_logs.hits)

    output_lines: list[str] = []
    cast_skills: dict[tuple[str, str, str], int] = {}
    cast_details: dict[tuple[str, str], OutputDetail] = {}
    skill_details: dict[tuple[str, str], OutputDetail] = {}
    confirmed_details: dict[tuple[str, str], OutputDetail] = {}
    high_suspected_details: dict[tuple[str, str], OutputDetail] = {}
    suspected_details: dict[tuple[str, str], OutputDetail] = {}

    if args.all:
        confirmed = collect_aoe_skills(
            parsed_logs.hits,
            event_index,
            args.min_targets,
            args.event_window_ms,
            args.include_blank_names,
            action_id_filter,
        )
        high_suspected = collect_parent_skills_with_derived_casts(
            parsed_logs.casts,
            event_index,
            args.source_name,
            action_id_filter,
            args.derived_name,
            args.derived_window_ms,
            args.min_derived_casts,
        )
        high_suspected = dict(
            (key, count)
            for key, count in high_suspected.items()
            if key not in confirmed
        )
        suspected = group_cast_suspicion(
            parsed_logs.casts,
            args.source_name,
            action_id_filter,
        )
        for key in list(confirmed.keys()) + list(high_suspected.keys()):
            # 按“确认 > 高度疑似 > 疑似”去重，避免同一技能重复输出。
            _ = suspected.pop(key, None)

        confirmed_details = enrich_skill_rows(
            confirmed,
            parsed_logs.casts,
            parsed_logs.hits,
            event_index,
            args.max_effect_delay_ms,
            args.target_window_ms,
            args.linked_target_window_ms,
        )
        high_suspected_details = enrich_skill_rows(
            high_suspected,
            parsed_logs.casts,
            parsed_logs.hits,
            event_index,
            args.max_effect_delay_ms,
            args.target_window_ms,
            args.linked_target_window_ms,
        )
        suspected_details = enrich_skill_rows(
            suspected,
            parsed_logs.casts,
            parsed_logs.hits,
            event_index,
            args.max_effect_delay_ms,
            args.target_window_ms,
            args.linked_target_window_ms,
        )

        output_lines.extend(format_category_block("确认的aoe", confirmed_details))
        output_lines.extend(format_category_block("高度疑似的Aoe", high_suspected_details))
        output_lines.extend(format_category_block("疑似Aoe", suspected_details))
    elif args.from_casts:
        cast_skills = collect_cast_skills(
            parsed_logs.casts,
            args.source_name,
            action_id_filter,
        )
        cast_detail_rows: dict[tuple[str, str], int] = {}
        for (_, name, action_id), cast_count in cast_skills.items():
            cast_detail_rows[(name, action_id)] = max(cast_detail_rows.get((name, action_id), 0), cast_count)
        # TODO(仅需关注,无任何实质性证据): 如需精确区分同名同 ID 的不同来源，可把 source_name 纳入补全键。
        # 说明：当前 --from-casts 为同一个 (name, action_id) 复用一份 detail；若未来日志中多个来源
        # 同时拥有各自的 AbilityEffect 详情，可能需要改成按 (source_name, name, action_id) 独立匹配。
        cast_details = enrich_skill_rows(
            cast_detail_rows,
            parsed_logs.casts,
            parsed_logs.hits,
            event_index,
            args.max_effect_delay_ms,
            args.target_window_ms,
            args.linked_target_window_ms,
        )
    else:
        skills = collect_aoe_skills(
            parsed_logs.hits,
            event_index,
            args.min_targets,
            args.event_window_ms,
            args.include_blank_names,
            action_id_filter,
        )
        if args.include_derived_casts:
            derived_skills = collect_parent_skills_with_derived_casts(
                parsed_logs.casts,
                event_index,
                args.source_name,
                action_id_filter,
                args.derived_name,
                args.derived_window_ms,
                args.min_derived_casts,
            )
            skills = merge_skill_counts(skills, derived_skills)
        skill_details = enrich_skill_rows(
            skills,
            parsed_logs.casts,
            parsed_logs.hits,
            event_index,
            args.max_effect_delay_ms,
            args.target_window_ms,
            args.linked_target_window_ms,
        )
    output_path = args.output if args.output.is_absolute() else script_dir / args.output

    structured_records: list[OutputRecord] = []
    # CSV/JSON 使用扁平 records；TXT 保持原来的分区文本格式。
    if args.all:
        structured_records.extend(category_records("确认的aoe", confirmed_details))
        structured_records.extend(category_records("高度疑似的Aoe", high_suspected_details))
        structured_records.extend(category_records("疑似Aoe", suspected_details))
    elif args.from_casts:
        for (source_name, name, action_id), _ in cast_skills.items():
            detail = cast_details.get((name, action_id))
            if detail is not None:
                structured_records.append(detail_record("from_casts", name, action_id, detail, source_name))
    else:
        structured_records.extend(category_records("aoe", skill_details))

    if args.output_format != "txt":
        write_structured_output(output_path, EXTRACTOR_VERSION, structured_records, args.output_format)
    else:
        with output_path.open("w", encoding="utf-8", newline="\n") as output:
            output.write(f"来自[{EXTRACTOR_VERSION}]提取器\n")
            if args.all:
                output.write("\n".join(output_lines))
                output.write("\n")
            elif args.from_casts:
                for (source_name, name, action_id), cast_count in cast_skills.items():
                    detail = cast_details.get((name, action_id))
                    if detail is None:
                        continue

                    prefix = f"{source_name} - {name} - {action_id}"
                    if args.with_count:
                        output.write(
                            f"{prefix}\t{detail.count}\t{detail.delay_ms}\t{detail.ability_name}/{detail.ability_id}\t{detail.hit_targets}\n"
                        )
                    else:
                        output.write(
                            f"{prefix}\t{detail.delay_ms}\t{detail.ability_name}/{detail.ability_id}\t{detail.hit_targets}\n"
                        )
            else:
                for (name, action_id), detail in skill_details.items():
                    if args.with_count:
                        output.write(format_output_line(name, action_id, detail) + "\n")
                    else:
                        output.write(format_output_line(name, action_id, detail, with_count=False) + "\n")

    if args.all:
        found_count = len(confirmed_details) + len(high_suspected_details) + len(suspected_details)
        result_type = "classified AOE entry"
    else:
        found_count = len(cast_skills) if args.from_casts else len(skill_details)
        result_type = "cast skill" if args.from_casts else "AOE skill"
    print(f"Parsed {len(log_paths)} log file(s). Found {found_count} {result_type}(s).")
    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
