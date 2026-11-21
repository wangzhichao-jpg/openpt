# SPDX-License-Identifier: Apache-2.0
"""指定值表的中文标签及兼容旧工作簿的字段键。"""

import re

ASSIGNED_LABELS = {
    "method": "定值方法",
    "value": "指定值",
    "uncertainty": "指定值基础标准不确定度",
    "source": "指定值来源说明",
    "uncertainty_source": "指定值不确定度来源说明",
    "consensus_method": "参加者公议计算方法",
    "sigma_temporary": "临时能力评定标准差",
    "sigma_final": "最终能力评定标准差",
    "sigma_procedure": "能力评定标准差确定程序",
    "u_hom": "均匀性标准不确定度分量",
    "u_stab": "稳定性标准不确定度分量",
    "hom_mapping": "均匀性分量映射",
    "stab_mapping": "稳定性分量映射",
    "hom_in_base": "基础不确定度已含均匀性分量",
    "stab_in_base": "基础不确定度已含稳定性分量",
    "U_assigned": "指定值扩展不确定度",
    "k_assigned": "指定值扩展不确定度包含因子",
    "independent": "参加者结果与指定值不相关",
    "known_components": "已知值制备标准不确定度分量",
    "expert_values": "专家公议结果列表",
    "hom_source": "均匀性分量来源",
    "u_trans": "运输标准不确定度分量",
    "trans_mapping": "运输分量映射",
    "trans_in_base": "基础不确定度已含运输分量",
    "trans_in_stab": "稳定性分量已含运输分量",
    "stability_disposition": "稳定性处置状态",
    "stability_disposition_reason": "稳定性处置书面依据",
    "sigma_pt_method": "能力评定标准差确定方法",
    "sigma_pt_sig_digits": "能力评定标准差修约有效位数",
}


def field_key(label: object) -> str:
    """将中文（英文）标签及旧英文标签统一为英文键。"""
    text = str(label or "")
    match = re.search(r"（([a-zA-Z_][a-zA-Z_0-9]*)）$", text)
    return match.group(1) if match else text


def field_label(key: str) -> str:
    """返回中文与英文均可见的字段名；未知字段保留原文。"""
    return f"{ASSIGNED_LABELS[key]}（{key}）" if key in ASSIGNED_LABELS else key
