import requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

tok = requests.post("http://127.0.0.1:8000/api/v1/chat/login",
    json={"email":"dan-test@example.com","password":"DanTest2026x"}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}

r = requests.post("http://127.0.0.1:8000/api/v1/dan-notion/blocks", headers=H,
    json={"type":"page","properties":{"title":"ホバーテスト","is_folder":True,"view_mode":"grid"},"icon":"\U0001f9ea"})
print(r.status_code, r.text[:200])
fid = r.json()["id"]
print("folder:", fid)

names = [
    "AMEX 明細 2026年3月 最終版（承認済み・注釈付き）.pdf",
    "とても長いファイル名のサンプル_カード請求書_2026_03_final_annotated_v3.pdf",
    "mid_file.pdf",
]
for n in names:
    r2 = requests.post("http://127.0.0.1:8000/api/v1/dan-notion/blocks", headers=H,
        json={"type":"pdf","parent_id":fid,"properties":{"title":n,"original_name":n,"url":"https://example.com/test.pdf"},"icon":"\U0001f4c4"})
    print(r2.status_code, n[:30])
print("FOLDER_ID="+fid)
print("TOKEN="+tok)
