#!/usr/bin/env python3
"""校验 knowledge_base/moves.json 的结构与自洽性。

用法: python3 knowledge_base/kb_lint.py
全部通过打印 "lint passed: N moves" 并以 0 退出。
有问题打印错误列表（文件+id+字段+原因）并以非 0 退出码结束。
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOVES_PATH = os.path.join(HERE, "moves.json")
REL_PATH = os.path.relpath(MOVES_PATH, os.path.dirname(HERE))

CATEGORIES = {
    "調節平衡類", "吊掛類", "推拉類", "反作用力類", "動態移動類",
    "攀岩的手順", "腳法基礎", "手塞", "腳塞", "擠塞",
}

KINDS = {"posture", "action"}

DETECTABILITY = {"rule", "rule_weak", "vision", "manual"}

# 特征注册表白名单（帧级 + 段级），必须与 PLAN / skill 描述保持一致
FRAME_FEATURES = {
    "ankle_rel_hip_y", "knee_rel_hip_y", "wrist_rel_shoulder_y",
    "knee_angle", "elbow_angle", "hip_angle",
    "heel_leads_toe_x", "foot_pitch", "ankle_cross_midline",
    "feet_spread", "hands_gap", "wrists_crossed",
    "shoulder_width_ratio", "hip_wall_proxy", "torso_lean",
}
# 对应的可见度特征：任意帧级特征名 + "_visibility"
FRAME_VISIBILITY_FEATURES = {f"{name}_visibility" for name in FRAME_FEATURES}
# 常用的单点可见度特征（关键点级别，而非派生特征级别）
POINT_VISIBILITY_FEATURES = {
    "ankle_visibility", "knee_visibility", "wrist_visibility",
    "hip_visibility", "shoulder_visibility", "heel_visibility",
    "foot_index_visibility", "elbow_visibility",
}

SEGMENT_FEATURES = {
    "dominant_limb", "displacement_direction", "displacement_magnitude",
    "peak_com_speed", "both_hands_release_simultaneously",
    "hip_height_change_pre_post", "segment_duration_s",
}

FEATURE_WHITELIST = (
    FRAME_FEATURES
    | FRAME_VISIBILITY_FEATURES
    | POINT_VISIBILITY_FEATURES
    | SEGMENT_FEATURES
)

REQUIRED_STR_FIELDS = [
    "id", "name_zh", "category", "kind", "book_ref",
    "description", "when_to_use", "detectability",
    "visual_cues_for_claude",
]
REQUIRED_LIST_FIELDS = ["aliases", "pose_rules", "common_errors", "confusable_with"]

SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


def fail(errors, file_ref, move_id, field, reason):
    errors.append(f"{file_ref} | id={move_id!r} | field={field} | {reason}")


def check_pose_rule(rule, idx, move_id, errors):
    prefix = f"pose_rules[{idx}]"
    if not isinstance(rule, dict):
        fail(errors, REL_PATH, move_id, prefix, "pose_rules 中的元素必须是对象")
        return

    feature = rule.get("feature")
    if not isinstance(feature, str) or not feature:
        fail(errors, REL_PATH, move_id, f"{prefix}.feature", "缺失或不是字符串")
    elif feature not in FEATURE_WHITELIST:
        fail(errors, REL_PATH, move_id, f"{prefix}.feature",
             f"特征名 {feature!r} 不在特征注册表白名单内")

    rng = rule.get("range")
    if not isinstance(rng, list) or len(rng) != 2:
        fail(errors, REL_PATH, move_id, f"{prefix}.range", "range 必须是长度为2的数组")
    else:
        lo, hi = rng
        if not (isinstance(lo, (int, float)) and isinstance(hi, (int, float))):
            fail(errors, REL_PATH, move_id, f"{prefix}.range", "range 的两个元素必须是数字")
        elif not (lo < hi):
            fail(errors, REL_PATH, move_id, f"{prefix}.range", f"range 要求 lo<hi，实际为 [{lo}, {hi}]")

    if "soft" not in rule:
        fail(errors, REL_PATH, move_id, f"{prefix}.soft", "缺失 soft 字段")
    elif not isinstance(rule.get("soft"), (int, float)):
        fail(errors, REL_PATH, move_id, f"{prefix}.soft", "soft 必须是数值（可为0）")

    weight = rule.get("weight")
    if not isinstance(weight, (int, float)):
        fail(errors, REL_PATH, move_id, f"{prefix}.weight", "缺失或不是数值")
    elif not (0 <= weight <= 1):
        fail(errors, REL_PATH, move_id, f"{prefix}.weight", f"weight 必须在 [0,1] 内，实际为 {weight}")

    if "gate" in rule and not isinstance(rule["gate"], bool):
        fail(errors, REL_PATH, move_id, f"{prefix}.gate", "gate 若存在必须是布尔值")

    if "side" in rule and rule["side"] not in ("left", "right", "either"):
        fail(errors, REL_PATH, move_id, f"{prefix}.side",
             f"side 若存在必须是 left/right/either，实际为 {rule['side']!r}")


def main():
    if not os.path.exists(MOVES_PATH):
        print(f"❌ 找不到文件: {MOVES_PATH}")
        sys.exit(1)

    with open(MOVES_PATH, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ JSON 解析失败: {e}")
            sys.exit(1)

    errors = []

    if not isinstance(data, list):
        print("❌ 顶层必须是数组")
        sys.exit(1)

    seen_ids = {}
    for i, move in enumerate(data):
        move_id = move.get("id") if isinstance(move, dict) else None
        ref = move_id if move_id else f"<index {i}>"

        if not isinstance(move, dict):
            fail(errors, REL_PATH, ref, "<root>", "每条记录必须是对象")
            continue

        # id
        if not isinstance(move.get("id"), str) or not move["id"]:
            fail(errors, REL_PATH, ref, "id", "缺失或不是字符串")
        else:
            if not SNAKE_CASE_RE.match(move["id"]):
                fail(errors, REL_PATH, ref, "id", f"{move['id']!r} 不是合法的 snake_case 格式")
            seen_ids.setdefault(move["id"], 0)
            seen_ids[move["id"]] += 1

        # 必填字符串字段
        for field in REQUIRED_STR_FIELDS:
            if field not in move:
                fail(errors, REL_PATH, ref, field, "缺失该字段")
            elif not isinstance(move[field], str) or not move[field].strip():
                fail(errors, REL_PATH, ref, field, "必须是非空字符串")

        # 必填列表字段
        for field in REQUIRED_LIST_FIELDS:
            if field not in move:
                fail(errors, REL_PATH, ref, field, "缺失该字段")
            elif not isinstance(move[field], list):
                fail(errors, REL_PATH, ref, field, "必须是数组（可为空数组）")

        # aliases 内容类型
        if isinstance(move.get("aliases"), list):
            for a in move["aliases"]:
                if not isinstance(a, str):
                    fail(errors, REL_PATH, ref, "aliases", f"元素必须是字符串，实际为 {a!r}")

        # common_errors 内容类型
        if isinstance(move.get("common_errors"), list):
            for a in move["common_errors"]:
                if not isinstance(a, str):
                    fail(errors, REL_PATH, ref, "common_errors", f"元素必须是字符串，实际为 {a!r}")

        # confusable_with 内容类型（自洽性稍后统一检查）
        if isinstance(move.get("confusable_with"), list):
            for a in move["confusable_with"]:
                if not isinstance(a, str):
                    fail(errors, REL_PATH, ref, "confusable_with", f"元素必须是字符串，实际为 {a!r}")

        # category
        category = move.get("category")
        if category not in CATEGORIES:
            fail(errors, REL_PATH, ref, "category", f"{category!r} 不在允许的分类枚举内: {sorted(CATEGORIES)}")

        # kind
        kind = move.get("kind")
        if kind not in KINDS:
            fail(errors, REL_PATH, ref, "kind", f"{kind!r} 必须是 posture 或 action")

        # detectability
        detectability = move.get("detectability")
        if detectability not in DETECTABILITY:
            fail(errors, REL_PATH, ref, "detectability",
                 f"{detectability!r} 必须是 rule/rule_weak/vision/manual 之一")

        # pose_rules 逐条校验
        if isinstance(move.get("pose_rules"), list):
            for idx, rule in enumerate(move["pose_rules"]):
                check_pose_rule(rule, idx, ref, errors)

        # min_hold_s：仅 posture 类需要
        if kind == "posture":
            mhs = move.get("min_hold_s")
            if mhs is None:
                fail(errors, REL_PATH, ref, "min_hold_s", "posture 类动作必须提供 min_hold_s")
            elif not isinstance(mhs, (int, float)) or mhs <= 0:
                fail(errors, REL_PATH, ref, "min_hold_s", "必须是正数")
        elif kind == "action":
            if "min_hold_s" in move and move.get("min_hold_s") is not None:
                fail(errors, REL_PATH, ref, "min_hold_s", "action 类动作不应提供 min_hold_s")

    # id 全局唯一
    for move_id, count in seen_ids.items():
        if count > 1:
            fail(errors, REL_PATH, move_id, "id", f"id 重复出现 {count} 次，必须全局唯一")

    # confusable_with 自洽性检查：引用的 id 必须真实存在
    all_ids = set(seen_ids.keys())
    for move in data:
        if not isinstance(move, dict):
            continue
        move_id = move.get("id", "<unknown>")
        for ref_id in move.get("confusable_with", []) or []:
            if isinstance(ref_id, str) and ref_id not in all_ids:
                fail(errors, REL_PATH, move_id, "confusable_with",
                     f"引用的 id {ref_id!r} 在 moves.json 中不存在")

    if errors:
        print(f"❌ lint failed: {len(errors)} 个问题")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"✅ lint passed: {len(data)} moves")
    sys.exit(0)


if __name__ == "__main__":
    main()
