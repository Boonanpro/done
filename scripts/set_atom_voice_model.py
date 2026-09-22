"""Select the model for the next Atom call. Active calls cannot be switched."""
import argparse
import json
from pathlib import Path
import httpx


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('provider',choices=['openai','gemini'])
    args=parser.parse_args()
    pairing=json.loads((Path(__file__).resolve().parents[1]/'.tmp/atom-wifi-pairing.json').read_text(encoding='utf-8'))
    response=httpx.post('http://127.0.0.1:48802/command',json={'key':pairing['key'],'action':'provider','provider':args.provider},timeout=5)
    if response.status_code!=200:
        raise SystemExit(f'Model selection failed ({response.status_code}): {response.json().get("detail", "unknown")}')
    print(json.dumps(response.json()))


if __name__=='__main__':main()
