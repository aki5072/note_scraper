import streamlit as st
import re
from re import DOTALL  # DOTALLフラグを明示的にインポート
import os  # osモジュールを追加
import random
import time
from bs4 import BeautifulSoup, Comment
from datetime import datetime
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# バナー入力をパースする補助関数
def parse_banner_input(banner_text, selected_date):
    """
    バナー入力を解析し、日付に基づいてフィルタリングする。
    - 「使用は〇/〇まで」という表記があるバナーをチェックする。
    - 記載された日付が selected_date より前の場合は、そのバナーを除外する。
    - 記載された日付が selected_date 以降の場合は、警告メッセージを削除してバナーを通常通り含める。
    """
    # Add a newline before "↓★注意★" to ensure it starts a new block.
    banner_text = re.sub(r'(↓★注意★)', r'\n\1', banner_text)
    banners = []
    blocks = [blk.strip() for blk in re.split(r'\n\s*\n', banner_text.strip()) if blk.strip()]

    for blk in blocks:
        original_lines = [ln.strip() for ln in blk.split('\n') if ln.strip()]
        if not original_lines:
            continue

        is_expired = False
        lines_to_process = []

        # 期限切れチェックと警告行の除去
        for line in original_lines:
            match = re.search(r'使用は(\d{1,2})/(\d{1,2})まで', line)
            if match:
                month = int(match.group(1))
                day = int(match.group(2))
                year = selected_date.year
                if selected_date.month == 12 and month == 1:
                    year += 1
                try:
                    expiration_date = datetime(year, month, day).date()
                    if expiration_date < selected_date:
                        is_expired = True
                except ValueError:
                    pass
                # 警告行は処理対象から外す
                continue

            lines_to_process.append(line)

        if is_expired:
            continue

        if not lines_to_process:
            continue

        banner = {'text': '', 'image_url': '', 'link_url': ''}
        banner['text'] = re.sub(r'^[■“”"\'\s]+', '', lines_to_process[0]).strip()

        content = '\n'.join(lines_to_process)
        all_urls = re.findall(r'https?://[^\s]+', content)

        # Find image URL by keyword
        img_match = re.search(r'画像\s*→?\s*(https?://[^\s]+)', content, re.I)
        if img_match:
            banner['image_url'] = img_match.group(1)

        # Find link URL by keyword
        link_match = re.search(r'URL\s*→?\s*(https?://[^\s]+)', content, re.I)
        if link_match:
            banner['link_url'] = link_match.group(1)

        # Fallback logic
        if not banner['image_url']:
            for url in all_urls:
                if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    banner['image_url'] = url
                    break

        if not banner['link_url']:
            for url in all_urls:
                if url != banner['image_url']:
                    banner['link_url'] = url
                    break

        # Only append banner if it's valid (has a title and at least one URL)
        if banner.get('text') and (banner.get('image_url') or banner.get('link_url')):
            banners.append(banner)

    return banners

# ChromeDriver のパスは webdriver-manager が自動で管理します

# Selenium のオプション設定
options = Options()
options.add_argument("--headless")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

def scrape_product_data(url):
    if "/smartphone/page" in url:
        return "", "", "", "", ""
    try:
        # WebDriverの設定を改善
        options = Options()
        options.add_argument("--headless=new")  # 新しいヘッドレスモード
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=ja")

        # メモリ使用量の最適化
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-application-cache")
        options.add_argument("--disable-component-extensions-with-background-pages")

        # ページロード戦略の最適化
        options.page_load_strategy = 'eager'

        # User-Agentを最新に更新
        options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        # タイムアウトの設定を調整
        driver.set_page_load_timeout(30)  # ページロードのタイムアウトを30秒に短縮
        driver.implicitly_wait(3)  # 暗黙的な待機時間を3秒に短縮

        try:
            # カテゴリページ(ct数字)の場合、最小価格抽出
            prices_override = None
            if re.search(r'/shopbrand/ct\d+', url):
                driver.get(url)
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "r_categoryList"))
                )
                links = driver.find_elements(By.CSS_SELECTOR, "#r_categoryList a")
                if not links:
                    raise Exception("カテゴリページ内の商品リンクが見つかりません")
                hrefs = [a.get_attribute("href") for a in links]
                price_values = []
                # 各リンク先の価格を取得
                for link in hrefs:
                    driver.get(link)
                    WebDriverWait(driver, 5).until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    # 価格取得ロジックの一部を参照
                    for sel in ["#M_usualValue .m_price", "input[name='price1']", ".price", ".product-price", "#itemPrice"]:
                        elems = driver.find_elements(By.CSS_SELECTOR, sel)
                        for e in elems:
                            text = e.get_attribute("value") or e.text
                            nums = re.findall(r'[\d,]+', text)
                            if nums:
                                price_values.append(int(nums[0].replace(',', '')))
                                break
                        if price_values:
                            break
                if price_values:
                    prices_override = min(price_values)
                # 最初のリンクで他情報を取得
                url = hrefs[0]
            driver.get(url)

            # ページ読み込み完了を待機
            WebDriverWait(driver, 10).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )

            # ネットワークのアイドル状態を確認
            driver.execute_script("return window.performance.timing.loadEventEnd")

            # JSによるコンテンツ描画を待つために数秒間スリープする
            time.sleep(5)

            # 商品名の取得（複数の方法を試行）
            product_name = ""
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#itemInfo h1, .itemTitle, .item-name, h1.product-name"))
                )
                product_name_elements = driver.find_elements(By.CSS_SELECTOR, "#itemInfo h1, .itemTitle, .item-name, h1.product-name")
                if product_name_elements:
                    product_name = product_name_elements[0].text.strip()
                    # 「※収穫期」などから始まる収穫期の記述を削除
                    product_name = re.sub(r'[\s（(※]*収[穫獲]期.*', '', product_name).strip()
                if not product_name:
                    raise Exception("商品名が取得できません")
            except Exception as e:
                product_name = f"【エラー】商品名が取得できませんでした: {str(e)}"

            # 商品説明の取得（複数の方法を試行）
            description_html = ""
            try:
                # JS実行によるコンテンツ取得を試みる (スクレイピング対策の回避)
                description_html = ""
                selectors = [
                    ".detailTxt",
                    ".detailExtTxt",
                    ".itemDescription",
                    ".item-description",
                    ".detail-text",
                    "#itemDetail",
                    ".product-description"
                ]

                for selector in selectors:
                    try:
                        js_script = f"return document.querySelector('{selector}').innerHTML;"
                        content = driver.execute_script(js_script)
                        if content and content.strip():
                            description_html = content
                            break
                    except:
                        continue

                if not description_html:
                    raise Exception("商品説明が見つかりません")
            except Exception as e:
                description_html = f"【エラー】商品説明取得に失敗: {str(e)}"

            # strongタグのテキスト取得を改善
            extracted_strong_text = ""
            try:
                strong_elements = driver.find_elements(By.CSS_SELECTOR, ".detailTxt strong, .detailExtTxt strong, .itemDescription strong, .product-description strong")
                strong_texts = [elem.text.strip() for elem in strong_elements if elem.text.strip() and "[備考欄]" not in elem.text]
                if strong_texts:
                    extracted_strong_text = ", ".join(strong_texts)
                    description_html = description_html.replace("$", extracted_strong_text)
                else:
                    description_html = description_html.replace("、$", "")
            except:
                description_html = description_html.replace("、$", "")

            # HTMLタグを除去して説明文を取得
            description = re.sub(r'<[^>]*>', '', description_html).strip()

            # 画像URLの取得（複数の方法を試行）
            image_url = ""
            try:
                image_selectors = [
                    ".M_imageMain img",
                    ".mainImage img",
                    ".item-image img",
                    "#itemImage img",
                    ".product-image img"
                ]

                for selector in image_selectors:
                    try:
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            image_url = elements[0].get_attribute("src")
                            if image_url:
                                break
                    except:
                        continue

                if not image_url:
                    raise Exception("画像URLが見つかりません")
            except Exception as e:
                image_url = f"【エラー】画像URL取得に失敗: {str(e)}"

            # 商品価格の取得を改善
            prices = "【エラー】価格情報が見つかりません"
            try:
                price_selectors = [
                    "#M_usualValue .m_price",
                    "input[name='price1']",
                    ".price",
                    ".product-price",
                    "#itemPrice"
                ]

                for selector in price_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for elem in elements:
                            price_text = elem.get_attribute("value") or elem.text
                            if price_text:
                                price_numbers = re.findall(r'[\d,]+', price_text)
                                if price_numbers:
                                    price_number = int(price_numbers[0].replace(',', ''))
                                    # "円"を付けずに価格を文字列として返す
                                    prices = f"{price_number:,}"
                                    break
                        if prices != "【エラー】価格情報が見つかりません":
                            break
                    except:
                        continue

                if prices == "【エラー】価格情報が見つかりません":
                    raise Exception("価格情報が取得できません")
            except Exception as e:
                prices = f"【エラー】価格取得に失敗: {str(e)}"

            # ctカテゴリだった場合は最小価格を適用
            if prices_override is not None:
                prices = f"{prices_override:,}"

        finally:
            try:
                driver.quit()
            except:
                pass

        return product_name, description, image_url, extracted_strong_text, prices

    except Exception as e:
        error_msg = str(e).split('\n')[0] if '\n' in str(e) else str(e)
        return (
            f"【エラー】商品名取得に失敗: {error_msg}",
            f"【エラー】商品説明取得に失敗: {error_msg}",
            f"【エラー】画像URL取得に失敗: {error_msg}",
            "",
            f"【エラー】価格取得に失敗: {error_msg}"
        )

# スプレッドシートからコピーしたデータを解析する関数
def parse_input_text(input_text):
    import re
    products = []
    
    # Combined pattern to find either a quoted block or a standalone URL, preserving order.
    # Group 1: Quoted content, Group 2: Unquoted URL
    pattern = re.compile(r'"(.*?)"|(https?://[^\s"]+)', re.DOTALL)
    
    # Handle the messy "" separator from spreadsheets by replacing it with a newline.
    processed_input = input_text.replace('""', '"\n"')

    for match in pattern.finditer(processed_input):
        quoted_content, unquoted_url = match.groups()

        if quoted_content is not None:
            # This is a quoted block, process it as before.
            item = quoted_content
            product_catchphrases = []
            product_urls = []
            current_catchphrase_buffer = ""
            lines = [l.strip() for l in item.split('\n') if l.strip()]
            
            for line in lines:
                url_matches = list(re.finditer(r'https?://[^\s]+', line))
                if url_matches:
                    text_before_first_url = line[0:url_matches[0].start()].strip()
                    if text_before_first_url:
                        current_catchphrase_buffer = (current_catchphrase_buffer + " " + text_before_first_url).strip()

                    last_end = 0
                    for m in url_matches:
                        text_between_urls = line[last_end:m.start()].strip()
                        if text_between_urls:
                            current_catchphrase_buffer = (current_catchphrase_buffer + " " + text_between_urls).strip()

                        url = m.group(0).strip()
                        url = re.sub(r'[\u3000-\u303F,]+', '', url)
                        url = url.split(' ')[0].split('　')[0].strip()

                        product_urls.append(url)
                        product_catchphrases.append(current_catchphrase_buffer if current_catchphrase_buffer else "")
                        current_catchphrase_buffer = "" 
                        last_end = m.end()

                    text_after_last_url = line[last_end:].strip()
                    if text_after_last_url:
                        current_catchphrase_buffer = (current_catchphrase_buffer + " " + text_after_last_url).strip()
                else:
                    current_catchphrase_buffer = (current_catchphrase_buffer + " " + line).strip() if current_catchphrase_buffer else line
            
            if product_urls:
                if len(product_catchphrases) < len(product_urls):
                    product_catchphrases += [""] * (len(product_urls) - len(product_catchphrases))
                elif len(product_urls) < len(product_catchphrases):
                    product_catchphrases = product_catchphrases[:len(product_urls)]
                
                products.append({'catchphrases': product_catchphrases, 'urls': product_urls})

        elif unquoted_url is not None:
            # This is a standalone, unquoted URL.
            products.append({'catchphrases': [''], 'urls': [unquoted_url.strip()]})
            
    return products

