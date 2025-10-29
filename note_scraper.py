import requests
import json
import os
import time
import html2text
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# .envファイルから環境変数を読み込む
load_dotenv()

# --- 設定 ---
USER_ID = "genel"
OUTPUT_DIR = f"./{USER_ID}_articles"

def sanitize_filename(title):
    """ファイル名として安全な文字列に変換する"""
    # 英数字、日本語（ひらがな、カタカナ、漢字）、アンダースコア、ハイフン以外の文字をすべてアンダースコアに置換
    cleaned_title = re.sub(r'[^a-zA-Z0-9_\-\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]+', "_", title)
    # 連続するアンダースコアを1つにまとめる
    cleaned_title = re.sub(r'__+', "_", cleaned_title)
    # 先頭と末尾のアンダースコアを除去
    cleaned_title = cleaned_title.strip("_")
    return cleaned_title

def get_all_notes_info(user_id):
    """指定されたユーザーの全記事キーとハッシュタグの情報を取得します。"""
    all_notes = {}
    page = 1
    print("全記事の基本情報（キー、ハッシュタグ）の取得を開始します...")
    while True:
        try:
            print(f"{page}ページ目の記事一覧を取得中...")
            url = f"https://note.com/api/v2/creators/{user_id}/contents?kind=note&page={page}"
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            data = res.json()["data"]

            if not data["contents"]:
                break

            for content in data["contents"]:
                key = content.get("key")
                if key:
                    hashtags = [tag["hashtag"]["name"] for tag in content.get("hashtags", []) if "hashtag" in tag and tag.get("hashtag")]
                    title = content.get("name", "無題")
                    all_notes[key] = {"hashtags": hashtags, "title": title}

            if data["isLastPage"]:
                break
            page += 1
            time.sleep(3)
        except Exception as e:
            print(f"エラー: 記事一覧の取得中に失敗しました。 {e}")
            return None
    print("すべての基本情報を取得しました。")
    return all_notes

def get_note_detail(note_key):
    """認証情報を使って、指定されたキーのnote記事詳細を取得します。"""
    token1 = os.getenv("NOTE_GQL_AUTH_TOKEN")
    token2 = os.getenv("_NOTE_SESSION_V5")

    cookies = {}
    if token1 and token2:
        cookies['note_gql_auth_token'] = token1
        cookies['_note_session_v5'] = token2
    else:
        print("警告: .envファイルに必要な認証トークンが見つかりません。無料部分のみ取得します。")

    try:
        url = f"https://note.com/api/v3/notes/{note_key}"
        res = requests.get(url, timeout=10, cookies=cookies)
        res.raise_for_status()
        return res.json()["data"]
    except Exception as e:
        print(f"    -> エラー: 記事詳細の取得に失敗しました。 {note_key}, {e}")
        return None

def save_as_markdown(note_key, note_info, all_notes_info, output_dir):
    """記事データを処理し、Markdownファイルとして保存します。"""
    try:
        note_detail = get_note_detail(note_key)
        if not note_detail:
            return

        title = note_detail.get("name", "無題")
        eyecatch_url = note_detail.get("eyecatch")
        body_html = note_detail.get("body", "")
        
        hashtags_from_list = note_info.get("hashtags", [])
        hashtags_from_detail = [t["hashtag"]["name"] for t in note_detail.get("hashtag_notes", []) if "hashtag" in t and t.get("hashtag")]
        hashtags = sorted(list(set(hashtags_from_list + hashtags_from_detail)))

        soup = BeautifulSoup(body_html, "html.parser")
        
        replacements_after_md = []

        for figure in soup.find_all("figure", attrs={"embedded-service": "note"}):
            related_key = figure.get("data-identifier")
            if not related_key or related_key == note_key: continue

            print(f"    -> 関連記事リンク発見: {related_key}。詳細を取得中...")
            time.sleep(3)
            related_detail = get_note_detail(related_key)

            if related_detail:
                original_related_title = all_notes_info.get(related_key, {}).get("title", related_detail.get("name", "無題"))
                safe_related_title = sanitize_filename(original_related_title)
                internal_link_target = f"{related_key}_{safe_related_title}"
                external_url = related_detail.get("note_url", "")
                related_eyecatch_url = related_detail.get("eyecatch", "")

                final_markdown_link = f"[[{internal_link_target}]][🌐]({external_url})"
                if related_eyecatch_url:
                    final_markdown_link += f"\n\n![thumbnail]({related_eyecatch_url})\n"

                placeholder = f"<!-- RELATED_NOTE_PLACEHOLDER_{related_key} -->"
                figure.replace_with(placeholder)
                replacements_after_md.append((placeholder, final_markdown_link))

        h = html2text.HTML2Text()
        h.body_width = 0
        body_md = h.handle(str(soup))

        for placeholder, final_markdown_link in replacements_after_md:
            body_md = body_md.replace(placeholder, final_markdown_link)

        md_content = f"# {title}\n\n**URL:** {note_detail.get('note_url', '')}\n\n"
        if eyecatch_url:
            md_content += f"![eyecatch]({eyecatch_url})\n\n"
        md_content += "---\n\n"
        md_content += body_md

        if hashtags:
            md_content += "\n\n---\n\n## ハッシュタグ\n"
            for tag in hashtags:
                md_content += f"- {tag}\n"

        safe_title = sanitize_filename(title)
        file_name = f"{note_key}_{safe_title}.md"
        file_path = os.path.join(output_dir, file_name)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"  -> 完了: {file_path}")

    except Exception as e:
        print(f"  -> エラー: ファイルの保存中に予期せぬエラーが発生しました。 {note_key}, {e}")

def main():
    """メイン処理"""
    ARTICLE_LIMIT = 0 # 0で全件取得

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"記事の保存先: {os.path.abspath(OUTPUT_DIR)}")

    all_notes_info = get_all_notes_info(USER_ID)

    if not all_notes_info:
        print("記事情報が取得できなかったため、処理を終了します。")
        return

    note_keys = list(all_notes_info.keys())
    if ARTICLE_LIMIT > 0:
        print(f"\n★★★ お試しモード: 最新の{ARTICLE_LIMIT}件のみ取得します ★★★\n")
        note_keys = note_keys[:ARTICLE_LIMIT]

    total_notes = len(note_keys)
    print(f"\n合計{total_notes}件の記事を処理します。")
    for i, note_key in enumerate(note_keys):
        print(f"({i + 1}/{total_notes}) 記事を処理中: {note_key}")
        note_info = all_notes_info.get(note_key, {})
        save_as_markdown(note_key, note_info, all_notes_info, OUTPUT_DIR)
        time.sleep(3)

    print("\nすべての処理が完了しました。")

if __name__ == "__main__":
    main()
