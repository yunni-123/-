#!/usr/bin/env python3
import json, os, shutil

root = "/root/repro-agent-bench"
eval_dir = os.path.join(root, "eval")
shutil.rmtree(eval_dir, ignore_errors=True)
os.makedirs(eval_dir, exist_ok=True)

variants = sorted(os.listdir(os.path.join(root, "variants")))
mapping = []
for i, v in enumerate(variants, 1):
    en = f"eval_{i:02d}"
    shutil.copytree(os.path.join(root, "variants", v), os.path.join(eval_dir, en))
    mapping.append({"eval": en, "variant": v, "repo": v.split("--")[0],
                    "defect": v.split("--")[1] if "--" in v else "pristine"})
with open(os.path.join(eval_dir, "mapping.json"), "w") as f:
    json.dump(mapping, f, ensure_ascii=False, indent=1)
print(f"total {len(mapping)} variants -> {eval_dir}")
for m in mapping:
    print(m["eval"], m["variant"])
