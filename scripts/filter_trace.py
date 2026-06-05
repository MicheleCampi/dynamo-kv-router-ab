import json, sys
src, dst = sys.argv[1], sys.argv[2]
kept = 0
with open(src) as f, open(dst, "w") as out:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            if json.loads(line)["input_length"] <= 16384:
                out.write(line + "\n")
                kept += 1
        except Exception:
            pass
print(f"kept {kept}")