# 商品URLに UTM パラメータを付与する関数
def clean_html(content):
    # Streamlitのコンポーネントが返す値を文字列に変換
    content = str(content)  # str() で文字列に変換
    soup = BeautifulSoup(content, "html.parser")
    return soup.get_text().strip()
def generate_product_urls(urls, campaign_type, campaign_date):
    generated_urls = []
    if campaign_type == "WEBCAS" or campaign_type == "WEBCAS(ビジュアルver)" or campaign_type == "Make Repeater_HTML":
        utm_source = "htmlmail"
    elif campaign_type in ["Make Repeater_レコメンド", "Make Repeater_レコメンド(ビジュアルver)"]:
        utm_source = "recommendmail"
    for url in urls:
        normalized = url.strip()
        if not normalized.endswith("/"):
            normalized += "/"
        
        # カテゴリページ(ct数字)のUTM付きURLを生成
        ct_match = re.search(r'/shopbrand/(ct\d+)', normalized)
        if ct_match:
            content = ct_match.group(1)
            utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email&utm_content={content}"
        else:
            # 商品詳細ページのUTM付きURLを生成
            m = re.search(r'shopdetail/(\d+)/', normalized)
            if m:
                shop_id = m.group(1)
                utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email&utm_content={shop_id}"
            else:
                # pageXXX.html形式のURL
                page_match = re.search(r'/(page\d+\.html)', normalized)
                if page_match:
                    content = page_match.group(1)
                    utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email&utm_content={content}"
                else:
                    # その他のURLもそのままUTM付きで出力
                    utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email"
        generated_urls.append(utm_url)
    return generated_urls, []

# PROMPTSの定義を修正
PROMPTS = {
    "メルマガ件名_短いキャッチと「」の商品名2個": """# 📩 メルマガ用：件名・キャッチコピー作成プロンプト

---

## 🔧【共通前提：文字数カウントルール】

本プロンプトでは、文字数は以下のルールに従ってカウントしてください：

- 改行（\\n）および行頭・行末のスペースはカウントしない。
- 単語間に必要な半角スペースがある場合、それは1文字としてカウント。
- それ以外のスペース・改行はすべて無視した上で文字数を算出する。
- Pythonにおける以下の処理に基づいた文字数制限を厳守すること：

```python
import re
processed_text = input_text.replace('\\n', '')
processed_text = re.sub(r'(?<=\S) (?=\S)', '∴', processed_text)
processed_text = processed_text.replace(' ', '')
processed_text = processed_text.replace('∴', ' ')
len(processed_text)
```

※生成したデータを出力する際、文字数チェックにおいて1行でも【条件】を満たしていない行がある場合、その案全体を破棄し、条件をすべて満たすまで再生成を繰り返してください。必ず**すべての行が指定の文字数範囲内に収まること**を厳守してください。

---

## ✍️【プロンプト指示】

あなたは、メルマガの件名・キャッチコピーを考える**プロのコピーライター**です。
以下の【条件】および【大前提】を厳守し、**2商品を紹介するメルマガの件名・キャッチコピー**を考案してください。

---

✅ 条件1：件名の構成・フォーマット
- 件名には、【】内に**日本語全角10文字以内で開封を促す一言**を入れてください。
- その後、**1商品目の短いキャッチコピー＋「商品名」＋2商品目の短いキャッチコピー＋「商品名」**をつなげてください。
- 例：
  - 【今が旬】薪火が引き出す旨み「昔ながらの干し芋セット」寒の時期だけの極上の甘み「しっとり濃厚・できたて干し芋セット」
- **開封を促す一言は1商品目の内容から最適なものを考えてください。**

✅ 条件2：プリヘッダー（キャッチコピー）
- **1商品目の説明文を元に、日本語全角16文字以内のキャッチコピーを3案**考案してください。
- ※文字数は【共通前提】に基づいて正確に計算してください。

✅ 条件3：開封を促す一言のバリエーション
- 「＠＠＠＠＠」を優先し、**日本語全角10文字以内の開封を促す一言を5案**考案してください。
- 商品の特性（産地・職人のこだわり・鮮度・限定性など）を活かした表現にしてください。

✅ 条件4：表現・トーン
- 商品の魅力が具体的に伝わる表現を使用してください。
- 「！」（感嘆符）は使用しないでください。落ち着きと信頼感を意識してください。
- 抽象的な表現（例：絶品・至高・格別）は避け、**具体的な特徴やこだわり**を記載してください。
- 詩的すぎる表現ではなく、テンポよく自然な語り口にしてください。

✅ 条件5：語句の使用制限
- 「名店」「数量限定」などの語句は、説明文に記載がある場合のみ使用可能。
- 安い商品ばかりではないので、「食卓」など、**家庭的な言葉は一切使用禁止です。**
- 以下の表現と類似の表現、壮大すぎる、カッコ良すぎる、キマってるような表現は**使用を禁止**します：
  - 「忘れられない味を。」
  - 「本当に美味しい〇〇を食べていますか。」
  - 「季節の便りをお届けします」
  - 「その信念の結晶ともいえる〇〇です。」
  - 「数字で示された品質をご賞味ください。」

✅ 条件6：読者層
- 読者は「50・60代以上の新聞読者層」、および「医師や経営者などのリピーター顧客層」です。

---

## 🧱【大前提】

- **【最重要】商品説明文に記載されていない情報の推察・創作は一切禁止します。すべての表現は、提供された説明文の事実に厳密に基づいている必要があります。意味の変わらない同義語への置換は許可しますが、推察による新たな情報の追加は禁止します。**
- **「お店売り」ではなく「職人売り」を基本**としてください。
  - （例：◯◯で話題のお店 → ❌ ／ ◯◯職人の丁寧な手仕事 → ⭕）
- 商品は、**地元で愛される逸品**または**まだ知られていないおすすめ商品**です。
- 職人のこだわりや他とは違う特徴を、**必ず具体的に**盛り込んでください。
- 締めの文に「○○の味をお楽しみください」などを使用する場合は、**商品固有の特徴を必ず記述**してください。
- 商品の魅力や背景が伝わる、**特別感のある表現**を心がけてください。

---

## 📤【出力指示】

以下それぞれ出力してください：

1. 件名案（【日本語全角10文字以内の開封ワード】＋キャッチ＋「商品名」 ×2）を3案
2. 開封ワード（日本語全角10文字以内）を5案（＠＠＠＠＠を考慮）
3. プリヘッダー（1商品目のみ、日本語全角16文字以内）を3案

---
それでは下記に各商品の説明文を共有します。

""",
    # 他のプロンプトも同様に修正
    "メルマガファーストビュー説明文": """# 📧 メールマガジン用ファーストビュー文章 作成プロンプト

---

## 🔧【共通前提：文字数カウントルール】

本プロンプトでは、文字数は以下のルールに従ってカウントしてください：

- 改行（\\n）および行頭・行末のスペースはカウントしない。
- 単語間に必要な半角スペースがある場合、それは1文字としてカウント。
- それ以外のスペース・改行はすべて無視した上で文字数を算出する。
- Pythonにおける以下の処理に基づいた文字数制限を厳守すること：

```python
import re
processed_text = input_text.replace('\\n', '')
processed_text = re.sub(r'(?<=\S) (?=\S)', '∴', processed_text)
processed_text = processed_text.replace(' ', '')
processed_text = processed_text.replace('∴', ' ')
len(processed_text)
```

※文字数に関する運用ルールと優先順位については、条件4で定義する基準に従ってください。

---

## ✍️【プロンプト指示】

あなたは、商品説明文の事実に忠実な、プロのコピーライターです。
50〜60代以上の新聞読者層に向けて、
商品説明文の事実に基づき、信頼感ある語り口で
複数商品をまとめて紹介するメルマガ冒頭用の導入文を、1まとまりの文章として2案作成する。
それに加えて、DESC法、新PASONAの法則、物語（ストーリーテリング）の3つの手法をそれぞれ用いて、さらに1案ずつ作成してください。

---

✅ 条件1：記号・改行・句読点の使用
- 「！」（感嘆符）は一切使用しない。
- **改行は必ず<br>タグを使用して、商品ごとに「コードブロック形式」で出力してください。**
- 句読点は自然な語のまとまりで使い、文節の途中で切らない。
- 改行位置は「読みやすさ」「一息で読める長さ」「文としてのまとまり」を最優先にする。


✅ 条件2：語句の使用制限
- 「名店」「数量限定」などの語句は、説明文に記載がある場合のみ使用可能。
- 安い商品ばかりではないので、「食卓」など、**家庭的な言葉は一切使用禁止です。**
- 以下の表現と類似の表現、壮大すぎる、カッコ良すぎる、キマってるような表現は**使用を禁止**します：
  - 「忘れられない味を。」
  - 「本当に美味しい〇〇を食べていますか。」
  - 「季節の便りをお届けします」
  - 「その信念の結晶ともいえる〇〇です。」
  - 「数字で示された品質をご賞味ください。」


✅ 条件3：レイアウト構成
- 1行目：読者の感情を引きつけるキャッチコピー。
- 2〜4行目：内容を補足し、情景・職人・味・背景などを簡潔に広げる。
- 各行は例文（＜例１＞〜＜例３＞）と同様に、意味のまとまりを保ちながら自然な位置で改行する。
- 全体を3〜4行で構成し、各行が読みやすい長さになるよう調整する。
- [キャッチ] や [補足文] などのラベルは出力に含めず、自然な文章として出力してください。
- 各行の冒頭に行番号や不要なスペースは入れない

#### ＜例１＞
[メインキャッチ] 丑の日にふさわしい、三つの焼きのうなぎです。<br>
[補足文] 四万十川の藁焼きに、名古屋職人の白焼き、<br>
[補足文] 宮崎では肝まで丁寧に焼き上げました。<br>
[補足文] 焼きも育ちも異なる三つのうなぎ、ぜひ比べてみてください。<br>

#### ＜例２＞
[メインキャッチ] ついに登場、鬼もろこし初入荷しました。<br>
[補足文] 熊も魅せられる極上の旨みと甘みです。<br>
[補足文] 粒立ちが良く、果皮は薄め、プリッと食感、<br>
[補足文] 標高四三〇メートルの農園からお届けします。<br>

#### ＜例３＞
[メインキャッチ] 「今年も鱧と向き合う夏です」
[補足文] そう語る村田大将のこだわり。
[補足文] 骨切り十年、旨味を活かし、祇園の季節にお届けします。
[補足文] 残りわずか、どうぞお早めに。


✅ 条件4：レイアウト・文字数・表現品質

メッセージは3〜4行構成とする。

各行の文字数は18文字以上25文字以内（日本語全角換算、上記カウントルールに準拠）を基本とするが、自然な語り口と読みやすさを最優先とする。

以下の段階的優先順位に従って判断する：

【優先順位】

最優先： 自然な語り口と読者の心地よい読書体験
第二優先： 各行18-25文字の基本範囲
許容範囲： 表現の質を保つため、1行あたり±4文字程度の超過・下限未満を積極的に許容
禁止事項： 違和感のある語尾調整や無理な言い換え
大幅に許容範囲を超える行（30文字以上または14文字未満）が含まれる場合のみ、その案全体を見直す。

改行は文字数調整ではなく、自然な日本語の語り口に従って行う。


✅ 条件5：表現スタイル
- 感情に訴えるが、**詩的すぎる表現**は一切禁止。
- 職人の手仕事・歴史・調理工程など「背景の温度」が感じられる構成にする。
- 比喩・体言止め・反復表現は使用可だが、多用は避ける。
- テンポよく、構文は読みやすく、丁寧語で締めくくる。
- 商品と直接関係のない抽象語・誇張は避ける。
- **「＠＠＠＠＠」**を適切に反映し、**メインキャッチ**に盛り込んでください。
- 説明文の《》の内容を、**補足文**に自然に盛り込んでください。


✅ 条件6：読者層に合わせた文体
- 読者は50〜60代以上の新聞購読者。
- 上品で落ち着いたトーン、過度な演出を避ける。
- 実直で、商品背景への関心を自然に引き出す構成にする。

---

🧱 大前提

- **【最重要】商品説明文に記載されていない情報の推察・創作は一切禁止します。すべての表現は、商品説明文に記載された事実を忠実に引用、または要約したものに限定してください。意味の変わらない同義語への置換は許可しますが、背景を補完するための憶測（例：「家族」「賄い」など）は固く禁じます。**
- 「お店売り」ではなく「職人売り」を基本とする。
  例：◯◯で話題のお店 → ❌ ／ ◯◯職人の丁寧な手仕事 → ⭕

- 読者層は50〜60代以上の新聞購読者。
  リピーターには医師・経営者層も含む。
  上品で押しつけのない語り口が好まれる。

- 商品紹介では、調理工程・味の特徴・人の背景・地域性など
  「具体的な魅力」に焦点をあて、商品価値が自然と伝わるよう丁寧に表現する。

- 条件３の＜例１＞＜例２＞＜例３＞の構成と温度感を意識してください。

---

それでは下記に各商品の説明文を共有します。

""",
    "注文ボタン上のメッセージ": """# 🛒 メルマガ用：注文促進メッセージ作成プロンプト

---

## 🔧【共通前提：文字数カウントルール】

本プロンプトでは、文字数は以下のルールに従ってカウントしてください：

- 改行（\\n）および行頭・行末のスペースはカウントしない。
- 単語間に必要な半角スペースがある場合、それは1文字としてカウント。
- それ以外のスペース・改行はすべて無視した上で文字数を算出する。
- Pythonにおける以下の処理に基づいた文字数制限を厳守すること：

```python
import re
processed_text = input_text.replace('\\n', '')
processed_text = re.sub(r'(?<=\S) (?=\S)', '∴', processed_text)
processed_text = processed_text.replace(' ', '')
processed_text = processed_text.replace('∴', ' ')
len(processed_text)
```

※文字数に関する運用ルールと優先順位については、条件4で定義する基準に従ってください。

---

## ✍️【プロンプト指示】

あなたは、商品説明文の事実に忠実な、プロのコピーライターです。
50〜60代以上の新聞購読者に向けて、
商品説明文の事実に基づき、信頼感ある語り口で
注文を後押しする短文メッセージを1商品につき2案ずつ作成する。
それに加えて、DESC法、新PASONAの法則、物語（ストーリーテリング）の3つの手法をそれぞれ用いて、さらに1案ずつ作成してください。

---

✅ 条件1：記号・改行・句読点・文章接続の使用
- 「！」（感嘆符）は一切使用しない。
- **改行は必ず<br>タグを使用して、商品ごとに「コードブロック形式」で出力してください。**
- 句読点は自然な日本語の流れを重視し、文節が途中で途切れる不自然な改行は避けてください。
- **助詞（は、の、を、が、に、で など）を効果的に使用し、文と文の自然な接続を重視してください。**
- **体言止めは1案につき最大1箇所までとし、連続使用を避けてください。**
- **読点のみで区切られた短文の連続を避け、完結した文章構成を心がけてください。**
- 文全体が流れるように読める構成を心がけてください。


✅ 条件2：語句の使用制限
- 「名店」「数量限定」などの語句は、説明文に記載がある場合のみ使用可能です。
- 安い商品ばかりではないので、「食卓」など、**家庭的な言葉は一切使用禁止です。**
- 以下の表現と類似の表現、壮大すぎる、カッコ良すぎる、キマってるような表現は**使用を禁止**します：
  - 「忘れられない味を。」
  - 「本当に美味しい〇〇を食べていますか。」
  - 「季節の便りをお届けします」
  - 「その信念の結晶ともいえる〇〇です。」
  - 「数字で示された品質をご賞味ください。」


✅ 条件3：行動喚起メッセージの追加
- 最終行には、商品の魅力に基づいた具体的な行動喚起表現を入れてください。
- 商品ごとに語尾や語調に変化をつけ、「ご堪能ください」「お楽しみください」のような繰り返しは避けてください。
- 抽象的な言葉ではなく、商品の具体的な魅力や特徴に基づいて締めくくってください。
- 下記のような例文は参考として使用しつつ、**必ずオリジナルの表現**を創出すること：

  ・この機会をお見逃しなく。
  ・◯◯ですので、他にはない味わいをお見逃しなく。
  ・老舗の職人が作る〇〇をご自宅で。

- また、全体の構成・語り口の参考として、以下のような完成イメージも併せて参考にしてください：
    ■例1■
    46年間変わらぬ味を届ける、<br>
    岡山・牛窓の洋食職人中山さん。<br>
    スパイス香るこだわりの一皿を、<br>
    週末便でお届けします。<br>
    ご自宅でじっくりご賞味ください。

    ■例2■
    野菜と牛肉の旨みだけで煮込んだ、<br>
    濃厚でまろやかな欧風カレー。<br>
    手間を惜しまぬ奥田シェフが、<br>
    週末便でお届けします。<br>
    週末のごちそうにいかがでしょうか。


✅ 条件4：レイアウト・文字数・表現品質

メッセージは3〜4行構成とする。

各行の文字数は11文字以上18文字以内（全角換算、上記カウントルールに準拠）を基本とするが、自然な語り口と読みやすさを最優先とする。

以下の段階的優先順位に従って判断する：

【優先順位】
1. **最優先：** 構成パターン（条件7）の5行構成と句読点配置
2. **第二優先：** 自然な語り口と読者の心地よい読書体験
3. **第三優先：** 各行11-18文字の基本範囲
4. **許容範囲：** 表現の質を保つため、1行あたり±6文字程度の超過を積極的に許容

禁止事項： 違和感のある語尾調整や無理な言い換え
大幅に許容範囲を超える行（23文字以上）が含まれる場合のみ、その案全体を見直す。

改行は文字数調整ではなく、自然な日本語の語り口に従って行う。


✅ 条件5：職人や店主の表現について
- 商品説明文に職人や生産者の名前がある場合は、自然に文中へ取り入れてください。
- 名前がない場合でも、「職人」「店主」「ご夫婦」など背景の伝わる表現で、人の手仕事が感じられる構成にしてください。
- **商品説明文に作り手の具体的な言葉や思いが記載されている場合は、「 」（カギ括弧）で囲んで直接引用し、職人の生の声として表現してください。**
- **作り手の言葉を引用する際は、以下のような導入表現を併用し、読者に作り手の人柄と情熱を伝えてください：**
  - 「そう語る○○さん」「○○の思いで」「○○と話す職人」
  - 「○○がモットーの」「○○という信念で」
- **カギ括弧による引用は1案につき1箇所までとし、多用による文章のリズム低下を避けてください。**
- 歴史・地名・こだわりの調理工程などを1行以上に反映させてください。


✅ 条件6：語り口とトーン・文章品質
- トーンは「実直で信頼感のある語り口」「押しつけのない落ち着いた温度感」とする。
- 美辞麗句よりも、「なぜ美味しいのか」「誰がどのように作ったのか」を具体的に伝える。
- **50-60代以上の読者層が好む「流れるような語り口」「完結した文章」を実現するため、以下を重視する：**
  - **助詞を適切に使用した自然な文の接続**
  - **体言止めの過度な使用を避けた、読みやすい文章構成**
  - **意味のまとまりを持った文の構成**
- 感情に寄せすぎず、読者が商品背景に関心を持てるような構成を目指す。
- ※表現の自然さを優先するため、制約に収めることを目的とした不自然な語尾変更や文字数調整は行わないでください。
- 表現に違和感がある場合は、積極的に見直し・提案を行ってください。
- 詩的・情緒的・抽象的な表現は一切禁止とします。
  これに該当する表現が1行でも含まれている場合、その行を含む案全体を破棄し、すべての行が自然で実直な表現に置き換わるまで再生成を繰り返してください。
  「はじける」「溶けるような」などの比喩表現、「喜びがあふれる」「心に染みる」などの抽象感情語も該当します。
  再生成後は、すべての行において表現の具体性・現実感・伝わりやすさを最優先してください。


✅ 条件7：構成パターン・表現品質
- **メッセージを1商品につき通常バージョンを2案、DESC法、新PASONAの法則、物語（ストーリーテリング）の手法で各1案、合計5案を作成する。**
- **句読点のパターンは設けず、各手法の構成や文章の流れが最も自然になるように句読点を配置する。**
- メッセージは必ず4行＋最終行（計5行）で構成する。

【運用ルール】
- **通常バージョンの2案は【通常バージョン1】のように、手法を用いた3案は【DESC法】のように、各案の冒頭に使用した手法を明記する。**
- 句読点のパターンは定めないが、文章が自然に読めるよう、その内容に最も適した句読点の配置を心がける。
- 各行の冒頭に行番号や不要なスペースは入れない。


---

🧱 大前提

- **【最重要】事実に基づく厳密な表現**
  - **商品説明文に記載されていない情報の推察、憶測、創作は一切禁止します。**
    - （例：「商品にするつもりがなかった」という記述から「賄い」「自家用」「家族」といった新しい言葉を創作してはいけません。）
  - **使用する語句は、すべて商品説明文からの直接引用、またはその内容を忠実に要約・抜粋したものに限定してください。**
  - 文章を自然にするための助詞・語尾の調整や、意味を変えない範囲での同義語（類語）への言い換えは許可します。ただし、元の文章にない新しい概念や情報を追加するような言葉の選択（例：「商品にするつもりがなかった」→「賄い」）は固く禁じます。

- 「お店売り」ではなく「職人売り」を基本とする。
  例：◯◯で話題のお店 → ❌ ／ ◯◯職人の丁寧な手仕事 → ⭕

- 読者層は50〜60代以上の新聞購読者。
  リピーターには医師・経営者層も含む。
  上品で押しつけのない語り口が好まれる。

- 商品紹介では、調理工程・味の特徴・人の背景・地域性など
  商品説明文に**記載されている**「具体的な魅力」に焦点をあて、商品価値が自然と伝わるよう丁寧に表現する。

- 同一商品のバリエーション（例：枝番付きの -1、-2 など）は、代表となる1商品に対してのみメッセージを作成してください。

---

それでは下記に各商品の説明文を共有します。

"""
}


