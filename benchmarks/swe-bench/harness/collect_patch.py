import json,subprocess
from pathlib import Path
subprocess.run(['git','config','core.fileMode','false'],cwd='/testbed',check=True)
initial=set(json.loads(Path('/root/initial-untracked.json').read_text()))
new=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd='/testbed').decode().split('\0')
new=[p for p in new if p and p not in initial and p.split('/')[0] not in ('.ck','.ckignore','.sgrep')]
for p in new:subprocess.run(['git','add','-N','--',p],cwd='/testbed',check=True)
print(subprocess.check_output(['git','diff','--binary','HEAD'],cwd='/testbed').decode(),end='')
