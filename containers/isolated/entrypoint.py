"""Enter the trusted image source tree, independent of the mounted project's Python path."""

import runpy
import site
import sys

# the interpreter starts with -I -S so dependency .pth hooks cannot run before isolation
boundary = runpy.run_path("/opt/selene/src/selene/isolation/linux_network.py")["LinuxNetworkBoundary"]
boundary.enter()
site.main()
sys.path.insert(0, "/opt/selene/src")

from selene.isolation.bootstrap import IsolatedServerBootstrap

IsolatedServerBootstrap.run()
