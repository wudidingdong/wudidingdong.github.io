import os
import re
from scholarly import scholarly

# 从GitHub Actions的环境变量中获取您的谷歌学术ID
# 我们稍后会在GitHub仓库的设置中配置这个ID，这样更安全
author_id = os.environ.get("GOOGLE_SCHOLAR_ID")
if not author_id:
    raise ValueError("环境变量 GOOGLE_SCHOLAR_ID 未设置！")

# 您主页HTML文件的路径，通常是仓库根目录下的 index.html
html_file_path = 'index.html'

def fetch_h10_index(author_id):
    """获取指定作者的 h-10 index (在scholarly中叫 i10_index)"""
    try:
        print(f"正在为作者ID {author_id} 获取数据...")
        author = scholarly.search_author_id(author_id)
        filled_author = scholarly.fill(author, sections=['indices'])
        # scholarly库将h-10 index命名为'i10_index'
        h10_index = filled_author.get('i10_index', 0)
        print(f"成功获取 h-10 index: {h10_index}")
        return h10_index
    except Exception as e:
        print(f"获取谷歌学术数据时出错: {e}")
        return None

def update_html_file(file_path, new_h10_index):
    """读取HTML文件，找到占位符并更新h-10 index"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 使用正则表达式安全地替换占位符之间的内容
        # 模式会匹配和之间的所有内容
        pattern = r"()(.*?)()"
        
        # 替换为新的index值
        replacement = f"\\1{new_h10_index}\\3"
        new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

        if count > 0:
            print(f"在 {file_path} 中找到并更新了 {count} 处 h-10 index。")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        else:
            print(f"警告：在 {file_path} 中未找到h-10 index的占位符。")
            print("请确保您的HTML文件包含 ...")

    except FileNotFoundError:
        print(f"错误：找不到文件 {file_path}。")
    except Exception as e:
        print(f"更新HTML文件时出错: {e}")

if __name__ == "__main__":
    latest_h10_index = fetch_h10_index(author_id)
    if latest_h10_index is not None:
        update_html_file(html_file_path, latest_h10_index)