def generate_email_prompt(prompt_template, parsed_products, descriptions, catchphrases, strong_texts_list, additional_notes, campaign_type, prices, prompt_key):
    """
    プロンプトテンプレートに基づき、全商品の説明文・キャッチコピー・strongテキスト・価格情報を
    枝番付きで埋め込んでプロンプトを生成する。
    parsed_products         : parse_input_text で得た構造化された商品リスト（dict のリスト）
    descriptions            : 各URLごとにスクレイピングして得た説明文のタプル（flattenされた順序）
    catchphrases            : 各URLごとのキャッチコピーのタプル（flattenされた順序）
    strong_texts_list       : 各URLごとのstrongテキストのタプル（flattenされた順序）
    additional_notes        : 追加事項テキスト
    campaign_type           : メルマガの種別
    prices                  : 各URLごとの価格のタプル（flattenされた順序）
    prompt_key              : 使用するプロンプトのキー文字列
    """

    # ビジュアルバージョンの場合の文字数制限の修正
    if campaign_type in ["WEBCAS(ビジュアルver)", "Make Repeater_レコメンド(ビジュアルver)"] and prompt_key == "注文ボタン上のメッセージ":
        prompt_template = prompt_template.replace(
            "各行の文字数は11文字以上18文字以内",
            "各行の文字数は11文字以上18文字以内 ※商品1のみ25文字以上40文字以内"
        )

    # ビジュアルバージョンの場合の文字数制限の修正
    if campaign_type in ["WEBCAS(ビジュアルver)", "Make Repeater_レコメンド(ビジュアルver)"] and prompt_key == "注文ボタン上のメッセージ":
        prompt_template = prompt_template.replace(
            "大幅に許容範囲を超える行（23文字以上）",
            "大幅に許容範囲を超える行（23文字以上。※商品1のみ1行を30文字以上を基準）"
        )

    # レコメンドメール・Make Repeater_HTMLの場合、改行タグの使用に関する追加指示
    if campaign_type in ["Make Repeater_レコメンド", "Make Repeater_レコメンド(ビジュアルver)", "Make Repeater_HTML"] and prompt_key in ["注文ボタン上のメッセージ", "メルマガファーストビュー説明文"]:
        prompt_template = prompt_template.replace(
            "**改行は必ず<br>タグを使用して、商品ごとに「コードブロック形式」で出力してください。**",
            "**各行の末尾に半角スペース2つを追加してMarkdownの強制改行記法を使用する。**"
        )
        prompt_template = prompt_template.replace("<br>", "")

    # ── ここから商品説明を組み立て ──
    products_section = ""
    flat_idx = 0
    for j, product in enumerate(parsed_products, start=1):
        for k, _ in enumerate(product['urls'], start=1):
            # 枝番の付け方：単一URLなら「商品 {j}」、複数URLなら「商品 {j}-{k}」
            if len(product['urls']) == 1:
                label = f"{j}"
            else:
                label = f"{j}-{k}"

            # テンプレート文字列を直接組み立てる
            section = (
                f"商品 {label} の説明文は以下のとおりです.\n\n"
                f"＊＊＊＊＊＊＊《＋＋＋＋＋、$$$》\n\n"
                f"価格: {prices[flat_idx]}\n\n"
                f"--------"
            )

            # 説明文を差し替え
            desc = descriptions[flat_idx]
            section = section.replace("＊＊＊＊＊＊＊", desc)

            # キャッチコピーを差し替え
            cp = catchphrases[flat_idx]
            if cp == "（キャッチコピーなし）":
                section = re.sub(r'《\＋＋＋＋＋、', '《', section)
                section = section.replace("＋＋＋＋＋", "")
            else:
                section = section.replace("＋＋＋＋＋", cp)

            # strongテキストを差し替え
            stxt = strong_texts_list[flat_idx]
            if stxt.strip():
                section = section.replace("$$$", stxt)
            else:
                section = section.replace("、$$$", "")

            products_section += section
            flat_idx += 1
    # ── ここまで商品説明組み立て ──

    # プロンプトテンプレートに商品説明を追加
    prompt_template += products_section

    # 追加事項の処理
    cleaned_additional_notes = clean_html(additional_notes)
    if cleaned_additional_notes:
        prompt_template = prompt_template.replace("＠＠＠＠＠", cleaned_additional_notes)
    else:
        if prompt_key == "メルマガ件名_短いキャッチと「」の商品名2個":
            prompt_template = prompt_template.replace("「＠＠＠＠＠」を考慮し、", "")
        elif prompt_key == "メルマガファーストビュー説明文":
            prompt_template = re.sub(
                r'- \*\*「＠＠＠＠＠」\*\*を適切に反映し、\*\*メインキャッチ\*\*に盛り込んでください。',
                '',
                prompt_template,
                flags=re.DOTALL
            )

    return prompt_template

