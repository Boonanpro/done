import json
from pathlib import Path
from app.services.source_alignment import locate
r=locate('a3970e0b-f7dc-472e-ad63-e8c51382ddb3','d0127ce5-9873-4d94-ba31-45584f697f76','137cdb0f-33b1-4e29-a20e-4ac95ef10f69',
         [0,3,7,10,15,20,30,90,122.6,130,135,141.2,145,150,155,159.8,165,170,175,178],1.5)
Path('uploads/editor-recovery-check/source-alignment.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps(r,indent=2))
