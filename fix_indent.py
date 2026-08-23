import re
with open("tests/test_system_health.py", "r") as f:
    lines = f.readlines()
with open("tests/test_system_health.py", "w") as f:
    for line in lines:
        if line.startswith("    def test_llm_latency_passthrough_and_join") and not line.startswith("        def"):
            f.write(line)
        else:
            f.write(line)