def replace_template_content(template_content, search_pattern, replace_pattern):
    """テンプレート内の特定のパターンを置換する補助関数"""
    return re.sub(search_pattern, replace_pattern, template_content, flags=re.DOTALL)

def generate_html_from_template(template_path, products_data, campaign_date, campaign_type, banner_text, selected_date):
    """
    HTMLテンプレートを商品データとバナー情報で生成する関数
    banner_text: str, バナー入力欄の生テキスト
    """
    try:
        print("テンプレート生成開始")

        # Parse raw banner_text into structured list
        banner_data = parse_banner_input(banner_text or "", selected_date)

        # 通常版の場合のみ、バナーが3つ以上あれば3つまたは4つをランダムに選択
        if 'ビジュアル' not in campaign_type and len(banner_data) >= 3:
            num_to_place = random.choice([3, 4])
            # 実際に配置するバナー数を、利用可能なバナー数と選択数のうち小さい方に制限
            num_to_place = min(num_to_place, len(banner_data))
            banner_data = random.sample(banner_data, num_to_place)

        # 商品名の整形（WEBCAS系のみ）
        if campaign_type in ["WEBCAS", "WEBCAS(ビジュアルver)"]:
            # WEBCAS系の場合、エラーを含む商品はデフォルト表記にする
            processed_products = []
            for p in products_data:
                p_copy = p.copy()
                if "【エラー】" in str(p_copy.get('product_name', '')):
                    p_copy['product_name'] = ''
                    p_copy['price'] = ''
                    p_copy['image_url'] = ''
                    p_copy['description'] = ''
                processed_products.append(p_copy)
            products_data = processed_products
            
            def format_product_name(name):
                # "]"の直後に<br>を挿入
                name = re.sub(r'(】)', r'\1<br>', name)
                # "※"を常に改行付きに
                name = name.replace('※', '<br>※')
                return name

            # ★WEBCAS系: ctカテゴリを含む場合は商品名から差分を除いた共通部分のみを抽出
            formatted_products_data = []
            for i, p in enumerate(products_data):
                raw_name = p['product_name']
                # ctカテゴリを含む場合、かつ通常版WEBCASの場合、共通部分を抽出し、数量オプションを削除
                if campaign_type == "WEBCAS" and any(re.search(r'/shopbrand/ct\d+', u) for u in p.get('urls', [])):
                    names = p.get('product_names', [p['product_name']])
                    if len(names) >= 2:
                        diff1, diff2 = extract_difference(names[0], names[1])
                        raw_name = names[0].replace(diff1, '').strip()
                    # 数量オプション（全角括弧・各種単位表記）を削除
                    raw_name = re.sub(r'（.*?）', '', raw_name)
                    raw_name = re.sub(r'\d+(?:[-～~]\d+)?(?:kg|g|個(?:セット|入)?|本箱|本|尾|玉|箱|パック)', '', raw_name)

                # ビジュアルverの商品1以外、または通常版の場合に名前をフォーマット
                if campaign_type == "WEBCAS(ビジュアルver)" and i == 0:
                    formatted_name = raw_name
                else:
                    formatted_name = format_product_name(raw_name)

                # ctカテゴリ以外は raw_name をそのまま使用
                formatted_products_data.append({
                    'product_name': formatted_name,
                    'product_names': p.get('product_names', [p['product_name']]),
                    'urls': p['urls'],
                    'image_url': p['image_url'],
                    'price': p['price'],
                    'catchphrases': p['catchphrases'],
                    'description': p.get('description', ''),
                })
            products_data = formatted_products_data

        # テンプレートファイルを読み込む
        with open(template_path, 'r', encoding='utf-8') as file:
            template_content = file.read()

        # サンプルバナーを除去
        soup = BeautifulSoup(template_content, 'html.parser')

        # HTMLコメント内のバナーセクションを削除
        comments = soup.find_all(string=lambda text: isinstance(text, Comment) and 'バナーセクション' in text)
        for comment in comments:
            comment.extract()

        # バナーセクションのdivを探して削除
        banner_sections = soup.find_all(['div', 'table'], string=lambda text: text and ('バナーセクション' in text if text else False))
        for section in banner_sections:
            section.decompose()

        # バナーに関連する既存のHTMLブロックを削除
        banner_blocks = soup.find_all(['div', 'table'], style=lambda style: style and ('border:1px solid #cccccc' in style if style else False))
        for block in banner_blocks:
            block.decompose()

        template_content = str(soup)

        # ── ここから UTM付きURL生成 ──
        # products_data には 'urls': [元の URL, ...] が入っている想定なので、
        # キャンペーン種別と日付から UTM 付き URL を生成して新たなリストを作成する
        products_data_with_utm = []
        # UTMソースは WEBCAS系とレコメンド系で切り替え
        if campaign_type in ["WEBCAS", "WEBCAS(ビジュアルver)"]:
            utm_source = "htmlmail"
        else:
            utm_source = "recommendmail"
        for p in products_data:
            original_urls = p.get("urls", [])
            utm_urls = []
            for url in original_urls:
                normalized = url.strip()
                if not normalized.endswith("/"):
                    normalized += "/"
                ct_match = re.search(r'/shopbrand/(ct\d+)', normalized)
                if ct_match:
                    content = ct_match.group(1)
                    utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email&utm_content={content}"
                else:
                    m = re.search(r'shopdetail/(\d+)/', normalized)
                    if m:
                        shop_id = m.group(1)
                        utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email&utm_content={shop_id}"
                    else:
                        page_match = re.search(r'/(page\d+\.html)', normalized)
                        if page_match:
                            content = page_match.group(1)
                            utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email&utm_content={content}"
                        else:
                            utm_url = f"{normalized}?utm_source={utm_source}&utm_campaign={campaign_date}&utm_medium=email"
                utm_urls.append(utm_url)
            new_p = p.copy()
            new_p["urls"] = utm_urls
            products_data_with_utm.append(new_p)
        products_data = products_data_with_utm
        # ── ここまで UTM付きURL生成 ──

        is_visual = 'ビジュアル' in campaign_type
        print(f"ビジュアルモード: {is_visual}")

        if is_visual:
            # ビジュアル版の処理
            new_sections = generate_visual_sections(products_data, is_visual)
            # 修正後のバナーHTML生成部分
            banner_html = ""

            # まず「技わざ、おすすめ」タイトル画像を配置
            banner_html += '''
<!--★技わざおすすめ★-->
<div style="text-align:center; margin:40px 0;">
    <img alt="技わざ、おすすめ"
        src="http://www.makerepeater.jp/kcfinder/upload/56305/images/osusume.jpg"
        style="height:45px; width:300px"
        width="300" height="45">
</div>
'''

            # 1枚目と2枚目を通常サイズで縦に並べる
            for i in range(min(2, len(banner_data))):
                b = banner_data[i]
                raw_text = b.get("text", "")
                text = re.sub(r'^[■“”"\'\s]+', '', raw_text).strip()
                img_url = b.get("image_url", "").strip()
                link_url = b.get("link_url", "").strip()
                if text and img_url and link_url:
                    banner_html += f'''
<!-- バナーセクション（通常サイズ） -->
<p style="font-size:18px; font-weight:bold; margin-bottom:5px; text-align:center;">{text}</p>
<div style="text-align:center; margin:5px 0 40px 0; padding:10px; border:1px solid #cccccc; border-radius:8px; max-width:600px; margin-left:auto; margin-right:auto;">
    <a href="{link_url}" target="_blank">
        <img src="{img_url}" alt="{text}" style="width:100%; height:auto; border-radius:5px;" />
    </a>
</div>
'''
            # 3枚目以降を1行に2枚横並びにする
            if len(banner_data) > 2:
                banner_html += '<!-- バナーセクション（2列） -->\n<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">\n'
                remaining_banners = banner_data[2:]
                for i in range(0, len(remaining_banners), 2):
                    banner_html += '<tr>\n'
                    # 左側のバナー
                    b1 = remaining_banners[i]
                    raw_text1 = b1.get("text", "")
                    text1 = re.sub(r'^[“”"\'\s]+', '', raw_text1).strip()
                    img_url1 = b1.get("image_url", "").strip()
                    link_url1 = b1.get("link_url", "").strip()
                    banner_html += '<td style="width: 48%; vertical-align: top; padding: 0 1%;">\n'
                    if text1 and img_url1 and link_url1:
                        banner_html += f'''
<p style="font-size:16px; font-weight:bold; margin-bottom:5px; text-align:center;">{text1}</p>
<div style="text-align:center; margin:5px 0; padding:10px; border:1px solid #cccccc; border-radius:8px;">
    <a href="{link_url1}" target="_blank">
        <img src="{img_url1}" alt="{text1}" style="width:100%; height:auto; border-radius:5px;" />
    </a>
</div>
'''
                    banner_html += '</td>\n'
                    # スペーサー
                    banner_html += '<td style="width: 4%;"></td>\n'
                    # 右側のバナー
                    banner_html += '<td style="width: 48%; vertical-align: top; padding: 0 1%;">\n'
                    if i + 1 < len(remaining_banners):
                        b2 = remaining_banners[i + 1]
                        raw_text2 = b2.get("text", "")
                        text2 = re.sub(r'^[■“”"\'\s]+', '', raw_text2).strip()
                        img_url2 = b2.get("image_url", "").strip()
                        link_url2 = b2.get("link_url", "").strip()
                        if text2 and img_url2 and link_url2:
                            banner_html += f'''
<p style="font-size:16px; font-weight:bold; margin-bottom:5px; text-align:center;">{text2}</p>
<div style="text-align:center; margin:5px 0 20px 0; padding:10px; border:1px solid #cccccc; border-radius:8px;">
    <a href="{link_url2}" target="_blank">
        <img src="{img_url2}" alt="{text2}" style="width:100%; height:auto; border-radius:5px;" />
    </a>
</div>
'''
                    banner_html += '</td>\n'
                    banner_html += '</tr>\n'
                banner_html += '</table>\n'
            # テンプレートから商品とバナーのプレースホルダーを削除し、生成したコンテンツを挿入
            combined_html = '\n'.join(new_sections) + banner_html
            template_content = re.sub(
                r'<!-- 単一商品表示 -->.*?<!--★技わざおすすめ★-->',
                combined_html,
                template_content,
                flags=re.DOTALL
            )
            # サンプルバナーの残骸を削除
            template_content = re.sub(r'<!--★技わざおすすめ★-->.*?<!--/recommend_banner-->', '', template_content, flags=re.DOTALL)
        else:
            # 通常版の処理
            new_sections = generate_normal_sections(products_data)
            # Generate banner HTML blocks with sanitization
            banner_html = ""
            for b in banner_data:
                # 各フィールドを取得し、先頭に含まれる不要文字（例：引用符など）を削除
                raw_text = b.get("text", "")
                text = re.sub(r'^[“”"\'\s]+', '', raw_text).strip()
                img_url = b.get("image_url", "").strip()
                link_url = b.get("link_url", "").strip()
                # テキスト・画像・リンクがそろっている場合のみ出力
                if text and img_url and link_url:
                    banner_html += f'''\n<!-- バナーセクション -->\n<p style="font-size:18px; font-weight:bold; margin-bottom:5px;">{text}</p>\n<div style="text-align:center; margin:5px 0 20px 0; padding:10px; border:1px solid #cccccc; border-radius:8px; max-width:600px; margin-left:auto; margin-right:auto;">\n    <a href="{link_url}" target="_blank">\n        <img src="{img_url}" alt="{text}" style="width:100%; height:auto; border-radius:5px;" />\n    </a>\n</div>\n                    '''
            # Combine product sections and banner sections
            combined = '\n'.join(new_sections) + banner_html
            template_content = re.sub(
                r'<!-- ■■■■■■■■■■■■ 商品 ■■■■■■■■■■■■ -->.*?<!-- ■■■■■■■■■■■■ 必要に応じて検索窓 ■■■■■■■■■■■■ -->',
                combined,
                template_content,
                flags=re.DOTALL
            )

        # 出力ディレクトリの設定
        output_dir = '/Users/akiakko0526/Library/Mobile Documents/com~apple~CloudDocs/47_CLUB_メルマガマニュアル/メルマガ原稿'
        filename_suffix = '_ビジュアルver' if is_visual else ''
        base_filename = f'{campaign_date}_WEBCAS{filename_suffix}.html'
        output_path = os.path.join(output_dir, base_filename)

        # ファイル名の重複をチェック
        counter = 2
        while os.path.exists(output_path):
            filename_without_ext = os.path.splitext(base_filename)[0]
            new_filename = f'{filename_without_ext}_{counter}.html'
            output_path = os.path.join(output_dir, new_filename)
            counter += 1

        # HTMLファイルを保存
        with open(output_path, 'w', encoding='utf-8') as file:
            # レスポンシブ対応のCSSを追加
            css_style = '''
        @media screen and (max-width: 900px) {
            .order-button {
                # width: 100% !important;
                content: url(https://gigaplus.makeshop.jp/wazawaza/img/order_btn_new_v2.png);
            }
        }'''

            # CSSを<head>タグ内に挿入
            if '<head>' in template_content:
                template_content = template_content.replace('</head>', f'    <style>{css_style}</style>\n</head>')
            else:
                # <head>タグがない場合は<body>の直前に挿入
                template_content = template_content.replace('<body>', f'<style>{css_style}</style>\n<body>')

            file.write(template_content)

        print(f"HTMLファイル生成完了: {output_path}")
        return output_path

    except Exception as e:
        print(f"エラー発生: {str(e)}")
        raise ValueError(f'HTMLファイルの生成中にエラーが発生しました: {str(e)}')

