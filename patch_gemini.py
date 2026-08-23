import re
with open('GEMINI.md', 'r') as f:
    text = f.read()

rule = "- **Review Before Merge:** Always run formal Code Quality and Security reviews on the builder subagent's completed implementation *before* executing a merge to the main branch. Do not bypass the review of the final code.\n- **Persistence:**"

text = text.replace("- **Persistence:**", rule)

with open('GEMINI.md', 'w') as f:
    f.write(text)
