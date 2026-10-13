"""Preserve initialized submodules while removing their future Git history."""
from pathlib import Path
import shutil,subprocess,tempfile
root=Path('/testbed')
paths=subprocess.check_output(['git','submodule','foreach','--quiet','--recursive','pwd'],cwd=root).decode().splitlines()
for name in sorted(paths,key=lambda p:len(Path(p).parts),reverse=True):
 path=Path(name).resolve();path.relative_to(root)
 with tempfile.TemporaryDirectory(prefix='benchmark-submodule-') as tmp:
  clone=Path(tmp)/'checkout'
  subprocess.run(['git','clone','-q','--no-local','--depth','1','--single-branch','file://'+str(path),str(clone)],check=True)
  metadata=path/'.git'
  if metadata.is_dir():shutil.rmtree(metadata)
  else:metadata.unlink()
  shutil.move(str(clone/'.git'),str(metadata))
  subprocess.run(['git','config','core.fileMode','false'],cwd=path,check=True)
  subprocess.run(['git','config','--global','--add','safe.directory',str(path)],check=True)