def generate_visual_sections(products_data, is_visual):
    """ビジュアル版の商品セクションを生成する関数"""
    try:
        new_sections = []
        print(f"処理開始: 商品データ数 = {len(products_data)}")  # デバッグ用

        # 商品1（単一商品表示）
        if products_data and len(products_data) > 0:
            first_product = products_data[0]
            print(f"最初の商品データ: {first_product}")  # デバッグ用

            try:
                # 商品データの形式をチェックして標準化
                if isinstance(first_product, dict):
                    product_name = first_product.get('product_name', '')
                    urls = first_product.get('urls', [''])
                    page_url = urls[0] if urls else ''
                    image_url = first_product.get('image_url', '')
                    price = first_product.get('price', '')

                    # 複数URLがある場合のボタン生成
                    buttons_html = ""
                    if len(urls) > 1:
                        # 複数URLの場合、差分を抽出してボタンラベルに使用
                        product_names = first_product.get('product_names', [])

                        # 商品1では横並び（「WEBCAS」と同様）
                        buttons_html = '''
        <table style="width: 100%; margin-top: 20px;">
            <tr>'''

                        for idx, url in enumerate(urls):
                            if idx < len(product_names):
                                # 他の商品名との差分を抽出
                                if idx == 0 and len(product_names) > 1:
                                    diff, _ = extract_difference(product_names[0], product_names[1])
                                elif idx == 1 and len(product_names) > 1:
                                    _, diff = extract_difference(product_names[0], product_names[1])
                                elif idx > 1:
                                    # 3つ目以降は最初との差分
                                    diff, _ = extract_difference(product_names[idx], product_names[0])
                                else:
                                    diff = product_names[idx]

                                # 差分が空の場合は商品名をそのまま使用
                                button_label = diff if diff.strip() else product_names[idx]
                            else:
                                button_label = f"オプション{idx+1}"

                            # 横並びボタン（「WEBCAS」と同様）
                            buttons_html += f'''
                <td style="padding: 5px; text-align: center; vertical-align: middle;">
                    <p style="font-size: 16px; font-weight: bold; margin: 5px 0; color: #333;">{button_label}</p>
                    <a href="{url}" target="_blank">
                        <img class="order-button" alt="" src="https://gigaplus.makeshop.jp/wazawaza/img/order_btn_new.png" style="width: 90%; height: auto;">
                    </a>
                </td>'''

                            # ボタン間にスペーサーを追加（最後のボタン以外）
                            if idx < len(urls) - 1:
                                buttons_html += '''
                <td style="width: 4%;"></td>'''

                        buttons_html += '''
            </tr>
        </table>'''

                        # 複数URLの場合は価格に「〜」を付与
                        price_display = f"{price} 〜"
                    else:
                        # 単一URLの場合、ctカテゴリのみ「〜」を付与
                        price_display = f"{price} 〜" if any(re.search(r'/shopbrand/ct\d+', u) for u in urls) else f"{price}"

                elif isinstance(first_product, (list, tuple)):
                    if len(first_product) >= 4:
                        product_name, page_url, image_url, price = first_product
                        urls = [page_url] # Ensure urls is a list for the check below
                        buttons_html = f'''
        <div class="order-button" style="text-align: center; margin: 15px auto;">
            <a href="{page_url}" target="_blank">
                <img alt="注文ボタン" src="https://gigaplus.makeshop.jp/wazawaza/img/order_btn_new.png"
                    style="width: 300px; margin: 10px auto;">
            </a>
        </div>'''
                        # 単一URLの場合、ctカテゴリのみ「〜」を付与
                        price_display = f"{price} 〜" if any(re.search(r'/shopbrand/ct\d+', u) for u in urls) else f"{price}"
                    else:
                        raise ValueError(f"商品データの要素数が不足しています: {len(first_product)}")
                else:
                    raise ValueError(f"未対応の商品データ形式です: {type(first_product)}")

                print(f"商品1 解析結果: 名前={product_name}, URL={page_url}, 画像={image_url}, 価格={price}")  # デバッグ用
            except ValueError as e:
                print(f"データ解析エラー: {str(e)}")
                raise ValueError(f"商品データの形式が不正です: {first_product}")

            main_section = f'''<!-- 商品セクション開始 -->
<!-- 単一商品表示 -->
<div class="product-item" style="margin-bottom: 20px;">
    <div class="product-image" style="text-align: center;">
        <a href="{page_url}" target="_blank">
            <img alt="" src="{image_url}"
                style="border-radius: 15px; border: 7px solid #ffffff; width: calc(100% - 16px); height: auto; margin: 20px auto 10px; outline: 1px solid #666666; outline-offset: -1px;">
        </a>
    </div>
    <div class="product-info" style="margin: 0 auto; width: 96%;">
        <h3 style="margin: 10px 0; font-weight: bold; line-height: 21px;">
            {product_name}
        </h3>
        <p class="price" style="margin: 10px 0;">
            販売価格 <span style="font-size: 12px">(税込)</span> ￥ {price_display}
        </p>
        <p class="description" style="color: #666666; text-align: justify; margin: 10px 0;">
            商品説明がここに入ります。
        </p>
        {buttons_html}
    </div>
</div>
<!-- 単一商品表示 -->'''
            new_sections.append(main_section)

        # 商品2以降（2列商品表示）
        if len(products_data) > 1:
            sub_products = products_data[1:]
            for i in range(0, len(sub_products), 2):
                row_products = sub_products[i:i+2]
                # 2つ並べたときは、ビジュアルverではそのまま商品名を、通常版では差分をタイトルに使う
                if is_visual:
                    titles = [p.get('product_name', '') for p in row_products]
                else:
                    names0 = row_products[0].get('product_names', [])
                    names1 = row_products[1].get('product_names', []) if len(row_products) > 1 else []
                    if len(names0) >= 1 and len(names1) >= 1:
                        diff1, diff2 = extract_difference(names0[0], names1[0])
                    else:
                        diff1 = row_products[0].get('product_name', '')
                        diff2 = row_products[1].get('product_name', '') if len(row_products) > 1 else ''
                    titles = [diff1, diff2]
                row = '''<!-- 2列商品表示 -->
<table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
    <tr>'''
                for idx, product in enumerate(row_products):
                    # productはdict想定
                    urls = product.get('urls', [])
                    page_url = urls[0] if urls else ''
                    image_url = product.get('image_url', '')
                    price = product.get('price', '')

                    # 複数URLがある場合のボタン生成
                    buttons_html = ""
                    if len(urls) > 1:
                        # 複数URLの場合、差分を抽出してボタンラベルに使用（商品2以降は縦並び）
                        product_names = product.get('product_names', [])
                        for url_idx, url in enumerate(urls):
                            if url_idx < len(product_names):
                                # 他の商品名との差分を抽出
                                if url_idx == 0 and len(product_names) > 1:
                                    diff, _ = extract_difference(product_names[0], product_names[1])
                                elif url_idx == 1 and len(product_names) > 1:
                                    _, diff = extract_difference(product_names[0], product_names[1])
                                elif url_idx > 1:
                                    # 3つ目以降は最初との差分
                                    diff, _ = extract_difference(product_names[url_idx], product_names[0])
                                else:
                                    diff = product_names[url_idx]

                                # 差分が空の場合は商品名をそのまま使用
                                button_label = diff if diff.strip() else product_names[url_idx]
                            else:
                                button_label = f"オプション{url_idx+1}"

                            # 商品2以降では縦並び（上下）にボタンを配置
                            buttons_html += f'''
                    <div class="order-button_2rows" style="text-align: center; margin: 8px auto;">
                        <p style="font-size: 16px; font-weight: bold; margin: 3px 0; color: #333;">{button_label}</p>
                        <a href="{url}" target="_blank">
                            <img class="order-button" alt="" src="https://gigaplus.makeshop.jp/wazawaza/img/order_btn_new.png"
                                style="width: 90%; height: auto; margin: 3px 0;">
                        </a>
                    </div>'''

                        # 複数URLの場合は価格に「〜」を付与
                        price_display = f"{price} 〜"
                    else:
                        # 単一URLの場合は通常のボタン
                        buttons_html = f'''
                <div class="order-button_2rows" style="text-align: center; margin: 15px auto;">
                    <a href="{page_url}" target="_blank">
                        <img alt="注文ボタン" src="https://gigaplus.makeshop.jp/wazawaza/img/order_btn_new.png"
                            style="width: 90%; height: auto; margin: 10px 0;">
                    </a>
                </div>'''
                        # 単一URLの場合、ctカテゴリのみ「〜」を付与
                        price_display = f"{price} 〜" if any(re.search(r'/shopbrand/ct\d+/', u) for u in product.get('urls', [])) else f"{price}"
                    title = titles[idx] if idx < len(titles) else product.get('product_name', '')
                    cell = f'''
        <td style="width: 48%; vertical-align: top;">
            <div class="product-image" style="text-align: center;">
                <a href="{page_url}" target="_blank">
                    <img alt="" src="{image_url}"
                        style="border-radius: 15px; border: 7px solid #ffffff; width: 96%; height: auto; margin: 20px auto 10px; outline: 1px solid #666666; outline-offset: -1px;">
                </a>
            </div>
            <div class="product-info" style="margin-left: 7px;">
                <h3 style="margin: 10px 0; font-weight: bold; line-height: 21px;">
                    {title}
                </h3>
                <p class="price" style="margin: 10px 0;">
                    販売価格 <span style="font-size: 12px">(税込)</span> ￥ {price_display}
                </p>
                <p class="description" style="color: #666666; text-align: justify; margin: 10px 0;">
                    商品説明がここに入ります。
                </p>
                {buttons_html}
            </div>
        </td>'''
                    row += cell
                    # 1つ目のセルの後、中央にスペーサーを挿入
                    if idx == 0:
                        row += '''
        <td style="width: 4% !important;"></td>'''
                # 商品数が奇数の場合、右列に技わざロゴを挿入
                if len(row_products) % 2 != 0:
                    row += '''
        <td style="width: 48%; vertical-align: top;">
            <div class="product-image" style="text-align: center;">
                <a href="https://wazawaza-select.jp/" target="_blank">
                    <img alt="技わざロゴ" src="https://gigaplus.makeshop.jp/wazawaza/top/images/wazawazalpgo-PC.jpg"
                        style="border-radius: 15px; border: 7px solid #ffffff; width: 96%; height: auto; margin: 20px auto 10px; outline: 1px solid #666666; outline-offset: -1px;">
                </a>
            </div>
        </td>'''
                row += '''
    </tr>
</table>
<!-- 2列商品表示ここまで -->'''
                new_sections.append(row)

        print(f"セクション生成完了: {len(new_sections)}個のセクションを生成")  # デバッグ用
        return new_sections

    except Exception as e:
        print(f"ビジュアル版セクション生成中にエラー発生: {str(e)}")
        raise ValueError(f'ビジュアル版の商品セクション生成中にエラーが発生しました: {str(e)}')

