#!/usr/bin/env python3
"""
作家分身技能 - 真实运行测试
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from author_persona_skill import AuthorPersonaSkill

def main():
    print("=" * 70)
    print("作家分身技能 - 真实运行测试")
    print("=" * 70)
    
    # 1. 读取小说文本
    novel_path = os.path.join(os.path.dirname(__file__), "末日分解1.txt")
    print(f"\n[1/4] 正在读取小说文本: {novel_path}")
    
    if not os.path.exists(novel_path):
        print("❌ 文件不存在！")
        return
    
    with open(novel_path, 'r', encoding='utf-8') as f:
        # 取前6000字进行分析
        full_text = f.read()
        sample_text = full_text[:6000]
        print(f"✓ 读取成功！共 {len(full_text)} 字符")
        print(f"✓ 分析样本长度: {len(sample_text)} 字符")
    
    # 2. 初始化技能
    print("\n[2/4] 初始化作家分身技能...")
    skill = AuthorPersonaSkill()
    print("✓ 技能初始化完成！")
    
    # 3. 定量风格分析
    print("\n[3/4] 正在进行定量风格分析...")
    try:
        features = skill.analyze_style(sample_text)
        print("✓ 分析成功！")
        
        # 展示分析结果
        print("\n" + "-" * 50)
        print("【定量分析结果】")
        print("-" * 50)
        
        vocab = features.get('vocabulary', {})
        print(f"\n【词汇特征】")
        print(f"  总词数: {vocab.get('total_words', 0)}")
        print(f"  独特词数: {vocab.get('unique_words', 0)}")
        print(f"  词汇丰富度(TTR): {vocab.get('ttr', 0):.3f}")
        print(f"  功能词占比: {vocab.get('function_word_ratio', 0):.2%}")
        print(f"  高频词(前10): {', '.join(vocab.get('top_words', [])[:10])}")
        
        sent = features.get('sentence', {})
        print(f"\n【句子特征】")
        print(f"  总句数: {sent.get('total_sentences', 0)}")
        print(f"  平均句长: {sent.get('avg_length', 0):.1f} 字")
        print(f"  短句率(<8字): {sent.get('short_rate', 0):.1f}%")
        print(f"  长句率(>30字): {sent.get('long_rate', 0):.1f}%")
        
        punct = features.get('punctuation', {})
        print(f"\n【标点特征】")
        punct_counts = punct.get('counts', {})
        print(f"  常用标点: {', '.join([k for k, v in sorted(punct_counts.items(), key=lambda x: -x[1])[:8]])}")
        
        para = features.get('paragraph', {})
        print(f"\n【段落特征】")
        print(f"  段落数: {para.get('total_paragraphs', 0)}")
        print(f"  平均段长: {para.get('avg_length', 0):.1f} 字")
        print(f"  对话次数: {para.get('dialogue_count', 0)}")
        
    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 4. 获取分析提示词模板
    print("\n[4/4] 编译作家分身提示词...")
    
    # 只用定量数据简单编译一个
    persona_prompt = skill.compile_persona(
        author_name="末日分解作者",
        quantitative_features=features
    )
    
    print("✓ 编译完成！")
    
    # 展示结果
    print("\n" + "=" * 70)
    print("【作家分身提示词】")
    print("=" * 70)
    print(persona_prompt)
    print("\n" + "=" * 70)
    
    # 保存结果
    result_path = os.path.join(os.path.dirname(__file__), "test_result.txt")
    with open(result_path, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("【作家分身技能分析结果】\n")
        f.write("=" * 70 + "\n")
        f.write(f"\n分析样本: {len(sample_text)} 字符\n")
        f.write(f"\n定量特征:\n{repr(features)}\n")
        f.write("\n" + "=" * 70 + "\n")
        f.write("【作家分身提示词】\n")
        f.write("=" * 70 + "\n")
        f.write(persona_prompt + "\n")
    
    print(f"\n✓ 结果已保存到: {result_path}")
    print("\n🎉 测试完成！")

if __name__ == "__main__":
    main()
