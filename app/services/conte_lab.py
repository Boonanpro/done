"""Isolated, editable 3D previs experiment. No production jobs or clip renders."""
TOOLS = [{"type":"function", "name":"edit_scene", "description":"Edit the live 3D scene. A batch is atomic. Read the supplied current scene and preserve unrelated objects. Positions are world meters, Y up, Z forward. Camera position and target are world coordinates. Sequence replaces ONLY the named actor's action track. Timings are absolute seconds from scene start. Use undo for the last batch.", "strict":False, "parameters":{
    "type":"object", "properties":{
        "base_revision":{"type":"integer"},
        "summary":{"type":"string","description":"Short Japanese description of the actual change"},
        "operations":{"type":"array","maxItems":20,"items":{"type":"object","properties":{
            "op":{"type":"string","enum":["add","transform","sequence","camera","remove","retime","undo"]},
            "id":{"type":"string"},
            "kind":{"type":"string","enum":["person","car","table","box"]},
            "position":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3},
            "rotation":{"type":"number","description":"Y rotation in radians; zero faces +Z"},
            "scale":{"type":"number"},
            "target":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3},
            "fov":{"type":"number"},
            "factor":{"type":"number","description":"Multiply action durations and their offsets by this positive factor"},
            "actions":{"type":"array","maxItems":30,"items":{"type":"object","properties":{
                "type":{"type":"string","enum":["walk","crouch","stand","work","wait"]},
                "start":{"type":"number"},"duration":{"type":"number"},
                "to":{"type":"array","items":{"type":"number"},"minItems":3,"maxItems":3}
            },"required":["type","start","duration"]}}
        },"required":["op"]}}
    },"required":["base_revision","summary","operations"]}}]

INSTRUCTIONS = """You operate a minimal 3D previs scene, not a final video generator. Interpret natural Japanese requests using the current scene and conversation. Use edit_scene for changes, combining generic operations. No keyword routing, no external production jobs. The available simple rigged human can walk, crouch, stand and work with arms. Car has wings but no articulated doors. Do not claim unsupported actions. Explain limitations briefly when necessary. Choose sensible coordinates and timings without asking unnecessary questions. Behind-the-person camera must be positioned behind that person's facing direction and aimed at the requested subject. Prevent obvious intersections; car dimensions about 2.2x1.4x4m (wings width 5m), table 2.6x1x1.2m. Preserve unrelated scene data. An actor sequence should start at 0 unless user gives a time. Ask only if ambiguity materially changes the result. Reply briefly in Japanese. Use the current revision for edits. Operations are applied by the browser, so a proposed edit is not a completed edit until the tool result arrives."""

def live_config(state):
    import json
    return {"model":"gpt-live-1", "audio":{"output":{"voice":"meridian"}},
        "instructions":"あなたはダン。ユーザーと一緒に目の前の3Dコンテを編集します。自然で短い日本語で話します。変更の依頼はバックエンドへ委譲してください。単なる雑談はそのまま答えます。接続時は発言を待ちます。操作結果が届いてから短く報告し、未対応の動作はできたと言いません。",
        "delegation":{"type":"responses","responses":{"model":"gpt-6-astra","instructions":INSTRUCTIONS+"\nCurrent scene: "+json.dumps(state),"tools":TOOLS,"parallel_tool_calls":False,"reasoning":{"effort":"low"}}}}