def save_template(template_content, campaign_date, is_visual):
    """HTMLテンプレートを保存する関数"""
    try:
        # 保存先ディレクトリの設定
        output_dir = '/Users/akiakko0526/Library/Mobile Documents/com~apple~CloudDocs/47_CLUB_メルマガマニュアル/メルマガ原稿'

        # ファイル名の生成
        filename_suffix = '_ビジュアルver' if is_visual else ''
        base_filename = f'{campaign_date}_WEBCAS{filename_suffix}.html'
        output_path = os.path.join(output_dir, base_filename)

        # ファイル名の重複をチェックし、必要に応じて番号を付与
        counter = 2
        while os.path.exists(output_path):
            filename_without_ext = os.path.splitext(base_filename)[0]
            new_filename = f'{filename_without_ext}_{counter}.html'
            output_path = os.path.join(output_dir, new_filename)
            counter += 1

        # HTMLファイルを保存
        with open(output_path, 'w', encoding='utf-8') as file:
            file.write(template_content)

        return output_path

    except Exception as e:
        st.error(f'テンプレートの保存中にエラーが発生しました: {str(e)}')
        return None

def extract_difference(str1, str2):
    """商品名から差分を抽出する関数

    複数の商品名から共通部分を除いた差分を抽出します。
    数字と単位（例：玉、個、箱など）を一緒に扱います。
    括弧内の文字列が同一の場合は、括弧外の差分を優先して抽出します。

    Args:
        str1 (str): 1つ目の商品名
        str2 (str): 2つ目の商品名

    Returns:
        tuple: 各商品名から抽出された差分文字列のタプル
    """
    # 括弧内の文字列を一時的に除去して差分を確認
    base1 = re.sub(r'（.*?）', '', str1).strip()
    base2 = re.sub(r'（.*?）', '', str2).strip()

    # 数字と単位のパターンを抽出
    # 括弧内の差分を先にチェック
    brackets1 = re.findall(r'（(.*?)）', str1)
    brackets2 = re.findall(r'（(.*?)）', str2)
    if brackets1 and brackets2 and brackets1[0] != brackets2[0]:
        return (brackets1[0], brackets2[0])

    def extract_patterns(text):
        patterns = re.finditer(r'(\d+)([玉個箱本尾パック]+)', text)
        positions = []
        for match in patterns:
            start, end = match.span()
            positions.append((start, end, match.group()))
        return positions

    patterns1 = extract_patterns(base1)
    patterns2 = extract_patterns(base2)

    # Find common prefix
    prefix = ''
    i = 0
    while i < len(base1) and i < len(base2) and base1[i] == base2[i]:
        # 数字+単位の位置にいる場合はスキップ
        skip = False
        for start, end, _ in patterns1 + patterns2:
            if i in range(start, end):
                skip = True
                break
        if not skip:
            prefix += base1[i]
        i += 1

    # Find common suffix
    suffix = ''
    i = 1
    while i <= len(base1) and i <= len(base2) and base1[-i] == base2[-i]:
        if len(prefix) + len(suffix) >= len(base1) or len(prefix) + len(suffix) >= len(base2):
            break
        # 数字+単位の位置にいる場合はスキップ
        skip = False
        for start, end, _ in patterns1 + patterns2:
            if len(base1) - i in range(start, end):
                skip = True
                break
        if not skip:
            suffix = base1[-i] + suffix
        i += 1

    diff1 = base1[len(prefix):len(base1)-len(suffix)]
    diff2 = base2[len(prefix):len(base2)-len(suffix)]

    if diff1 and diff2:
        # 括弧外に差分がある場合はそれを使用
        return (diff1, diff2)
    else:
        # 括弧外に差分がない場合は括弧内の差分を使用
        brackets1 = re.findall(r'（(.*?)）', str1)
        brackets2 = re.findall(r'（(.*?)）', str2)
        if brackets1 and brackets2 and brackets1[0] != brackets2[0]:
            return (brackets1[0], brackets2[0])

        # それでも差分が見つからない場合は空文字を返す
        return ('', '')

def generate_normal_sections(products_data):
    """通常版の商品セクションを生成する関数"""
    new_sections = []
    # デバッグ用：全体のデータ構造を確認
    print("=== 商品データの構造確認 ===")
    for i, product in enumerate(products_data, 1):
        print(f"\n商品 {i} のデータ:")
        print(f"商品データキー: {product.keys()}")
        if 'prices' in product:
            print(f"価格リスト: {product['prices']}")
        print(f"価格: {product.get('price', 'なし')}")
        print(f"商品名: {product.get('product_names', [product.get('product_name', 'なし')])}")
        # 複数商品の場合、共通の商品名部分をタイトルに使用
        if len(product.get('urls', [])) > 1:
            names = product.get('product_names', [product['product_name']])
            if len(names) >= 2:
                diff1, diff2 = extract_difference(names[0], names[1])
                # 元の名前から差分を除いて共通名を取得
                common = names[0].replace(diff1, '').strip()
                name = common
            else:
                name = product['product_name']
            name = re.sub(r'（.*?）', '', name)
            # 小数kg、g、個セット/入、尾、箱などの単位表記を削除
            name = re.sub(r'(?:約?\d+(?:\.\d+)?kg|\d+(?:\.\d+)?g|\d+(?:[-～~]\d+)?(?:個(?:セット|入)?|本箱|本|尾|玉|箱|パック))', '', name)
            name = name.strip()
        else:
            name = product['product_name']
        # 空の括弧"()"や"（）"を削除
        name = re.sub(r'[\(（]\s*[）\)]', '', name)
        # '】'の直後に改行タグを追加
        name = name.replace('】', '】<br>')
        # '※'の直前に改行タグを追加
        name = name.replace('※', '<br>※')
        # 連続する<br>をまとめ、前後の空白・改行を除去
        name = re.sub(r'(?:<br>\s*)+', '<br>', name).strip()
        # 価格接尾辞：複数URLまたはカテゴリURL(ct数字)で「～」を付加
        if len(product['urls']) > 1 or any(re.search(r'/shopbrand/ct\d+', u) for u in product['urls']):
            price_suffix = "円 ～"
            print("\n=== 価格処理の詳細 ===")
            print(f"URLの数: {len(product['urls'])}")
            print(f"複数商品の処理開始:")
            # 複数商品の場合は常に最小価格を表示
            if 'prices' in product and len(product['prices']) > 1:
                print(f"利用可能な価格リスト: {product['prices']}")
                # 文字列価格を数値に変換してソート
                numeric_prices = []
                for p_str in product['prices']:
                    # カンマを除去して数値に変換
                    numeric_price = int(str(p_str).replace(',', ''))
                    numeric_prices.append(numeric_price)

                min_price = min(numeric_prices)
                # 元の形式（カンマ付き）で表示
                price = f"{min_price:,}"
                print(f"数値化された価格リスト: {numeric_prices}")
                print(f"最小価格: {min_price}")
                print(f"選択された価格（表示用）: {price}")
            else:
                price = f"{product['price']}"
                print(f"単一価格を使用: {price}")
        else:
            price_suffix = "円"
            price = f"{product['price']}"
        img = product['image_url']
        catchphrases = product['catchphrases']
        urls = product['urls']
        btns = ""

        # 画像HTMLを生成。単一商品の場合はリンクを追加
        image_html = f'<img alt="" src="{img}" style="width: 100%;border-radius:10px;" />'
        if len(urls) == 1:
            image_html = f'<a href="{urls[0]}" target="_blank">{image_html}</a>'

        # ボタンテキストの生成
        button_texts = []
        if len(urls) > 1:
            names = product.get('product_names', [])
            if len(names) >= 2:
                diff1, diff2 = extract_difference(names[0], names[1])
                button_texts = [diff1, diff2]
            else:
                button_texts = ['', '']

        if len(urls) == 1:
            # 1ボタン時は中央寄せ、テキストなし
            btns = f'''
            <td colspan="2" style="padding: 5px; text-align: center;">
                <a href="{urls[0]}" target="_blank">
                    <img class="order-button_single" alt="" src="https://gigaplus.makeshop.jp/wazawaza/img/order_btn_new.png" />
                </a>
            </td>
            '''
        else:
            # 2ボタン時は左右配置、差分テキスト表示（数字の小さい方を左側に配置）
            def get_sort_key(text):
                # サイズ表記の場合の並び替え
                size_match = re.search(r'([0-9]+)?L～(?:[0-9]+L)?', text)
                if size_match:
                    # 数字がない場合（L～）は1として扱う
                    size_num = int(size_match.group(1)) if size_match.group(1) else 1
                    return (0, size_num)  # サイズは最優先で並び替え

                # 数字＋単位の場合の並び替え
                text = text.translate(str.maketrans('１２３４５６７８９０', '1234567890'))
                numbers = re.findall(r'\d+', text)
                return (1, float(numbers[0]) if numbers else float('inf'))  # 数字＋単位は二番目の優先度

            sorted_data = sorted(zip(urls, button_texts), key=lambda x: get_sort_key(x[1]))
            for url, button_text in sorted_data:
                btns += f'''
                <td style="width: 48%; padding: 5px; text-align: center;">
                    <div class="btn_txt" style="font-size: 22px; font-weight: bold; margin-bottom: 10px;">
                        {button_text}
                    </div>
                    <a href="{url}" target="_blank">
                        <img class="order-button" alt="" src="https://gigaplus.makeshop.jp/wazawaza/img/order_btn_new.png" />
                    </a>
                </td>
                '''

            # ボタン間のスペーサー
            btns = btns.replace('</td>\n                <td', '</td>\n                <td style="width: 4%;"></td>\n                <td')

        section = f'''<!-- ■■■■■■■■■■■■ 商品{i} ■■■■■■■■■■■■ -->\n<div style="text-align: center; line-height: 1.5; margin:3.0em 0; padding-bottom: 2.5rem; border-bottom: 8px solid #CCCCCC;">
    <div class="item_title" style="border-radius:15px;color:#333333;font-size:24px;font-weight:bold; background:repeating-linear-gradient(135deg, #E4E4E4 0 4px, transparent 2px 20px),repeating-linear-gradient(45deg, #E4E4E4 0 4px, transparent 2px 20px),#fff; border: 4px solid #fff; box-shadow: 0 0 10px rgba(0, 0, 0, 0.4);overflow: hidden;padding: 10px; margin: 30px auto;">
        {name}
    </div>
    <div style="border-radius:15px; border:7px solid #ffffff; margin:5px auto; outline-offset:-1px; outline:#666666 solid 1px; vertical-align:bottom; max-width:500px; width:100%;">
        {image_html}
    </div>
    <div class="item_price" style="margin: 20px auto; font-size: 20px;">
        <span class="tax" style="font-size: 16px;">（税込）</span>{price}{price_suffix}
    </div>
    <p class="item_text" style="font-size: 16px; margin: 30px auto;">
        文章文章。<br>
        文章文章文章。<br>
        文章。<br><br>
        背中を押す文言。<br>
    </p>
    <table style="width: 100%; margin-top: 20px;">
        <tr>
            {btns}
        </tr>
    </table>
</div>
<!-- ■■■■■■■■■■■■ 商品{i}ここまで ■■■■■■■■■■■■ -->'''
        new_sections.append(section.strip())
    return new_sections

