import json

path = r"c:\Users\yy3\GIT\squdi\src\qudi\jupyternotebooks\ple_repump.ipynb"
with open(path, "r", encoding="utf-8") as f:
    nb = json.load(f)

for cell in nb["cells"]:
    if cell["cell_type"] == "code":
        src = "".join(cell["source"])
        if "def do_custom_ple_scan" in src:
            src = src.replace("channel = scan.scanner_channels[scan._channel]", "channel = scan._channel")
            cell["source"] = src.splitlines(True)

with open(path, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1)
print("Updated successfully")
