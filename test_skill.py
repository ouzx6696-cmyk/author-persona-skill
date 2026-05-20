#!/usr/bin/env python3
"""
作家分身技能 - 简单测试示例
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from author_persona_skill import AuthorPersonaSkill


def main():
    print("=" * 50)
    print("作家分身技能 - 测试示例")
    print("=" * 50)

    # 初始化技能
    skill = AuthorPersonaSkill()

    # 测试文本（一小段金庸风格）
    test_text = """
    夜色如墨，月光透过梧桐枝叶，在青石板路上投下斑驳的影。
    远处传来更夫的梆子声，一下，一下，敲得人心头紧。
    杨过立在墙头，望着襄阳城的方向，手中玄铁重剑微微颤动。
    """

    print("\n1. 测试文本：")
    print(test_text.strip())

    # 1. 测试风格分析
    print("\n" + "=" * 50)
    print("2. 定量风格分析...")
    try:
        features = skill.analyze_style(test_text)
        print("✓ 分析成功！")
        print(f"- 平均句长: {features['sentence']['avg_length']}字")
        print(f"- 短句比例: {features['sentence']['short_rate']}%")
        print(f"- 词汇丰富度(TTR): {features['vocabulary']['ttr']}")
        print(f"- 常用词: {', '.join(features['vocabulary']['top_words'][:5])}")
    except Exception as e:
        print(f"✗ 分析失败: {e}")
        return

    # 2. 获取分析提示词
    print("\n" + "=" * 50)
    print("3. LLM分析提示词模板：")
    prompt = skill.get_analysis_prompt()
    print(prompt[:200] + "...")

    # 3. 编译提示词
    print("\n" + "=" * 50)
    print("4. 编译作家分身提示词...")
    persona = skill.compile_persona(
        author_name="测试作家",
        quantitative_features=features
    )
    print("\n" + persona)

    print("\n" + "=" * 50)
    print("✓ 所有测试完成！")
    print("\n提示：")
    print("- 把 author_persona_skill 目录打包成zip，就可以上传到Agent平台了！")
    print("- 在平台上调用这些工具函数，创建你的作家分身！")


if __name__ == "__main__":
    main()