# フォーマット関数を修正
def format_display_css():
    """表示用のCSSスタイルを生成する関数"""
    return '''\n<style>\n    div[data-testid="stTextInput"] > div {\n        position: relative;\n        display: flex;\n        align-items: center;\n        overflow: hidden;\n    }\n\n    div[data-testid="stTextInput"] > div > div > input {\n        white-space: nowrap;\n        overflow: hidden;\n        text-overflow: ellipsis;\n        position: relative;\n        top: -10px;\n        padding: 0;\n    }\n\n    div[data-testid="stTextInputRootElement"] {\n        position: relative;\n    }\n\n    div[data-testid="stVerticalBlock"] {\n        position: relative;\n    }\n\n    div[data-testid="stVerticalBlockBorderWrapper"] {\n        position: relative;\n        top: 5px;\n    }\n\n    .stMarkdown a {\n        display: inline-block;\n        white-space: nowrap;\n        overflow: hidden;\n        text-overflow: ellipsis;\n        width: 100%;\n    }\n\n    label[data-testid="stWidgetLabel"] {\n        display: unset !important;\n    }\n\n    iframe[data-testid="stIFrame"] {\n        margin-top: -13px;\n        width: 143%;\n        overflow: hidden;\n    }\n\n    .product-divider {\n        border-top: 2px solid #d6932f;\n        margin: 20px 0;\n    }\n\n    @media screen and (max-width: 767px) {\n        .imadake_container {\n            flex-direction: column;\n        }\n        .imadake_main {\n            width: 100%;\n            float: none;\n            margin: 10px 0;\n            height: calc(520px - ((767px - 100vw) * 0.67));\n        }\n        .imadake_right_container {\n            width: 100%;\n            margin-bottom: 50px;\n        }\n        .imadake_right {\n            margin: 10px 0;\n            float: none;\n        }\n    }\n</style>\n'''

# 高さの微調整をするためのCSSを適用
st.markdown(format_display_css(), unsafe_allow_html=True)

# Streamlit の UI 部分
st.title("メルマガ用プロンプト生成ツール")
selected_date = st.date_input("📅 配信する日付を入力してください", value=None, min_value=datetime.today())
formatted_date = selected_date.strftime("%y%m%d") if selected_date else None
campaign_type = st.radio("メルマガの種類を選択", ["WEBCAS", "WEBCAS(ビジュアルver)", "Make Repeater_HTML", "Make Repeater_レコメンド", "Make Repeater_レコメンド(ビジュアルver)"], horizontal=True)

# プロンプト選択を複数選択可能なチェックボックスに変更
selected_prompts = []
st.write("使用するプロンプトを選択（複数選択可）")

# 「すべて選択」ボタンの状態をセッションで管理
if 'select_all_prompts' not in st.session_state:
    st.session_state.select_all_prompts = False

if st.button('すべて選択 / 解除'):
    st.session_state.select_all_prompts = not st.session_state.select_all_prompts
    # チェックボックスの状態を強制的に更新
    for prompt_key in PROMPTS.keys():
        st.session_state[f"checkbox_{prompt_key}"] = st.session_state.select_all_prompts

for prompt_key in PROMPTS.keys():
    # セッションステートを使ってチェックボックスの状態を制御
    if st.checkbox(prompt_key, key=f"checkbox_{prompt_key}", value=st.session_state.get(f"checkbox_{prompt_key}", False)):
        selected_prompts.append(prompt_key)

input_text = st.text_area("スプレッドシートからコピーしたデータを貼り付けてください", height=200)
additional_notes = st.text_area("追加事項（必要に応じて記入してください）", height=68)

# バナー設置欄を追加（WEBCAS系・Make Repeater系で表示）
banner_text = ""
if "WEBCAS" in campaign_type or "Make Repeater" in campaign_type:
    st.markdown("### バナー設置")
    banner_text = st.text_area(
        "バナー情報を下記フォーマットで貼り付けてください（例：バナー名、画像URL、リンクURLを改行区切りで記入）",
        height=180,
        value=""
    )

# 高さの微調整をするためのCSS
st.markdown(
    format_display_css(),
    unsafe_allow_html=True
)

