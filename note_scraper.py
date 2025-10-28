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
USER_ID = "mujihayashi_note"
OUTPUT_DIR = f"./{USER_ID}_articles"

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
                    all_notes[key] = {"hashtags": hashtags}

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

def create_related_article_card(note_data):
    """取得した記事データから内部・外部リンク付きのMarkdownカードを生成します。"""
    title = note_data.get("name", "無題")
    note_key = note_data.get("key")
    external_url = note_data.get("note_url", "")
    eyecatch = note_data.get("eyecatch", "")
    
    # 内部リンク用のファイル名を生成
    safe_title = re.sub(r'[\/:"*?<>|]+', "_", title)
    internal_link = f"{note_key}_{safe_title}"

    description = note_data.get("description", "")
    if not description and "body" in note_data:
        clean_body = re.sub("<.*?>", "", note_data["body"]).replace('\n', ' ').strip()
        description = clean_body[:100] + '...' if len(clean_body) > 100 else clean_body

    user_name = note_data.get("user", {}).get("nickname", "")
    publish_date = note_data.get("publish_at", "")[:10]

    card = f"""
> ---
> ### [{title}]({internal_link}) [🌐]({external_url})\n"""
    if eyecatch:
        card += f"> ![thumbnail]({eyecatch})\n"
    card += f">\n> {description}\n>\n"
    if user_name and publish_date:
        card += f"> *{user_name} - {publish_date}*\n"
    card += "> ---"
    return card

def save_as_markdown(note_key, note_info, output_dir):
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
        for figure in soup.find_all("figure", attrs={"embedded-service": "note"}):
            related_key = figure.get("data-identifier")
            if not related_key or related_key == note_key: continue

            print(f"    -> 関連記事リンク発見: {related_key}。詳細を取得中...")
            time.sleep(3)
            related_detail = get_note_detail(related_key)

            if related_detail:
                card_md = create_related_article_card(related_detail)
                figure.replace_with(card_md)

        h = html2text.HTML2Text()
        h.body_width = 0
        body_md = h.handle(str(soup))

        md_content = f"# {title}\n\n"
        if eyecatch_url:
            md_content += f"![eyecatch]({eyecatch_url})\n\n"
        md_content += "---\n\n"
        md_content += body_md

        if hashtags:
            md_content += "\n\n---\n\n## ハッシュタグ\n"
            for tag in hashtags:
                md_content += f"- {tag}\n"

        safe_title = re.sub(r'[\/:"*?<>|]+', "_", title)
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
        save_as_markdown(note_key, note_info, OUTPUT_DIR)
        time.sleep(3)

    print("\nすべての処理が完了しました。")

if __name__ == "__main__":
    main()