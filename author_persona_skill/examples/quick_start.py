#!/usr/bin/env python3
"""
作家分身Skill - 快速开始示例
演示如何在各种Agent平台上使用此Skill
"""

import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from author_persona_skill import AuthorPersonaSkill
from author_persona_skill.api import create_api
from author_persona_skill.platforms import DifySkillAdapter, CozeSkillAdapter


def example_basic_usage():
    """基础使用示例"""
    print("=" * 60)
    print("示例1：基础使用")
    print("=" * 60)

    # 创建Skill实例
    skill = AuthorPersonaSkill()

    # 示例小说语料
    sample_corpus = """
    夜色如墨，月光透过树叶的缝隙洒在青石板路上，斑驳陆离。
    她静静地站在古树下，手中握着那柄冰凉的青铜古剑，指节因为用力而泛白。
    风轻轻吹过，撩起她的衣角，也吹来了远方若有若无的笛声。
    "你来了。"一个低沉的声音从树后传来。
    她没有回头，只是微微颔首，"我知道你会来。"
    树影婆娑，那个身影缓缓走出，月光照亮了他坚毅的脸庞。
    "这一天，我等了很久。"他的声音里带着一丝沧桑。
    她终于转过身，四目相对的瞬间，时间仿佛静止了。
    """

    # 1. 分析风格
    print("\n1. 分析风格...")
    analyze_result = skill.analyze_style(sample_corpus, "示例作家")
    if analyze_result["success"]:
        print("✓ 风格分析完成！")
        print(f"  定量摘要：{analyze_result['quantitative_summary']}")

        # 保存风格指纹
        style_profile = analyze_result["style_profile"]
    else:
        print(f"✗ 分析失败：{analyze_result.get('error')}")
        return

    # 2. 编译分身
    print("\n2. 编译分身提示词...")
    compile_result = skill.compile_persona(style_profile, "示例作家")
    if compile_result["success"]:
        print("✓ 编译完成！")
        persona_prompt = compile_result["persona_prompt"]
        print(f"  提示词长度：{len(persona_prompt)} 字符")
    else:
        print(f"✗ 编译失败：{compile_result.get('error')}")
        return

    # 3. 使用分身（无LLM时返回提示词模板）
    print("\n3. 生成分身创作提示...")
    user_request = "写一段古城相遇的场景，带点悬疑氛围"
    generate_result = skill.generate_with_persona(persona_prompt, user_request)

    if generate_result["success"]:
        if "warning" in generate_result:
            print(f"⚠️  {generate_result['warning']}")
            print(f"  提示词模板已生成，可手动使用")
        else:
            print("✓ 生成完成！")
            print(f"  生成结果：{generate_result.get('final_text', '')[:100]}...")

    print("\n" + "=" * 60)


def example_api_usage():
    """API使用示例"""
    print("\n" + "=" * 60)
    print("示例2：API使用")
    print("=" * 60)

    # 创建API实例
    api = create_api()

    # 示例小说语料
    sample_corpus = """
    夜色如墨，月光透过树叶的缝隙洒在青石板路上，斑驳陆离。
    她静静地站在古树下，手中握着那柄冰凉的青铜古剑，指节因为用力而泛白。
    """

    # 使用统一的请求格式
    print("\n完整工作流API调用...")
    request = {
        "action": "complete_workflow",
        "params": {
            "corpus_text": sample_corpus,
            "author_name": "示例作家",
            "user_request": "写一段古城相遇的场景",
            "enable_iteration": False
        }
    }

    result = api.handle_request(request)

    if result["success"]:
        print("✓ API调用成功！")
        if "persona_prompt" in result:
            print(f"  生成提示词成功")
    else:
        print(f"✗ API调用失败：{result.get('error')}")


def example_platform_adapters():
    """平台适配器使用示例"""
    print("\n" + "=" * 60)
    print("示例3：平台适配器")
    print("=" * 60)

    # Dify平台示例
    print("\nDify平台适配器...")
    dify_adapter = DifySkillAdapter()

    dify_input = {
        "action": "analyze_style",
        "corpus_text": "夜色如墨，月光透过树叶的缝隙...",
        "author_name": "示例作家"
    }

    dify_output = dify_adapter.run(dify_input)
    print(f"Dify输出：{'成功' if dify_output.get('success') else '失败'}")

    # Coze平台示例
    print("\nCoze平台适配器...")
    coze_adapter = CozeSkillAdapter()

    coze_request = {
        "method": "analyze_style",
        "parameters": {
            "corpus_text": "夜色如墨，月光透过树叶的缝隙...",
            "author_name": "示例作家"
        }
    }

    coze_output = coze_adapter.handle_plugin_call(coze_request)
    print(f"Coze输出状态：{coze_output.get('status')}")


def main():
    """主函数"""
    print("\n" + "#" * 60)
    print("# 作家分身Skill - 快速开始")
    print("#" * 60)

    example_basic_usage()
    example_api_usage()
    example_platform_adapters()

    print("\n" + "#" * 60)
    print("# 示例执行完毕！")
    print("#" * 60)
    print("\n下一步：")
    print("  1. 准备你的小说语料")
    print("  2. 配置LLM API密钥（可选，用于完整功能）")
    print("  3. 在你的Agent平台上安装此Skill")


if __name__ == "__main__":
    main()