# 商品情報と価格の表示
if st.button("生成"):
    if not selected_date:
        st.error("【エラー】配信する日付を入力してください。")
    elif not selected_prompts:
        st.error("【エラー】少なくとも1つのプロンプトを選択してください。")
    else:
        # 解析
        parsed_products = parse_input_text(input_text)
        with st.expander("🔍 解析されたURLデータ (クリックで展開)"):
            st.write(parsed_products)
        if len(parsed_products) == 0:
            st.error("【エラー】少なくとも1つのURLが必要です。")
            st.stop()
        else:
            # バナーURLチェック：絶対URL（http...png/jpg）以外の画像パスを検出し、エラー表示して処理停止
            invalid_urls = set()
            for line in banner_text.split('\n'):
                # 絶対URLの画像パスを抽出（http:// または https:// で始まるもの）
                abs_imgs = re.findall(r'(https?://[^\s]+?\.(?:png|jpg|jpeg|gif))', line, flags=re.IGNORECASE)
                # 相対パスかつ先頭が / で始まるものを抽出（ただし "//" はスキップ）
                rel_imgs = re.findall(r'(/[^ \t]+?\.(?:png|jpg|jpeg|gif))', line, flags=re.IGNORECASE)
                for rm in rel_imgs:
                    # '//' で始まる（スキーム相対） は問題なしと扱い、それ以外をエラー対象
                    if not rm.startswith('//'):
                        invalid_urls.add(rm)
                # その他、「.png/.jpg などの拡張子を含むが http:// や https:// を含まない文字列」を検出
                candidates = re.findall(r'\S+\.(?:png|jpg|jpeg|gif)', line, flags=re.IGNORECASE)
                for candidate in candidates:
                    # 「http://」や「https://」を含む場合は OK
                    if re.search(r'https?://', candidate, flags=re.IGNORECASE):
                        continue
                    # スキーム相対（先頭が "//"）の場合も OK
                    if candidate.startswith('//'):
                        continue
                    # 上記以外は不完全な URL とみなし、'→' が含まれるなら分割して後ろを検査
                    part = candidate
                    if '→' in candidate:
                        part = candidate.split('→', 1)[1]
                    # 「/」で始まるものは既に rel_imgs で検知しているため、ここでは「http」か「//」で始まらないものだけをエラーに
                    if part and not part.startswith('http') and not part.startswith('//'):
                        invalid_urls.add(part)
            if invalid_urls:
                for url in invalid_urls:
                    st.error(f"画像URLが不正です（httpで始まっていません）：{url}")
                st.stop()

            # 重複を除いた全URLを一度だけスクレイピング
            st.info("📡 商品情報の取得を開始します...")
            all_urls_in_order = []
            for p in parsed_products:
                for url in p.get('urls', []):
                    all_urls_in_order.append(url)

            # 重複を除いたユニークなURLリストを作成
            unique_urls = []
            seen_urls = set()
            for url in all_urls_in_order:
                if url != "URLを確認してください" and url not in seen_urls:
                    unique_urls.append(url)
                    seen_urls.add(url)

            # 並列スクレイピングの実行
            scraping_cache = {}
            if unique_urls:
                import concurrent.futures
                from threading import Lock

                progress_bar = st.progress(0)
                status_text = st.empty()
                processed_count = 0
                lock = Lock()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future_to_url = {executor.submit(scrape_product_data, url): url for url in unique_urls}

                    for future in concurrent.futures.as_completed(future_to_url):
                        url = future_to_url[future]
                        try:
                            data = future.result()
                            scraping_cache[url] = data
                        except Exception as exc:
                            scraping_cache[url] = (f"【エラー】{exc}", "", "", "", "")

                        # プログレスバーを更新
                        with lock:
                            processed_count += 1
                            progress = processed_count / len(unique_urls)
                            status_text.text(f"取得中: {processed_count}/{len(unique_urls)}")
                            progress_bar.progress(progress)

                status_text.empty()
                progress_bar.empty()
                st.success(f"✅ {len(unique_urls)}件の商品情報の取得が完了しました。")

            # キャッシュから結果を再構築
            results = []
            for url in all_urls_in_order:
                if url == "URLを確認してください":
                    results.append(("URLを確認してください", "URLを確認してください", "URLを確認してください", "URLを確認してください", "URLを確認してください"))
                else:
                    cached_data = scraping_cache.get(url)
                    if cached_data:
                        results.append(cached_data)
                    else:
                        results.append((f"【エラー】{url}のデータが見つかりません", "【エラー】", "【エラー】", "", "【エラー】"))

            # 以降、parsed_productsを使う
            # 例: catchphrases, urls = zip(*[(cp, url) for p in parsed_products for cp, url in zip(p['catchphrases'], p['urls'])])
            # ...既存の処理...
            catchphrases, urls = zip(*[(cp, url) for p in parsed_products for cp, url in zip(p['catchphrases'], p['urls'])])
            # UTMパラメータ付きのURLを生成
            generated_urls, _ = generate_product_urls(urls, campaign_type, selected_date.strftime("%Y%m%d"))

            # 商品データと価格を分割して取得（キャッシュから）
            product_names, descriptions, scraped_image_urls, strong_texts_list, prices = ([], [], [], [], [])
            if results:
                product_names, descriptions, scraped_image_urls, strong_texts_list, prices = zip(*results)

            with st.expander("🔍 取得された商品情報 (クリックで展開)"):
                st.write({
                    "商品名": product_names,
                    "説明": descriptions,
                    "画像URL": scraped_image_urls,
                    "取得されたstrongテキスト": strong_texts_list,
                    "価格": prices
                })

            error_descriptions = [desc for desc in descriptions if "【エラー】" in desc]
            success_count = len(descriptions) - len(error_descriptions)
            st.info(f"✅ 取得成功: {success_count} 件 / {len(descriptions)} 件")
            if len(error_descriptions) > 0:
                st.error("【エラー】以下の商品の情報が取得できませんでした:\n" + "\n".join(error_descriptions))
            
            # 選択されたプロンプトごとに個別のボックスで出力
            for prompt_key in selected_prompts:
                st.subheader(f"🔸 {prompt_key}")
                email_prompt = generate_email_prompt(
                    PROMPTS[prompt_key],
                    parsed_products,
                    descriptions,
                    catchphrases,
                    strong_texts_list,
                    additional_notes,
                    campaign_type,
                    prices,
                    prompt_key
                )

                # プロンプト出力用のテキストエリアとコピーボタン
                st.text_area(f"{prompt_key}のプロンプト", email_prompt, height=200, key=f"textarea_{prompt_key}")

                # JavaScriptで使用する際にエスケープが必要な文字を適切に処理
                escaped_prompt = (
                    email_prompt
                    .replace('\\', '\\\\')
                    .replace('`', '\`')
                    .replace('${', '\\${')
                    .replace('\n', '\\n')
                    .replace('\r', '\\r')
                    .replace('\t', '\\t')
                    .replace("'", "\\'")
                )

                # コピーボタンの実装
                safe_prompt_key = prompt_key.replace(" ", "_").replace("「", "").replace("」", "").replace("、", "_")
                clipboard_script = f'''\n                    <script>\n                        function copyToClipboard_{safe_prompt_key}() {{\n                            var text = `{escaped_prompt}`;\n                            navigator.clipboard.writeText(text).then(function() {{\n                                alert('📋 {prompt_key}のプロンプトをコピーしました！');\n                            }}, function(err) {{\n                                console.error('コピーに失敗しました', err);\n                            }});\n                        }}\n                    </script>\n                    <button onclick="copyToClipboard_{safe_prompt_key}()">📋 クリップボードにコピー</button>\n                    '''
                st.components.v1.html(clipboard_script, height=40)

                # プロンプト間の区切り線を追加
                if prompt_key != selected_prompts[-1]:  # 最後のプロンプト以外に区切り線を追加
                    st.markdown("---")

            # 各商品の商品名、ページURL、画像URLとそのコピー用ボタンを表示（枝番付き）
            flat_idx = 0
            for j, product in enumerate(parsed_products, start=1):
                for k, original_url in enumerate(product['urls'], start=1):
                        if len(product['urls']) == 1:
                        # 24 spaces indentation
                        # (this block is 24 spaces in the original)
                        # If only one URL, just use 商品 {j}
                            label = f"商品 {j}"
                        else:
                            label = f"商品 {j}-{k}"
                        gen_url = generated_urls[flat_idx]
                        scraped_img_url = scraped_image_urls[flat_idx]
                        product_name = product_names[flat_idx]
                        price = prices[flat_idx]

                        # ① 商品名の表示とコピー用ボタン
                        col_name_label, col_name_text, col_name_button = st.columns([2, 4, 1])
                        unique_name_key = f"product_name_input_{flat_idx}"
                        col_name_label.write(f"{label} の商品名:")
                        col_name_text.text_input("", product_name, key=unique_name_key)
                        clipboard_name_script = f"""\n                        <script>\n                            function copyName_{flat_idx}() {{\n                                var text = "{product_name}";\n                                navigator.clipboard.writeText(text).then(function() {{\n                                    alert('📋 商品名をコピーしました！');\n                                }}, function(err) {{\n                                    console.error('コピーに失敗しました', err);\n                                }});\n                            }}\n                        </script>\n                        <button onclick="copyName_{flat_idx}()">📋 コピー</button>\n                        """
                        with col_name_button:
                            st.components.v1.html(clipboard_name_script, height=40)

                        # ② ページURLの表示とコピー用ボタン
                        col_url_label, col_url_text, col_url_button = st.columns([2, 4, 1])
                        unique_page_key = f"page_url_input_{flat_idx}"
                        col_url_label.write(f"{label} のページURL:")
                        col_url_text.markdown(f"[{gen_url}]({gen_url})", unsafe_allow_html=True)
                        clipboard_script = f"""\n                        <script>\n                            function copyToClipboard_{flat_idx}() {{\n                                var text = "{gen_url}";\n                                navigator.clipboard.writeText(text).then(function() {{\n                                    alert('📋 商品URLをコピーしました！');\n                                }}, function(err) {{\n                                    console.error('コピーに失敗しました', err);\n                                }});\n                            }}\n                        </script>\n                        <button onclick="copyToClipboard_{flat_idx}()">📋 コピー</button>\n                        """
                        with col_url_button:
                            st.components.v1.html(clipboard_script, height=40)

                        # ③ 画像URLの表示とコピー用ボタン
                        col_img_label, col_img_text, col_img_button = st.columns([2, 4, 1])
                        unique_img_key = f"img_url_input_{flat_idx}"
                        col_img_label.write(f"{label} の画像URL:")
                        col_img_text.text_input("", scraped_img_url, key=unique_img_key)
                        clipboard_img_script = f"""\n                        <script>\n                            function copyImgToClipboard_{flat_idx}() {{\n                                var text = "{scraped_img_url}";\n                                navigator.clipboard.writeText(text).then(function() {{\n                                    alert('📋 画像URLをコピーしました！');\n                                }}, function(err) {{\n                                    console.error('コピーに失敗しました', err);\n                                }});\n                            }}\n                        </script>\n                        <button onclick="copyImgToClipboard_{flat_idx}()">📋 コピー</button>\n                        """
                        with col_img_button:
                            st.components.v1.html(clipboard_img_script, height=40)

                        # ④ 価格の表示とコピー用ボタン
                        col_price_label, col_price_text, col_price_button = st.columns([2, 4, 1])
                        unique_price_key = f"price_input_{flat_idx}"
                        col_price_label.write(f"{label} の価格:")
                        col_price_text.text_input("", price, key=unique_price_key)
                        clipboard_price_script = f"""\n                        <script>\n                            function copyPriceToClipboard_{flat_idx}() {{\n                                var text = "{price}";\n                                navigator.clipboard.writeText(text).then(function() {{\n                                    alert('📋 価格をコピーしました！');\n                                }}, function(err) {{\n                                    console.error('コピーに失敗しました', err);\n                                }});\n                            }}\n                        </script>\n                        <button onclick="copyPriceToClipboard_{flat_idx}()">📋 コピー</button>\n                        """
                        with col_price_button:
                            st.components.v1.html(clipboard_price_script, height=40)

                        st.markdown('<div style="border-top: 2px solid #d6932f; margin: 20px 0;"></div>', unsafe_allow_html=True)

                        flat_idx += 1

            # Make Repeater系の場合、バナー情報を表示
            if "Make Repeater" in campaign_type and banner_text:
                st.markdown("---")
                st.subheader("🔸 バナー情報")
                parsed_banners = parse_banner_input(banner_text, selected_date)
                if parsed_banners:
                    for i, banner in enumerate(parsed_banners, 1):
                        st.markdown(f"**バナー {i}**")

                        # バナー名
                        col_b_name_label, col_b_name_text, col_b_name_button = st.columns([2, 4, 1])
                        col_b_name_label.write("バナー名:")
                        banner_name = banner.get('text', '')
                        col_b_name_text.text_input("", banner_name, key=f"banner_name_{i}_{banner.get('link_url', '')}")
                        clipboard_banner_name_script = f'''
                        <script>
                            function copyBannerName_{i}() {{
                                navigator.clipboard.writeText(`{banner_name}`).then(() => alert('📋 バナー名をコピーしました！'), () => alert('コピーに失敗しました'));
                            }}
                        </script>
                        <button onclick="copyBannerName_{i}()">📋 コピー</button>
                        '''
                        with col_b_name_button:
                            st.components.v1.html(clipboard_banner_name_script, height=40)

                        # 画像URL
                        col_b_img_label, col_b_img_text, col_b_img_button = st.columns([2, 4, 1])
                        col_b_img_label.write("画像URL:")
                        banner_img_url = banner.get('image_url', '')
                        col_b_img_text.text_input("", banner_img_url, key=f"banner_image_url_{i}_{banner.get('link_url', '')}")
                        clipboard_banner_img_script = f'''
                        <script>
                            function copyBannerImg_{i}() {{
                                navigator.clipboard.writeText(`{banner_img_url}`).then(() => alert('📋 画像URLをコピーしました！'), () => alert('コピーに失敗しました'));
                            }}
                        </script>
                        <button onclick="copyBannerImg_{i}()">📋 コピー</button>
                        '''
                        with col_b_img_button:
                            st.components.v1.html(clipboard_banner_img_script, height=40)

                        # リンクURL
                        col_b_link_label, col_b_link_text, col_b_link_button = st.columns([2, 4, 1])
                        col_b_link_label.write("リンクURL:")
                        banner_link_url = banner.get('link_url', '')
                        col_b_link_text.text_input("", banner_link_url, key=f"banner_link_url_{i}_{banner.get('link_url', '')}")
                        clipboard_banner_link_script = f'''
                        <script>
                            function copyBannerLink_{i}() {{
                                navigator.clipboard.writeText(`{banner_link_url}`).then(() => alert('📋 リンクURLをコピーしました！'), () => alert('コピーに失敗しました'));
                            }}
                        </script>
                        <button onclick="copyBannerLink_{i}()">📋 コピー</button>
                        '''
                        with col_b_link_button:
                            st.components.v1.html(clipboard_banner_link_script, height=40)

                        if i < len(parsed_banners):
                            st.markdown('<div style="margin-top: 20px;"></div>', unsafe_allow_html=True)

                else:
                    st.write("有効なバナー情報がありません。")

            # ループ外に「全ての商品URLを開く」ボタンを配置（1つだけ）
            all_urls = list(generated_urls)
            button_script = f"""\n            <script>\n                function openAllUrls() {{\n                    var urls = {str(all_urls)};  # リストを文字列に変換\n                    urls.forEach(url => {{\n                        window.open(url, '_blank');\n                    }});\n                }}\n            </script>\n            <button onclick="openAllUrls()">全ての商品URLを開く</button>\n            """
            st.components.v1.html(button_script, height=60)

        # HTMLファイルの生成（WEBCASの場合のみ）
        print(f"=== キャンペーンタイプ確認: {campaign_type} ===")
        print(f"WEBCAS判定: {'WEBCAS' in campaign_type}")
        st.write(f"🔍 キャンペーンタイプ: {campaign_type}")
        st.write(f"🔍 WEBCAS判定: {'WEBCAS' in campaign_type}")
        if "WEBCAS" in campaign_type:
            print("=== HTMLファイル生成処理開始 ===")
            st.write("🔍 HTMLファイル生成処理を開始します")
            template_dir = '/Users/akiakko0526/Library/Mobile Documents/com~apple~CloudDocs/47_CLUB_メルマガマニュアル/メルマガ原稿'
            template_filename = 'WEBCAS_テンプレート_ビジュアルver.html' if 'ビジュアル' in campaign_type else 'WEBCAS_テンプレート_ver3.html'
            template_path = os.path.join(template_dir, template_filename)
            print(f"テンプレートパス: {template_path}")
            st.write(f"🔍 テンプレートパス: {template_path}")

            # HTML生成用の最終的な商品データリストを構築
            products_data_for_html = []
            for product_group in parsed_products:
                group_urls = product_group.get('urls', [])
                if not group_urls:
                    continue

                # グループ内の各URLからスクレイピング結果を取得
                scraped_results = [scraping_cache.get(u, ("【キャッシュエラー】", "", "", "", "【キャッシュエラー】")) for u in group_urls]

                scraped_names = [res[0] for res in scraped_results]
                scraped_prices_str = [res[4] for res in scraped_results]

                # 最小価格を計算
                min_price_str = ""
                valid_prices = []
                for p_str in scraped_prices_str:
                    try:
                        price_val = int(str(p_str).replace(',', ''))
                        valid_prices.append(price_val)
                    except (ValueError, TypeError):
                        pass
                if valid_prices:
                    min_price_str = f"{min(valid_prices):,}"

                # グループの代表データとして最初のURLの結果を使用
                representative_data = scraped_results[0]

                products_data_for_html.append({
                    'product_name': representative_data[0],
                    'product_names': scraped_names,
                    'description': representative_data[1],
                    'image_url': representative_data[2],
                    'price': min_price_str or representative_data[4], # 最小価格がなければ代表価格
                    'prices': scraped_prices_str,
                    'catchphrases': product_group['catchphrases'],
                    'urls': group_urls,
                })

            # HTMLファイルの生成
            generated_file = generate_html_from_template(
                template_path=template_path,
                products_data=products_data_for_html,
                campaign_date=selected_date.strftime("%Y%m%d"),
                campaign_type=campaign_type,
                banner_text=banner_text,
                selected_date=selected_date
            )

            if generated_file:
                st.success(f'HTMLファイルを生成しました: {os.path.basename(generated_file)}')