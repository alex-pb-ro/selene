import os
from repo_dir_sync import LibRepo, OtherRepo

r = LibRepo(name="selene", libDirectory="src")
r.add(OtherRepo(name="mux", branch="mux", pathToLib=os.path.join("..", "selene-multiplexer", "src-selene")))
r.runMain()
