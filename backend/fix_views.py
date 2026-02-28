import re
import json

def parse_llm_output(raw_text):
    # Find JSON array
    match = re.search(r'\[.*\]', raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass
    return []

print(parse_llm_output('```json\n[{"name": "test"}]\n```'))
